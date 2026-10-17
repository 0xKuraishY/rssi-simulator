"""EBIOS RM : formules, matrice 4×4, réductions, ateliers 1 à 5."""
from __future__ import annotations

import pytest

from game.measures import MeasurePortfolio, combine_reductions
from game.risk_engine import (
    REFUSAL_FACTOR,
    EbiosStudy,
    RiskEngine,
    Treatment,
    clamp_scale,
    likelihood_from_probability,
    operational_likelihood,
    risk_category,
    risk_score,
    severity_from_dict,
)


@pytest.fixture
def engine(data, org):  # type: ignore[no-untyped-def]
    portfolio = MeasurePortfolio(data.measures)
    impacts = {t.type: t.impact for t in data.incidents.values()}
    chains = {t.type: t.attack_chain for t in data.incidents.values()}
    return RiskEngine(org, data.referential, portfolio, impacts, chains)


# -- formules pures ------------------------------------------------------------
@pytest.mark.parametrize("v,g,expected", [(1, 1, 1), (2, 3, 6), (4, 4, 16), (3, 4, 12)])
def test_risk_score_is_product(v: int, g: int, expected: int) -> None:
    assert risk_score(v, g) == expected


@pytest.mark.parametrize("v,g", [(0, 2), (5, 1), (2, 0), (1, 5)])
def test_risk_score_rejects_out_of_scale(v: int, g: int) -> None:
    with pytest.raises(ValueError):
        risk_score(v, g)


@pytest.mark.parametrize("score,cat", [(1, "faible"), (3, "faible"), (4, "modere"), (6, "modere"),
                                       (8, "eleve"), (9, "eleve"), (12, "critique"), (16, "critique")])
def test_risk_category_thresholds(score: int, cat: str) -> None:
    assert risk_category(score) == cat


def test_matrix_4x4_covers_all_categories() -> None:
    cats = {risk_category(risk_score(v, g)) for v in range(1, 5) for g in range(1, 5)}
    assert cats == {"faible", "modere", "eleve", "critique"}


def test_severity_is_worst_dict_criterion() -> None:
    assert severity_from_dict({"D": 4, "I": 1, "C": 2, "T": 1}) == 4
    assert severity_from_dict({"D": 1, "I": 1, "C": 3, "T": 2}) == 3
    assert severity_from_dict({}) == 1


@pytest.mark.parametrize("p,v", [(0.0, 1), (0.04, 1), (0.05, 2), (0.15, 3), (0.29, 3), (0.30, 4), (0.9, 4)])
def test_likelihood_from_probability(p: float, v: int) -> None:
    assert likelihood_from_probability(p) == v


def test_clamp_scale() -> None:
    assert clamp_scale(-3) == 1
    assert clamp_scale(9) == 4
    assert clamp_scale(2.4) == 2


def test_operational_likelihood_reduced_by_measures() -> None:
    assert operational_likelihood(4, 0.0) == 4
    assert operational_likelihood(4, 0.5) == 2
    assert operational_likelihood(1, 0.9) == 1


def test_combine_reductions_multiplicative_and_capped() -> None:
    assert combine_reductions([]) == 0.0
    assert combine_reductions([0.5, 0.5]) == pytest.approx(0.75)
    assert combine_reductions([0.99, 0.99, 0.99]) == pytest.approx(0.9)


# -- réductions sur le moteur --------------------------------------------------
def test_measures_reduce_probability(engine) -> None:  # type: ignore[no-untyped-def]
    before = engine.annual_probability("ransomware", 10)
    engine.portfolio.add("M06", 1)
    engine.portfolio.add("M08", 1)
    after = engine.annual_probability("ransomware", 10)
    assert after < before
    expected_red = combine_reductions([0.45, 0.35])
    assert engine.reduction("ransomware", 10) == pytest.approx(expected_red)


def test_measure_inactive_until_ready(engine) -> None:  # type: ignore[no-untyped-def]
    engine.portfolio.add("M06", 5)  # délai 6 semaines
    assert engine.reduction("ransomware", 6) == 0
    assert engine.reduction("ransomware", 11) > 0


def test_impact_reduction_lowers_residual_severity(engine) -> None:  # type: ignore[no-untyped-def]
    g0 = engine.residual_severity("ransomware", 10)
    engine.portfolio.add("M16", 0, initial=True)
    engine.portfolio.add("M17", 0, initial=True)
    assert engine.residual_severity("ransomware", 10) < g0


def test_hygiene_factor_bounds(engine) -> None:  # type: ignore[no-untyped-def]
    f = engine.hygiene_factor(1)
    assert 0.8 <= f <= 1.2
    assert 39 in engine.hygiene_in_place(1)  # le RSSI est désigné


def test_detection_factor(engine) -> None:  # type: ignore[no-untyped-def]
    assert engine.detection_factor(1) == 1.0
    engine.portfolio.add("M29", 0, initial=True)
    assert engine.detection_factor(1) == pytest.approx(0.35)


def test_modifiers_apply_and_expire(engine) -> None:  # type: ignore[no-untyped-def]
    base = engine.annual_probability("vpn_exploit", 5)
    engine.add_modifier("vpn_exploit", 2.0, until_turn=8)
    assert engine.annual_probability("vpn_exploit", 5) == pytest.approx(min(0.95, base * 2))
    engine.purge_modifiers(9)
    assert engine.annual_probability("vpn_exploit", 9) == pytest.approx(base)


def test_non_applicable_type_has_zero_probability(engine) -> None:  # type: ignore[no-untyped-def]
    assert engine.annual_probability("ot_iot", 1) == 0.0
    assert "ot_iot" not in engine.applicable_types()


def test_global_risk(engine) -> None:  # type: ignore[no-untyped-def]
    level, cat = engine.global_risk(1)
    assert 1 <= level <= 16
    assert cat == risk_category(level)
    assert engine.average_risk(1) <= level


def test_weekly_probability_consistent(engine) -> None:  # type: ignore[no-untyped-def]
    p = engine.annual_probability("ransomware", 1)
    w = engine.weekly_probability("ransomware", 1)
    assert 1 - (1 - w) ** 52 == pytest.approx(p)


# -- ateliers -------------------------------------------------------------------
def _complete_study(engine, treatment: str = Treatment.REDUIRE.value) -> None:  # type: ignore[no-untyped-def]
    for a in engine.org.assets_critiques:
        engine.classify_asset(a.id, a.criticite)
    engine.complete_workshop1()
    for key in sorted(engine.expected_pairs()):
        sr, ov = key.split(":")
        engine.toggle_pair(sr, ov)
    engine.complete_workshop2()
    engine.add_strategic_scenario(engine.study.selected_pairs[0], "CA2")
    engine.complete_workshop3()
    engine.complete_workshop4(1)
    for op in engine.study.operational:
        engine.set_treatment(op.id, treatment)
    engine.complete_workshop5(1, has_insurance=False)


def test_workshops_are_sequential(engine) -> None:  # type: ignore[no-untyped-def]
    assert engine.study.unlocked(1)
    assert not engine.study.unlocked(2)
    with pytest.raises(ValueError):
        engine.complete_workshop2()


def test_workshop1_requires_all_assets(engine) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        engine.complete_workshop1()
    with pytest.raises(ValueError):
        engine.classify_asset(engine.org.assets_critiques[0].id, "tertiaire")
    with pytest.raises(KeyError):
        engine.classify_asset("inconnu", "primaire")


def test_workshop1_score(engine) -> None:  # type: ignore[no-untyped-def]
    assets = engine.org.assets_critiques
    for a in assets:
        engine.classify_asset(a.id, "primaire")
    expected = sum(1 for a in assets if a.criticite == "primaire") / len(assets)
    assert engine.workshop1_score() == pytest.approx(expected)


def test_hygiene_priorities_capped_at_10(engine) -> None:  # type: ignore[no-untyped-def]
    for i in range(1, 15):
        engine.toggle_hygiene_priority(i)
    assert len(engine.study.hygiene_priorities) == 10
    engine.toggle_hygiene_priority(1)
    assert 1 not in engine.study.hygiene_priorities
    assert engine.hygiene_gaps(1)


def test_workshop2_f_measure(engine) -> None:  # type: ignore[no-untyped-def]
    expected = engine.expected_pairs()
    assert expected
    for key in expected:
        sr, ov = key.split(":")
        engine.toggle_pair(sr, ov)
    assert engine.workshop2_score() == pytest.approx(1.0)
    with pytest.raises(ValueError):
        engine.toggle_pair("SR1", "OV7")  # OV non associé à SR1
    sr, ov = next(iter(expected)).split(":")
    assert engine.toggle_pair(sr, ov) is False


def test_twelve_risk_sources(engine) -> None:  # type: ignore[no-untyped-def]
    assert len(engine.ref.sources) == 12
    assert {s.id for s in engine.ref.sources.values()} == {f"SR{i}" for i in range(1, 13)}


def test_strategic_scenario_computed_and_adjustable(engine) -> None:  # type: ignore[no-untyped-def]
    engine.toggle_pair("SR2", "OV1")
    with pytest.raises(ValueError):
        engine.add_strategic_scenario("SR1:OV2", "CA1")
    s = engine.add_strategic_scenario("SR2:OV1", "CA1")
    assert s.likelihood == s.likelihood_calc
    assert set(s.incident_types) <= set(engine.applicable_types())
    engine.adjust_strategic(s.id, 1, 1)
    assert s.deviation > 1
    assert engine.workshop3_score() < 1
    with pytest.raises(KeyError):
        engine.adjust_strategic("SS99", 1, 1)
    engine.remove_strategic_scenario(s.id)
    assert not engine.study.strategic


def test_operational_scenarios_map_mitre(engine) -> None:  # type: ignore[no-untyped-def]
    engine.toggle_pair("SR2", "OV1")
    engine.add_strategic_scenario("SR2:OV1", "CA2")
    ops = engine.generate_operational(1)
    assert ops
    for op in ops:
        assert op.techniques, "chaque scénario opérationnel est relié à MITRE ATT&CK"
        assert 1 <= op.likelihood <= op.likelihood_base
        assert op.score == op.likelihood * op.severity


def test_treatment_before_after(engine, data) -> None:  # type: ignore[no-untyped-def]
    engine.toggle_pair("SR2", "OV1")
    engine.add_strategic_scenario("SR2:OV1", "CA2")
    engine.generate_operational(1)
    res = engine.simulate_treatment(1, [data.measures["M06"], data.measures["M10"], data.measures["M16"]])
    assert res["after_avg"] <= res["before_avg"]
    assert res["after_max"] <= res["before_max"]


def test_full_study_and_refusal_factor(engine) -> None:  # type: ignore[no-untyped-def]
    _complete_study(engine, Treatment.REFUSER.value)
    assert engine.study.complete
    assert 41 in engine.hygiene_in_place(1)
    refused_type = engine.study.operational[0].incident_type
    assert engine.treatment_factor(refused_type) == REFUSAL_FACTOR
    assert 0 <= engine.study_quality() <= 1


def test_workshop5_requires_all_treatments_and_scores(engine) -> None:  # type: ignore[no-untyped-def]
    for a in engine.org.assets_critiques:
        engine.classify_asset(a.id, a.criticite)
    engine.complete_workshop1()
    engine.toggle_pair("SR2", "OV1")
    engine.complete_workshop2()
    engine.add_strategic_scenario("SR2:OV1", "CA2")
    engine.complete_workshop3()
    engine.complete_workshop4(1)
    with pytest.raises(ValueError):
        engine.complete_workshop5(1, False)
    with pytest.raises(ValueError):
        engine.set_treatment(engine.study.operational[0].id, "ignorer")
    with pytest.raises(KeyError):
        engine.set_treatment("inconnu", Treatment.ACCEPTER.value)
    for op in engine.study.operational:
        engine.set_treatment(op.id, Treatment.ACCEPTER.value)
    high = [o for o in engine.study.operational if o.score >= 8]
    score = engine.workshop5_score(False)
    if high:
        assert score < 1
        assert engine.accepted_high_risk_types()
    for op in engine.study.operational:
        engine.set_treatment(op.id, Treatment.TRANSFERER.value)
    assert engine.workshop5_score(True) == pytest.approx(1.0)


def test_study_serialization_roundtrip(engine) -> None:  # type: ignore[no-untyped-def]
    _complete_study(engine)
    engine.add_modifier("ddos", 1.5, 20)
    data = engine.to_dict()
    engine.reset_study()
    assert not engine.study.complete
    engine.load_dict(data)
    assert engine.study.complete
    assert isinstance(EbiosStudy.from_dict(data["study"]).strategic[0].score, int)
    assert engine.modifiers
