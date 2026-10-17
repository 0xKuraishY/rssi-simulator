"""Joueurs automatiques : mode --headless, tests d'intégration et calibrage des difficultés.

Trois profils :
- expert : analyse EBIOS RM, investissements au meilleur ROI, correctifs prioritaires, notifications à temps ;
- moyen  : bonnes intentions mais réactions irrégulières ;
- novice : décisions de crise inadaptées, vulnérabilités ignorées, aucune notification.
"""
from __future__ import annotations

import random
from typing import Callable

from game.risk_engine import Treatment
from game.simulation import GameRuleError, Simulation

STRATEGIES = ("expert", "moyen", "novice")
QUALITY_ORDER = {"expert": ["bonne", "moyenne", "mauvaise"], "novice": ["mauvaise", "moyenne", "bonne"]}


def _pick(choices, quality_order: list[str], rng: random.Random):  # type: ignore[no-untyped-def]
    for q in quality_order:
        options = [c for c in choices if c.qualite == q]
        if options:
            return rng.choice(options)
    return choices[0]


def _order(strategy: str, rng: random.Random) -> list[str]:
    return QUALITY_ORDER.get(strategy) or rng.sample(["bonne", "moyenne", "mauvaise"], 3)


def _notify_all(sim: Simulation) -> None:
    for d in list(sim.compliance.state.deadlines):
        if d.done_hour is None and d.status == "pending":
            sim.notify_obligation(d.incident_uid, d.kind)


def _ebios_step(sim: Simulation) -> None:
    """Un atelier EBIOS par semaine, si l'équipe en a la capacité."""
    r = sim.risk
    study = r.study
    n = next((i for i in range(1, 6) if not study.done[i - 1]), None)
    if n is None:
        return
    if n == 1:
        for a in sim.org.assets_critiques:
            r.classify_asset(a.id, a.criticite)
    elif n == 2 and not study.selected_pairs:
        for key in sorted(r.expected_pairs()) or [f"{sr.id}:{ov.id}" for sr, ov in r.all_pairs()[:1]]:
            sr, ov = key.split(":")
            r.toggle_pair(sr, ov)
    elif n == 3 and not study.strategic:
        for key in study.selected_pairs:
            ov = key.split(":")[1]
            path = next((p.id for p in r.ref.paths.values() if r.scenario_types(ov, p.id)), "CA1")
            r.add_strategic_scenario(key, path)
    elif n == 5:
        if not study.operational:
            r.generate_operational(sim.turn)
        for op in study.operational:
            r.set_treatment(op.id, Treatment.REDUIRE.value if op.score >= 4 else Treatment.ACCEPTER.value)
    try:
        sim.complete_workshop(n)
    except (GameRuleError, ValueError):
        pass


def _run_ebios(sim: Simulation) -> None:
    """Étude complète d'un coup (tests) : la capacité de l'équipe est réinitialisée entre ateliers."""
    for _ in range(5):
        sim.team.state.used = 0.0
        _ebios_step(sim)


def _buy_best_measures(sim: Simulation, max_share: float, min_roi: float = 0.5) -> None:
    cap = sim.team.capacity(sim.turn)
    candidates = []
    for mid in sim.data.measures:
        ok, _ = sim.measure_availability(mid)
        if ok:
            candidates.append((sim.measure_roi(mid)["roi"], mid))
    candidates.sort(reverse=True)
    floor = sim.budget.budget_annuel_ssi * (1 - max_share)
    for roi, mid in candidates:
        if roi < min_roi:
            break
        if sim.deployment_load() > 0.7 * cap:   # ne pas saturer l'équipe
            break
        cost, _ = sim.measure_costs(sim.data.measures[mid])
        if sim.budget.remaining - cost >= floor:
            try:
                sim.buy_measure(mid)
            except GameRuleError:
                continue


def _handle_vulns(sim: Simulation, strategy: str, rng: random.Random) -> None:
    for v in sim.vulns.open_items(visible_only=True):
        if v.status != "ouverte":
            continue
        d = sim.vulns.definition(v)
        if strategy == "expert":
            urgent = d.gravite == "critique" and d.exposition == "internet"
            actions = ["urgence", "contourner"] if urgent else ["planifier", "contourner"]
        elif strategy == "moyen":
            if rng.random() < 0.5:
                continue
            actions = ["planifier"]
        else:
            if rng.random() < 0.7:
                continue
            actions = ["accepter"]
        for action in actions:
            try:
                sim.vuln_action(v.uid, action)
                break
            except GameRuleError:
                continue


def _handle_board(sim: Simulation, strategy: str, rng: random.Random) -> None:
    if strategy == "expert":
        opts = {o["id"]: o for o in sim.board_options()}
        if opts["rallonge"]["probability"] >= 0.55:
            choice = "rallonge"
        elif sim.team.state.overload_weeks >= 3 and opts["recrutement"]["probability"] >= 0.35:
            choice = "recrutement"
        elif sim.turn >= sim.prep_until and opts["exercice"]["available"]:
            choice = "exercice"
        else:
            choice = "bilan"
    elif strategy == "moyen":
        choice = rng.choice(["rallonge", "bilan", "bilan", "recrutement"])
    else:
        choice = rng.choice(["rallonge", "recrutement"])
    try:
        sim.resolve_board(choice)
    except GameRuleError:
        sim.resolve_board("bilan")


def play(sim: Simulation, strategy: str = "expert", seed: int = 0,
         on_turn: Callable[[Simulation], None] | None = None) -> Simulation:
    rng = random.Random(seed)
    while not sim.finished:
        week = sim.calendar.week_of_year(sim.turn)
        if strategy == "expert":
            if sim.turn >= 2:
                _ebios_step(sim)
            if week in (2, 14, 27, 40):
                _buy_best_measures(sim, 0.92)
            for p in sim.compliance.applicable_permanent():
                if p.measure is None and p.key != "nis2_analyse_risques" and not sim.compliance.is_satisfied(
                        p.key, sim.turn, sim.active_measure_ids, sim.risk.study.completed_turn):
                    try:
                        sim.compliance_action(p.key)
                    except GameRuleError:
                        pass
            if week in (10, 36) and "M01" in sim.portfolio.items:
                try:
                    sim.run_phishing_campaign()
                except GameRuleError:
                    pass
            if sim.team.state.overload_weeks >= 3 and sim.turn >= sim.team.state.reinforcement_until:
                try:
                    sim.hire_reinforcement()
                except GameRuleError:
                    pass
        elif strategy == "moyen":
            if sim.turn >= 8 and rng.random() < 0.3:
                _ebios_step(sim)
            if week == 2:
                _buy_best_measures(sim, 0.5, min_roi=2.0)
        _handle_vulns(sim, strategy, rng)
        for inc in sim.active_crises():
            while (d := sim.incidents.pending_decision(inc)) is not None:
                sim.crisis_decide(inc.uid, d.id, _pick(d.choix, _order(strategy, rng), rng).id)
                if strategy == "expert" or (strategy == "moyen" and rng.random() < 0.5):
                    _notify_all(sim)
            sim.crisis_close(inc.uid)
        if strategy == "expert":
            _notify_all(sim)
        for eid in list(sim.pending_events):
            ev = sim.data.events[eid]
            choices = [c for c in ev.choix if sim.event_choice_available(eid, c.id)[0]] or ev.choix
            try:
                sim.resolve_event(eid, _pick(choices, _order(strategy, rng), rng).id)
            except GameRuleError:
                sim.pending_events.remove(eid)
        if sim.pending_board:
            _handle_board(sim, strategy, rng)
        if on_turn:
            on_turn(sim)
        sim.next_turn()
    return sim


__all__ = ["play", "STRATEGIES"]
