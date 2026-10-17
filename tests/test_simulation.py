"""Intégration : boucle de jeu, événements, réputation, fin de partie, score, rapport."""
from __future__ import annotations

import pytest

import config
from engine.event_bus import EventBus
from game.autoplay import play
from game.calendar import GameCalendar
from game.incident_engine import Phase
from game.reputation_engine import ReputationEngine
from game.report import build_html, generate_report
from game.scoring import compute_score, grade_for, percentile_for
from game.simulation import GameRuleError, Simulation, new_game
from tests.conftest import resolve_blockers


def test_initial_state(sim) -> None:  # type: ignore[no-untyped-def]
    assert sim.turn == 1
    assert sim.budget.budget_annuel_ssi == 72_000
    assert sim.portfolio.has("M07")
    assert sim.news and "Prise de fonction" in sim.news[0].text
    assert sim.can_advance()
    with pytest.raises(KeyError):
        Simulation(sim.data, "inconnue")


def test_turn_advances_and_blocks_on_pending(sim) -> None:  # type: ignore[no-untyped-def]
    report = sim.next_turn()
    assert report.turn == 2 == sim.turn
    sim.pending_events.append(next(iter(sim.events.events)))
    assert not sim.can_advance()
    with pytest.raises(GameRuleError):
        sim.next_turn()


def test_event_resolution(sim) -> None:  # type: ignore[no-untyped-def]
    eid, ev = next((k, e) for k, e in sim.events.events.items() if any(c.effets.get("cout") for c in e.choix))
    sim.pending_events.append(eid)
    choice = next(c for c in ev.choix if c.effets.get("cout"))
    spent = sim.budget.spent
    sim.resolve_event(eid, choice.id)
    assert sim.budget.spent == spent + float(choice.effets["cout"])
    assert eid not in sim.pending_events
    assert sim.decisions[-1].source == eid
    with pytest.raises(GameRuleError):
        sim.resolve_event(eid, choice.id)


def test_event_choice_unaffordable(data) -> None:  # type: ignore[no-untyped-def]
    s = Simulation(data, "pme_industrie", seed=3)
    eid, ev = next((k, e) for k, e in s.events.events.items() if any(c.effets.get("cout") for c in e.choix))
    c = next(c for c in ev.choix if c.effets.get("cout"))
    s.budget.spend(s.budget.remaining, "divers", "tout", 1)
    s.pending_events.append(eid)
    assert s.event_choice_available(eid, c.id)[0] is False
    with pytest.raises(GameRuleError):
        s.resolve_event(eid, c.id)


def test_all_event_effects_apply(data) -> None:  # type: ignore[no-untyped-def]
    for org_id in data.organisations:
        s = Simulation(data, org_id, seed=5)
        s.budget.budget_annuel_ssi += 10**6
        s.budget.categories["divers"]["alloue"] += 10**6
        for eid, ev in s.events.events.items():
            for c in ev.choix:
                s.pending_events = [eid]
                s.resolve_event(eid, c.id)
        assert s.decisions


def test_crisis_full_cycle(sim) -> None:  # type: ignore[no-untyped-def]
    bus_events = []
    sim.bus.subscribe("incident.*", lambda e: bus_events.append(e.topic))
    inc = sim._start_incident("INC-001")
    if not inc.detected:
        inc.phase = Phase.DETECTION
        sim._on_detected(inc)
    assert inc in sim.active_crises() and not sim.can_advance()
    rep_before = sim.reputation.global_score()
    assert rep_before < 75
    while (d := sim.incidents.pending_decision(inc)) is not None:
        res = sim.crisis_decide(inc.uid, d.id, next(c for c in d.choix if c.qualite == "mauvaise").id)
        assert res["record"].quality == "mauvaise"
    result = sim.crisis_close(inc.uid)
    assert result["cost"]["brut"] > 0
    assert sim.mistakes
    sim.bus.dispatch()
    assert "incident.detected" in bus_events and "incident.crisis_closed" in bus_events
    assert sim.phase_label(inc) == "Reprise"
    while not inc.closed:
        resolve_blockers(sim)
        sim.next_turn()
    assert any(n.text.startswith("Retour d'expérience") for n in sim.news)
    assert sim.missed_practices


def test_insurance_with_complaint(data) -> None:  # type: ignore[no-untyped-def]
    s = Simulation(data, "esn", seed=8)
    s.portfolio.add("M37", 0, initial=True)
    assert s.has_insurance()
    inc = s._start_incident("INC-002")
    if not inc.detected:
        inc.phase = Phase.DETECTION
        s._on_detected(inc)
    assert "plainte_72h" in {d.kind for d in s.compliance.deadlines_for(inc.uid)}
    s.notify_obligation(inc.uid, "plainte_72h")
    while (d := s.incidents.pending_decision(inc)) is not None:
        s.crisis_decide(inc.uid, d.id, d.choix[0].id)
    res = s.crisis_close(inc.uid)
    assert res["cost"]["rembourse"] > 0


def test_ebios_through_simulation(sim) -> None:  # type: ignore[no-untyped-def]
    from game.autoplay import _run_ebios
    reg = sim.reputation.values["regulateurs"]
    _run_ebios(sim)
    assert sim.risk.study.complete and sim.risk.study.completed_turn == sim.turn
    assert sim.reputation.values["regulateurs"] > reg
    assert sim.compliance.is_satisfied("nis2_analyse_risques", sim.turn, set(), sim.risk.study.completed_turn)
    with pytest.raises(ValueError):
        sim.complete_workshop(6)


def test_new_year_budget_and_maintenance(sim) -> None:  # type: ignore[no-untyped-def]
    sim.buy_measure("M16")
    sim.budget_flags["major_incidents"] = 1
    while sim.turn < 52:
        resolve_blockers(sim)
        sim.next_turn()
    resolve_blockers(sim)
    sim.next_turn()
    assert sim.turn == 53 and sim.budget.year == 2
    assert sim.budget.budget_annuel_ssi == pytest.approx(round(72_000 * 1.17, -2))
    assert sim.budget.spent > 0  # maintenance M16 imputée


def test_unfunded_maintenance_suspends_measure(data) -> None:  # type: ignore[no-untyped-def]
    s = Simulation(data, "pme_industrie", seed=2)
    s.portfolio.add("M29", 1)  # SOC hors de portée : maintenance non finançable
    s.turn = 52
    s.next_turn()
    assert s.portfolio.items["M29"].suspended
    s.portfolio.resume("M29", s.turn)
    assert not s.portfolio.items["M29"].suspended


def test_contract_loss_and_game_over(sim) -> None:  # type: ignore[no-untyped-def]
    sim.reputation.apply({"tous": -40})
    resolve_blockers(sim)
    sim.next_turn()
    assert sim.contracts_lost == 1
    assert any("rompu" in n.text for n in sim.news)
    sim.reputation.apply({"tous": -100})
    resolve_blockers(sim)
    report = sim.next_turn()
    assert report.game_over and sim.finished
    assert "20/100" in sim.game_over_reason
    with pytest.raises(GameRuleError):
        sim.next_turn()
    assert compute_score(sim).total <= 30


def test_game_ends_after_156_turns(data) -> None:  # type: ignore[no-untyped-def]
    s = Simulation(data, "telecom", seed=11)
    s.turn = config.TOTAL_TURNS
    report = s.next_turn()
    assert report.game_over and s.turn == config.TOTAL_TURNS
    assert "3 ans" in s.game_over_reason
    s.abandon()  # sans effet après la fin


@pytest.mark.parametrize("strategy", ["expert", "moyen", "novice"])
def test_autoplay_full_game(data, strategy: str) -> None:  # type: ignore[no-untyped-def]
    s = play(Simulation(data, "mairie", seed=21), strategy, seed=1)
    assert s.finished
    card = compute_score(s)
    assert 0 <= card.total <= 100
    assert card.grade in {"Insuffisant", "Moyen", "Bon", "Expert"}


def test_strategies_are_ranked(data) -> None:  # type: ignore[no-untyped-def]
    scores = {st: compute_score(play(Simulation(data, "hopital", seed=4), st, 4)).total
              for st in ("expert", "novice")}
    assert scores["expert"] > scores["novice"]


def test_scoring_helpers() -> None:
    assert grade_for(10) == "Insuffisant"
    assert grade_for(50) == "Moyen"
    assert grade_for(70) == "Bon"
    assert grade_for(90) == "Expert"
    from game.scoring import REFERENCE_MEAN
    assert percentile_for(0) < percentile_for(REFERENCE_MEAN) < percentile_for(100)
    assert percentile_for(REFERENCE_MEAN) == 50


def test_report_html(tmp_path, data) -> None:  # type: ignore[no-untyped-def]
    s = play(Simulation(data, "esn", seed=6), "moyen", 2)
    html = build_html(s)
    assert html.startswith("<!doctype html>")
    for section in ("Évaluation globale", "Les 3 meilleures décisions", "Les 3 erreurs critiques",
                    "Chronologie des incidents", "Bonnes pratiques manquées"):
        assert section in html
    assert "http" not in html.split("<footer>")[0].split("<style>")[1].split("</style>")[0]  # CSS autonome
    assert "<script" not in html
    path = generate_report(s, tmp_path)
    assert path.exists() and path.suffix == ".html"
    default = generate_report(s)
    assert default.parent == config.user_paths().reports_dir


def test_serialization_full(data) -> None:  # type: ignore[no-untyped-def]
    s = play(Simulation(data, "pme_industrie", seed=9), "expert", 9)
    restored = Simulation.from_dict(data, s.to_dict())
    assert compute_score(restored).total == pytest.approx(compute_score(s).total)


def test_new_game_helper() -> None:
    s = new_game("mairie", seed=1, bus=EventBus())
    assert s.org.id == "mairie" and s.seed == 1
    assert s.current_date_label() == GameCalendar().format_date(config.START_DATE)
    assert s.visible_incidents() == []


def test_reputation_engine() -> None:
    r = ReputationEngine()
    assert r.global_score() == pytest.approx(sum(config.REPUTATION_INITIAL[k] * w
                                                 for k, w in config.REPUTATION_WEIGHTS.items()))
    applied = r.apply({"presse": -100, "inconnu": 5})
    assert r.values["presse"] == 0 and "inconnu" not in applied
    r.weekly_update(1)
    assert r.values["presse"] > 0 and r.history
    with pytest.raises(ValueError):
        ReputationEngine(weights={"a": 0})
    other = ReputationEngine()
    other.load_dict(r.to_dict())
    assert other.values == r.values


def test_score_card_deduplicates(data) -> None:  # type: ignore[no-untyped-def]
    from game.state import DecisionRecord, Mistake
    s = Simulation(data, "hopital", seed=3)
    for i in range(3):
        s.decisions.append(DecisionRecord(1, f"INC-001#{i}", "Inc", "Q", "Même choix", "bonne", "fb"))
        s.mistakes.append(Mistake(1, "Même erreur", "x", "ref"))
    card = compute_score(s)
    assert len(card.best_decisions) == 1 and len(card.worst_mistakes) == 1
