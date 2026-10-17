"""Nouvelles mécaniques : difficultés, opérations SSI, gouvernance, migration de sauvegarde, réseau local."""
from __future__ import annotations

import random
import time

import pygame
import pytest

from game.autoplay import play
from game.difficulty import DIFFICULTIES, get_difficulty
from game.governance import OBJECTIVES, TRUST_INITIAL, board_probability, draw_objectives
from game.operations import (
    BURNOUT_WEEKS,
    PhishingKPI,
    TeamEngine,
    ThreatEngine,
    VulnerabilityEngine,
    measure_weekly_load,
)
from game.scoring import compute_score
from game.simulation import GameRuleError, Simulation
from tests.conftest import resolve_blockers


# -- difficultés ----------------------------------------------------------------------
def test_difficulty_catalogue() -> None:
    assert list(DIFFICULTIES) == ["decouverte", "standard", "expert", "crise"]
    levels = [d.level for d in DIFFICULTIES.values()]
    assert levels == sorted(levels)
    mults = [d.incident_mult for d in DIFFICULTIES.values()]
    assert mults == sorted(mults)
    assert get_difficulty("inconnue").id == "standard"
    assert get_difficulty(None).id == "standard"


def test_difficulty_changes_parameters(data) -> None:  # type: ignore[no-untyped-def]
    easy = Simulation(data, "hopital", seed=1, difficulty="decouverte")
    hard = Simulation(data, "hopital", seed=1, difficulty="crise")
    assert easy.budget.budget_annuel_ssi > hard.budget.budget_annuel_ssi
    assert easy.incidents.max_open < hard.incidents.max_open
    assert easy.risk.annual_probability("ransomware", 10) < hard.risk.annual_probability("ransomware", 10)
    assert easy.team.capacity(1) > hard.team.capacity(1)
    assert easy.decision_hint is not None


@pytest.mark.parametrize("years", [1, 2, 3])
def test_mandate_duration(data, years: int) -> None:  # type: ignore[no-untyped-def]
    sim = play(Simulation(data, "mairie", seed=3, years=years, difficulty="decouverte"), "expert", 3)
    assert sim.finished and sim.turn <= years * 52
    if sim.game_over_reason.startswith("Fin du mandat"):
        assert f"{years} an" in sim.game_over_reason
    with pytest.raises(ValueError):
        Simulation(data, "mairie", years=9)


def test_expert_beats_novice_on_every_difficulty(data) -> None:  # type: ignore[no-untyped-def]
    for dif in DIFFICULTIES:
        good = compute_score(play(Simulation(data, "esn", seed=7, difficulty=dif, years=1), "expert", 7)).total
        bad = compute_score(play(Simulation(data, "esn", seed=7, difficulty=dif, years=1), "novice", 7)).total
        assert good > bad, dif


# -- équipe ---------------------------------------------------------------------------------
def test_team_capacity_and_burnout(org) -> None:  # type: ignore[no-untyped-def]
    team = TeamEngine(org, get_difficulty("standard"), random.Random(0))
    cap = team.capacity(1)
    assert team.capacity(1, in_crisis=True) < cap
    assert team.reserve(cap, 1) and not team.reserve(0.5, 1)
    team.state.members = 3
    for week in range(BURNOUT_WEEKS + 30):
        team.end_week(week, background_load=100.0, in_crisis=False)
    assert team.state.departures >= 1 and team.state.members >= 1
    arrival = team.recruit(10)
    team.end_week(arrival - 1, 0.0, False)
    assert not team.state.pending_recruits
    team.add_reinforcement(5)
    assert team.capacity(6) > team.capacity(5 + 9)
    assert measure_weekly_load("externalisation") < measure_weekly_load("outils")


def test_overload_delays_deployments(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "pme_industrie", seed=4, difficulty="crise")
    sim.budget.adjust_budget(500_000, "outils")
    for mid in ("M06", "M08", "M09", "M10", "M13", "M18", "M16"):
        sim.buy_measure(mid)
    planned = {mid: st.ready_turn for mid, st in sim.portfolio.items.items() if not st.initial}
    resolve_blockers(sim)
    sim.next_turn()
    later = {mid: sim.portfolio.items[mid].ready_turn for mid in planned}
    assert any(later[m] > planned[m] for m in planned)
    assert any("retardé" in n.text for n in sim.news)


def test_actions_consume_capacity(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "pme_industrie", seed=4)
    sim.team.state.used = sim.team.capacity(sim.turn)
    with pytest.raises(GameRuleError, match="surchargée"):
        sim.compliance_action("registre")
    with pytest.raises(GameRuleError):
        sim.complete_workshop(1)
    sim.team.state.used = 0
    sim.compliance_action("registre")
    assert sim.team.state.used > 0


# -- vulnérabilités ----------------------------------------------------------------------------
def test_vulnerability_lifecycle(data, org) -> None:  # type: ignore[no-untyped-def]
    eng = VulnerabilityEngine(org, data.vulns, get_difficulty("standard"), random.Random(1))
    assert all(not d.organisations or org.id in d.organisations for d in eng.defs.values())
    created = [v for v in (eng.spawn(t, {"M26"}) for t in range(200)) if v]
    assert created and len({v.cve for v in created}) == len(created)
    v = created[0]
    f0 = eng.factor(eng.definition(v).type)
    assert f0 > 1.0
    eng.apply_action(v.uid, "planifier", 10)
    assert v.status == "planifiee" and v.due_turn % 4 == 0
    eng.weekly(v.due_turn, set(), exploit_allowed=False)
    assert v.status == "corrigee" and eng.mean_time_to_patch() is not None
    with pytest.raises(ValueError):
        eng.apply_action(v.uid, "urgence", 11)
    other = created[1]
    with pytest.raises(ValueError):
        eng.apply_action(other.uid, "ignorer", 5)
    eng.apply_action(other.uid, "contourner", 5)
    assert eng.action_cost(other.uid, "urgence") > eng.action_cost(other.uid, "planifier")


def test_auto_patch_and_reveal(data, org) -> None:  # type: ignore[no-untyped-def]
    eng = VulnerabilityEngine(org, data.vulns, get_difficulty("standard"), random.Random(2))
    for t in range(150):
        eng.spawn(t, set())
    for v in eng.items:
        v.visible = False
    assert eng.reveal_hidden(1.0)
    interne = [v for v in eng.items if eng.definition(v).exposition == "interne" and v.is_open]
    eng.weekly(1000, {"M08"}, exploit_allowed=False)
    assert all(v.status == "corrigee" for v in interne)


def test_exploited_vulnerability_triggers_incident(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "hopital", seed=5)
    sim.turn = 10
    cve = next(c for c, d in sim.vulns.defs.items() if d.exploitee and d.exposition == "internet"
               and sim.incidents.template_for_type(d.type))
    from game.operations import VulnInstance
    v = VulnInstance("V999", cve, 1, True, status="acceptee")
    sim.vulns.items.append(v)
    sim.vulns.rng = random.Random(0)
    sim.vulns.rng.random = lambda: 0.0   # exploitation certaine
    from game.simulation import TurnReport
    sim._weekly_operations(TurnReport(10))
    assert v.exploited_turn == 10
    assert sim.incidents.incidents
    assert any("acceptée puis exploitée" in m.title for m in sim.mistakes)


def test_vuln_actions_through_simulation(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "esn", seed=6)
    for t in range(60):
        sim.vulns.spawn(t, set())
    for v in sim.vulns.items:
        v.visible = True
    first, second = sim.vulns.items[:2]
    sim.vuln_action(first.uid, "urgence")
    assert sim.decisions[-1].source == first.uid
    with pytest.raises(GameRuleError):
        sim.vuln_action(first.uid, "urgence")
    sim.vuln_action(second.uid, "accepter")
    with pytest.raises(GameRuleError):
        sim.vuln_action("V000", "urgence")
    with pytest.raises(GameRuleError):
        sim.vuln_action(second.uid, "danser")


# -- menace et hameçonnage ----------------------------------------------------------------------
def test_threat_campaigns(data) -> None:  # type: ignore[no-untyped-def]
    eng = ThreatEngine(data.campaigns, get_difficulty("crise"), random.Random(3))
    started = [c for c in (eng.weekly(t) for t in range(1, 200)) if c]
    assert started
    eng.active = [{"id": "CAMP-03", "until": 50}]
    assert eng.factor("ddos", 10) > 2 and eng.factor("ddos", 60) == 1.0
    assert eng.level(10)[1] in ("Élevé", "Très élevé")
    other = ThreatEngine(data.campaigns, get_difficulty("crise"), random.Random(3))
    other.load_dict(eng.to_dict())
    assert other.active == eng.active


def test_phishing_kpi() -> None:
    kpi = PhishingKPI(0.2)
    for _ in range(8):
        kpi.quarterly(awareness=True, mail_filter=True)
    assert kpi.rate < 0.05 and kpi.factor() < 1
    rate = kpi.run_campaign(10, random.Random(0))
    assert 0 <= rate <= 0.1 and kpi.last_measure()[0] == 10
    kpi2 = PhishingKPI(0.2)
    kpi2.quarterly(awareness=False, mail_filter=False)
    assert kpi2.rate > 0.2


def test_phishing_campaign_action(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "mairie", seed=2)
    spent = sim.budget.spent
    sim.run_phishing_campaign()
    assert sim.budget.spent > spent and sim.phishing.measured
    sim.budget.spend(sim.budget.remaining, "divers", "tout", 1)
    with pytest.raises(GameRuleError):
        sim.run_phishing_campaign()
    with pytest.raises(GameRuleError):
        sim.hire_reinforcement()


# -- gouvernance ---------------------------------------------------------------------------------
def test_board_meeting_cycle(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "telecom", seed=8)
    with pytest.raises(GameRuleError):
        sim.resolve_board("bilan")
    while not sim.pending_board:
        resolve_blockers(sim) if sim.turn % 13 else None
        if sim.pending_board:
            break
        for inc in sim.active_crises():
            while (d := sim.incidents.pending_decision(inc)) is not None:
                sim.crisis_decide(inc.uid, d.id, d.choix[0].id)
            sim.crisis_close(inc.uid)
        for e in list(sim.pending_events):
            sim.pending_events.remove(e)
        sim.next_turn()
    assert sim.turn % 13 == 0 and not sim.can_advance()
    opts = {o["id"]: o for o in sim.board_options()}
    assert set(opts) == {"rallonge", "recrutement", "exercice", "bilan"}
    assert 0.05 <= opts["rallonge"]["probability"] <= 0.95
    before = sim.trust
    res = sim.resolve_board("bilan")
    assert res["success"] and sim.trust > before and not sim.pending_board
    sim.pending_board = True
    budget = sim.budget.budget_annuel_ssi
    sim.rng.random = lambda: 0.0
    assert sim.resolve_board("rallonge")["success"]
    assert sim.budget.budget_annuel_ssi > budget
    sim.pending_board = True
    sim.resolve_board("exercice")
    assert sim.prep_until > sim.turn
    sim.pending_board = True
    assert sim.resolve_board("recrutement")["success"] and sim.team.state.pending_recruits
    sim.pending_board = True
    with pytest.raises(GameRuleError):
        sim.resolve_board("pot-de-vin")


def test_board_probability_bounds(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "mairie", seed=1)
    sim.trust = 0
    assert board_probability(sim, "rallonge") >= 0.05
    sim.trust = 100
    assert board_probability(sim, "rallonge") <= 0.95
    assert board_probability(sim, "bilan") == 1.0


def test_objectives_drawn_and_evaluated(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "esn", seed=9)
    assert len(sim.objectives) == 3 and all(o["id"] in OBJECTIVES for o in sim.objectives)
    pme = Simulation(data, "pme_industrie", seed=9, years=1)
    assert all(o["id"] != "OBJ-ISO" for o in draw_objectives(pme, random.Random(1), n=11))
    sim.objectives = [{"id": oid, "params": OBJECTIVES[oid].params(sim), "status": "en_cours", "turn": None}
                      for oid in OBJECTIVES if OBJECTIVES[oid].applies(sim)]
    sim.budget.record_fine(1000, 1, "test")
    sim.compliance.state.missed = 1
    sim.objective_flags["vuln_breach"] = True
    sim._update_objectives()
    status = {o["id"]: o["status"] for o in sim.objectives}
    assert status["OBJ-NOFINE"] == "echoue" and status["OBJ-VULN"] == "echoue"
    assert status["OBJ-NOTIF"] == "echoue" and status["OBJ-REP"] == "en_cours"
    sim._update_objectives_final()
    assert all(o["status"] != "en_cours" for o in sim.objectives if o["id"] in ("OBJ-REP", "OBJ-TRUST", "OBJ-PHISH"))
    assert compute_score(sim).components["objectifs"] < 1


def test_dismissal_by_direction(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "esn", seed=10, difficulty="expert")
    assert sim.trust == TRUST_INITIAL
    sim.trust = 1
    resolve_blockers(sim)
    report = sim.next_turn()
    assert report.game_over and "direction" in sim.game_over_reason
    assert compute_score(sim).total <= 30


def test_trust_recovers_slowly(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "mairie", seed=11, difficulty="decouverte")
    sim.trust = 40
    for _ in range(5):
        resolve_blockers(sim)
        sim.next_turn()
    assert 40 < sim.trust <= TRUST_INITIAL


# -- sauvegardes ------------------------------------------------------------------------------------
def test_v1_save_migration(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "hopital", seed=12, difficulty="expert", years=2)
    for _ in range(8):
        resolve_blockers(sim)
        sim.next_turn()
    state = sim.to_dict()
    old = {k: v for k, v in state.items() if k not in ("team", "vulns", "threat", "phishing", "trust",
                                                         "difficulty", "years", "objectives")}
    old["version"] = 1
    restored = Simulation.from_dict(data, old)
    assert restored.turn == sim.turn and restored.difficulty.id == "standard" and restored.years == 3
    full = Simulation.from_dict(data, state)
    assert full.difficulty.id == "expert" and full.years == 2 and full.objectives == sim.objectives


def test_event_offered_measure_does_not_reset(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "hopital", seed=13)
    eid, choice = next(((e.id, c) for e in sim.events.events.values() for c in e.choix
                        if c.effets.get("mesure_offerte")), (None, None))
    if eid is None:
        pytest.skip("aucun événement n'offre de mesure")
    mid = choice.effets["mesure_offerte"]
    sim.portfolio.add(mid, 0, initial=True)
    sim.pending_events.append(eid)
    sim.budget.adjust_budget(100_000)
    sim.resolve_event(eid, choice.id)
    assert sim.portfolio.items[mid].initial and sim.portfolio.items[mid].is_active(sim.turn)


def test_budget_cut_never_negative(data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "pme_industrie", seed=14)
    sim.budget.spend(sim.budget.remaining - 500, "outils", "x", 1)
    applied = sim.budget.adjust_budget(-5000, "formation")
    assert applied == -500 and sim.budget.remaining >= -1e-6
    total = sum(c["alloue"] for c in sim.budget.categories.values())
    assert total == pytest.approx(sim.budget.budget_annuel_ssi)


# -- réseau local (intégration avec le jeu) ------------------------------------------------------------
def _wait(cond, timeout: float = 4.0) -> bool:  # type: ignore[no-untyped-def]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_net_session_sync_flow() -> None:
    from ui.net_session import NetSession
    host = NetSession.create_host("Formateur", "mairie", "standard", 1, "synchronise", port=0)
    try:
        client = NetSession.join("127.0.0.1", host.port, "Apprenant", host.pin)
        try:
            assert _wait(lambda: (host.poll(), len(host.players) == 2)[1])
            params = host.launch()
            assert _wait(lambda: (client.poll(), client.start is not None)[1])
            assert client.start.seed == params.seed and client.start.org_id == "mairie"
            host.ready(1)
            assert not host.may_advance(1)
            client.ready(1)
            assert _wait(lambda: (host.poll(), client.poll(), host.may_advance(1) and client.may_advance(1))[2])
            client.send_progress(2, 55.0, 70.0, 1, False)
            host.send_progress(2, 60.0, 72.0, 0, False)
            assert _wait(lambda: (client.poll(), any(p.score == 60.0 for p in client.players))[1])
            assert client.leaderboard()[0].name == "Formateur"
        finally:
            client.close()
        assert _wait(lambda: (host.poll(), any(not p.connected for p in host.players))[1])
        assert host.may_advance(1)
    finally:
        host.close()


def test_net_wrong_pin_rejected() -> None:
    from ui.net_session import NetSession, join_async
    host = NetSession.create_host("Formateur", "esn", "expert", 1, "libre", port=0)
    try:
        wrong = "0000" if host.pin != "0000" else "1111"
        task = join_async("127.0.0.1", host.port, "Intrus", wrong)
        assert _wait(lambda: task.done)
        assert task.error and task.result is None
    finally:
        host.close()


# -- interface ---------------------------------------------------------------------------------------------
@pytest.fixture
def app(tmp_path, data):  # type: ignore[no-untyped-def]
    from engine.game_loop import GameApp
    from engine.save_manager import SaveManager
    application = GameApp(size=(1280, 720), headless=True, seed=5, data=data, saves=SaveManager(tmp_path / "s.db"))
    yield application
    application.leave_network()
    pygame.quit()


def _frames(app, n: int = 3, events=None) -> None:  # type: ignore[no-untyped-def]
    for _ in range(n):
        app.step(1 / 60, list(events or []))


def test_new_screens_render(app) -> None:  # type: ignore[no-untyped-def]
    app.settings["difficulty"] = "decouverte"
    app.settings["years"] = 1
    app.start_game("hopital", 3)
    assert app.sim.difficulty.id == "decouverte" and app.sim.years == 1
    for t in range(40):
        app.sim.vulns.spawn(t, set())
    for v in app.sim.vulns.items:
        v.visible = True
    app.switch("OPERATIONS")
    _frames(app)
    app.screen.filter = "toutes"
    _frames(app)
    app.switch("DASHBOARD")
    app.screen.map_view = "matrice"
    _frames(app)
    app.screen.map_view = "3d"
    app.sim.pending_board = True
    _frames(app)
    assert app.dialogs.active
    app.dialogs.items[0].buttons[-1].action()
    app.dialogs.items.clear()
    assert not app.sim.pending_board
    app.screen._open_save()
    app.dialogs.items[0].buttons[1].action()
    assert app.saves.exists("slot2")
    app.dialogs.items.clear()
    app.switch("MENU")
    app.screen.mode = "load"
    _frames(app)
    for mode in ("choix", "heberger", "rejoindre"):
        app.switch("LOBBY")
        app.screen.mode = mode
        _frames(app)


def test_lobby_host_and_text_input(app) -> None:  # type: ignore[no-untyped-def]
    app.switch("LOBBY")
    lobby = app.screen
    lobby.mode = "heberger"
    _frames(app, 2)
    field = pygame.Rect(36 + 0, 0, 0, 0)
    app.ui.focus = "pseudo"
    _frames(app, 1, [pygame.event.Event(pygame.TEXTINPUT, text="Équipe1")])
    assert lobby.pseudo == "Équipe1"
    _frames(app, 1, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=0, unicode="")])
    assert lobby.pseudo == "Équipe"
    lobby.port = "0"
    lobby._create()
    assert app.net is not None and app.net.is_host and lobby.mode == "attente"
    _frames(app, 2)
    params = app.net.launch()
    app.start_game(params.org_id, params.seed, params.difficulty, params.years)
    assert app.screen_name == "DASHBOARD"
    app.screen.center_tab = "classement"
    _frames(app, 3)
    assert any(p.name == "Équipe" for p in app.net.players)
    app.autosave()
    assert app.saves.exists("reseau")
    _ = field


def test_finished_player_does_not_block_sync() -> None:
    from ui.net_session import NetSession
    host = NetSession.create_host("Formateur", "mairie", "standard", 1, "synchronise", port=0)
    try:
        client = NetSession.join("127.0.0.1", host.port, "Apprenant", host.pin)
        try:
            assert _wait(lambda: (host.poll(), len(host.players) == 2)[1])
            host.launch()
            client.ready(10_000)      # partie du participant terminée
            host.ready(5)
            assert _wait(lambda: (host.poll(), host.may_advance(5))[1])
        finally:
            client.close()
    finally:
        host.close()
