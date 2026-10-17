"""Incidents : chargement, génération, timeline en 7 phases, décisions."""
from __future__ import annotations

import random
from pathlib import Path

import pytest
import yaml

import config
from game.incident_engine import (
    GRACE_TURNS,
    IncidentEngine,
    IncidentError,
    IncidentTemplate,
    Phase,
    load_incident_templates,
)
from game.organisation import INCIDENT_TYPES


@pytest.fixture
def engine(data, org):  # type: ignore[no-untyped-def]
    return IncidentEngine(org, data.incidents, random.Random(1))


def test_ten_scenarios_loaded(data) -> None:  # type: ignore[no-untyped-def]
    ids = sorted(data.incidents)
    assert ids == [f"INC-{i:03d}" for i in range(1, 11)]
    assert {t.type for t in data.incidents.values()} == set(INCIDENT_TYPES)


def test_templates_are_complete(data) -> None:  # type: ignore[no-untyped-def]
    for t in data.incidents.values():
        assert 3 <= len(t.decisions) <= 5
        assert t.cout_min <= t.cout_max
        assert set(t.impact) == {"D", "I", "C", "T"}
        assert all(1 <= v <= 4 for v in t.impact.values())
        assert t.attack_chain
        assert [d.heure for d in t.decisions] == sorted(d.heure for d in t.decisions)
        for d in t.decisions:
            assert sum(1 for c in d.choix if c.qualite == "bonne") >= 1
            assert d.default_choice in d.choix


def test_specified_costs_and_cves(data) -> None:  # type: ignore[no-untyped-def]
    inc1 = data.incidents["INC-001"]
    assert (inc1.cout_min, inc1.cout_max) == (150_000, 3_500_000)
    assert "CVE-2017-0144" in {c["id"] for c in inc1.cve_references}
    assert (data.incidents["INC-002"].cout_min, data.incidents["INC-002"].cout_max) == (50_000, 800_000)
    assert "CVE-2024-21887" in {c["id"] for c in data.incidents["INC-005"].cve_references}
    assert data.incidents["INC-004"].duree_semaines == {"min": 8, "max": 24}
    assert set(data.incidents["INC-010"].organisations) == {"pme_industrie", "telecom"}


def test_mitre_techniques_known(data) -> None:  # type: ignore[no-untyped-def]
    for t in data.incidents.values():
        for tid in t.attack_chain:
            assert tid in data.mitre, f"{t.id} : {tid} absent de mitre_attack.json"


def test_ot_incident_filtered_for_hospital(engine) -> None:  # type: ignore[no-untyped-def]
    assert "INC-010" not in engine.templates
    with pytest.raises(IncidentError):
        engine.start("INC-010", 5)


def test_start_and_detection_timeline(engine) -> None:  # type: ignore[no-untyped-def]
    inc = engine.start("INC-007", 10)  # initié : détection tardive
    t = engine.template(inc)
    lo, hi = t.phase_detection_semaines["min"], t.phase_detection_semaines["max"]
    assert lo <= inc.detection_turn - inc.start_turn <= hi
    assert inc.phase == Phase.COMPROMISSION and not inc.detected
    assert t.cout_min <= inc.base_cost <= t.cout_max
    if inc.detection_turn > 11:
        engine.advance(11)
        assert inc.phase == Phase.LATENCE
    result = engine.advance(inc.detection_turn)
    assert inc in result["detected"]
    assert inc.phase == Phase.DETECTION and inc.in_crisis


def test_detection_factor_shortens_delay(data, org) -> None:  # type: ignore[no-untyped-def]
    slow = IncidentEngine(org, data.incidents, random.Random(3)).start("INC-007", 1, detection_factor=1.0)
    fast = IncidentEngine(org, data.incidents, random.Random(3)).start("INC-007", 1, detection_factor=0.1)
    assert fast.detection_turn - fast.start_turn <= slow.detection_turn - slow.start_turn


def test_decisions_flow_and_effects(engine) -> None:  # type: ignore[no-untyped-def]
    inc = engine.start("INC-001", 5)
    engine.advance(inc.detection_turn)
    first = engine.pending_decision(inc)
    with pytest.raises(IncidentError):
        engine.decide(inc, "MAUVAIS_ID", first.choix[0].id)
    with pytest.raises(IncidentError):
        engine.decide(inc, first.id, "Z")
    bad = next(c for c in first.choix if c.qualite == "mauvaise")
    engine.decide(inc, first.id, bad.id)
    assert inc.cost_mult == pytest.approx(float(bad.effets.get("cout_mult", 1.0)))
    assert inc.crisis_hour == first.heure
    assert inc.phase >= Phase.CONFINEMENT
    with pytest.raises(IncidentError):
        engine.end_crisis(inc, 6)
    while (d := engine.pending_decision(inc)) is not None:
        engine.decide(inc, d.id, d.choix[0].id)
    assert 0 <= engine.decision_quality(inc) < 1
    cost = engine.end_crisis(inc, inc.detection_turn)
    assert cost > 0 and inc.final_cost == cost
    assert inc.phase == Phase.REPRISE and not inc.in_crisis
    with pytest.raises(IncidentError):
        engine.decide(inc, "D1", "A")
    res = engine.advance(inc.recovery_end_turn)
    assert inc in res["closed"] and inc.closed
    assert engine.closed_incidents() == [inc]


def test_declenche_adds_obligation(data, org) -> None:  # type: ignore[no-untyped-def]
    eng = IncidentEngine(org, data.incidents, random.Random(2))
    tid, dec_id, choice = next(
        (t.id, d.id, c) for t in eng.templates.values() for d in t.decisions for c in d.choix
        if c.effets.get("declenche"))
    inc = eng.start(tid, 4)
    eng.advance(inc.detection_turn)
    while (d := eng.pending_decision(inc)) is not None and d.id != dec_id:
        eng.decide(inc, d.id, d.choix[0].id)
    eng.decide(inc, dec_id, choice.id)
    assert set(choice.effets["declenche"]) <= set(inc.triggered)


def test_cost_increases_with_late_detection(engine) -> None:  # type: ignore[no-untyped-def]
    inc = engine.start("INC-002", 5)
    inc.detection_turn = inc.start_turn
    c0 = engine.compute_final_cost(inc)
    inc.detection_turn = inc.start_turn + 20
    assert engine.compute_final_cost(inc) > c0
    inc.impact_reduction = 0.6
    assert engine.compute_final_cost(inc) < c0 * 1.5


def test_roll_respects_grace_and_limits(engine) -> None:  # type: ignore[no-untyped-def]
    certain = {t: 1.0 for t in INCIDENT_TYPES}
    assert engine.roll(GRACE_TURNS, certain) is None
    assert engine.roll(10, certain) is not None
    assert engine.roll(10, {t: 0.0 for t in INCIDENT_TYPES}) is None
    engine.start("INC-001", 10)
    engine.start("INC-002", 10)
    assert engine.roll(11, certain) is None  # 2 incidents ouverts maximum


def test_serialization_roundtrip(engine, data, org) -> None:  # type: ignore[no-untyped-def]
    inc = engine.start("INC-003", 7)
    other = IncidentEngine(org, data.incidents, random.Random(9))
    other.load_dict(engine.to_dict())
    assert other.get(inc.uid).detection_turn == inc.detection_turn
    with pytest.raises(IncidentError):
        other.get("INC-999#1")


def test_invalid_templates_rejected(tmp_path: Path, data) -> None:  # type: ignore[no-untyped-def]
    raw = yaml.safe_load((config.INCIDENTS_DIR / "inc_001_ransomware_smb.yaml").read_text(encoding="utf-8"))
    for mutate, msg in [
        (lambda d: d.pop("impact"), "impact"),
        (lambda d: d.update(type="inconnu"), "type"),
        (lambda d: d.update(cout_min=10, cout_max=1), "cout"),
        (lambda d: d.update(decisions=d["decisions"][:2]), "décisions"),
        (lambda d: d["decisions"][0]["choix"][0].update(qualite="excellente"), "qualité"),
    ]:
        broken = yaml.safe_load(yaml.safe_dump(raw))
        mutate(broken)
        with pytest.raises(IncidentError):
            IncidentTemplate.from_dict(broken)
    (tmp_path / "a.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert list(load_incident_templates(tmp_path)) == ["INC-001"]
