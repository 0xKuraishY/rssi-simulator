"""Budget : enveloppes, dépassement, ROI, coûts d'incident, assurance, amendes."""
from __future__ import annotations

import pytest

import config
from game.budget_engine import (
    INSURANCE_COVER,
    INSURANCE_DEDUCTIBLE,
    INSURANCE_RATE_MAX,
    INSURANCE_RATE_MIN,
    BudgetEngine,
    BudgetExceededError,
    insurance_rate,
    roi,
)
from game.simulation import GameRuleError


@pytest.fixture
def budget(org):  # type: ignore[no-untyped-def]
    return BudgetEngine(org)


def test_six_categories_sum_to_budget(budget, org) -> None:  # type: ignore[no-untyped-def]
    assert set(budget.categories) == set(config.BUDGET_CATEGORIES)
    assert sum(c["alloue"] for c in budget.categories.values()) == pytest.approx(org.budget_ssi)
    assert budget.remaining == org.budget_ssi


def test_spend_and_overspend(budget) -> None:  # type: ignore[no-untyped-def]
    budget.spend(10_000, "outils", "EDR", 1)
    assert budget.spent == 10_000
    with pytest.raises(BudgetExceededError):
        budget.spend(budget.remaining + 1, "outils", "trop", 1)
    with pytest.raises(KeyError):
        budget.spend(1, "voyages", "x", 1)
    with pytest.raises(ValueError):
        budget.spend(-5, "outils", "x", 1)


def test_category_strict_and_auto_reallocation(budget) -> None:  # type: ignore[no-untyped-def]
    cap = budget.category_remaining("divers")
    assert not budget.can_afford(cap + 100, "divers", auto_realloc=False)
    with pytest.raises(BudgetExceededError):
        budget.spend(cap + 100, "divers", "x", 1, auto_realloc=False)
    budget.spend(cap + 100, "divers", "x", 1)
    assert budget.categories["divers"]["depense"] == cap + 100
    assert sum(c["alloue"] for c in budget.categories.values()) == pytest.approx(budget.budget_annuel_ssi)


def test_reallocate(budget) -> None:  # type: ignore[no-untyped-def]
    a = budget.categories["outils"]["alloue"]
    budget.reallocate("outils", "formation", 1000)
    assert budget.categories["outils"]["alloue"] == a - 1000
    with pytest.raises(ValueError):
        budget.reallocate("outils", "formation", 0)
    with pytest.raises(BudgetExceededError):
        budget.reallocate("outils", "formation", 10**9)


def test_roi_formula() -> None:
    # ROI = (freq × coût moyen × coeff) / coût mesure
    assert roi(0.3, 1_000_000, 0.5, 50_000) == pytest.approx(3.0)
    assert roi(0.1, 100_000, 0.2, 10_000) == pytest.approx(0.2)
    assert roi(0.1, 100_000, 0.2, 0) == float("inf")
    assert roi(0.0, 100_000, 0.2, 0) == 0.0


def test_measure_roi_detail(budget, data) -> None:  # type: ignore[no-untyped-def]
    m = data.measures["M16"]
    res = budget.measure_roi(m, 30_000, 10_000, {"ransomware": 0.3, "phishing": 0.2},
                             {"ransomware": 1_000_000, "phishing": 100_000})
    assert res["cout_annuel"] == pytest.approx(30_000 / 3 + 10_000)
    assert res["cout_evite"] == pytest.approx(0.3 * 1_000_000 * 0.6)
    assert res["roi"] == pytest.approx(res["cout_evite"] / res["cout_annuel"])
    assert res["rentable"] is True
    assert budget.roi_mesures["M16"] == res["roi"]


def test_incident_cost_and_insurance(budget, org) -> None:  # type: ignore[no-untyped-def]
    r = budget.record_incident_cost(100_000, 3)
    assert r == {"brut": 100_000, "rembourse": 0.0, "net": 100_000}
    r = budget.record_incident_cost(100_000, 4, insured=True)
    assert r["rembourse"] == pytest.approx((100_000 - INSURANCE_DEDUCTIBLE) * INSURANCE_COVER)
    r = budget.record_incident_cost(100_000, 4, insured=True, cover_condition_met=False)
    assert r["rembourse"] == 0
    big = budget.record_incident_cost(50_000_000, 5, insured=True)
    assert big["rembourse"] == org.plafond_assurance
    assert budget.cout_incident_cumule > 0
    assert budget.remaining == org.budget_ssi  # hors budget SSI


def test_fines_accumulate(budget) -> None:  # type: ignore[no-untyped-def]
    budget.record_fine(15_000, 3, "CNIL")
    budget.record_fine(20_000, 4, "ANSSI")
    assert budget.amendes_cumulees == 35_000


def test_insurance_rate_bounds() -> None:
    assert insurance_rate(1.0, True) == pytest.approx(INSURANCE_RATE_MIN)
    assert insurance_rate(0.0, True) == pytest.approx(INSURANCE_RATE_MAX)
    assert insurance_rate(1.0, False) == pytest.approx(INSURANCE_RATE_MAX)


def test_new_year_maintenance_and_unfunded(budget) -> None:  # type: ignore[no-untyped-def]
    budget.spend(5_000, "outils", "x", 10)
    unfunded = budget.new_year(50_000, [("M01", "A", 20_000, "formation"), ("M02", "B", 40_000, "outils"),
                                        ("M03", "C", 0, "divers")], 53)
    assert budget.year == 2
    assert budget.budget_annuel_ssi == 50_000
    assert budget.spent == 20_000
    assert unfunded == ["M02"]
    assert budget.yearly[0]["depense"] == 5_000


def test_weekly_history(budget) -> None:  # type: ignore[no-untyped-def]
    budget.spend(1_000, "outils", "a", 3)
    budget.spend(2_000, "outils", "b", 3)
    hist = dict(budget.weekly_spending(12, 12))
    assert len(hist) == 12 and hist[3] == 3_000


def test_serialization(budget, org) -> None:  # type: ignore[no-untyped-def]
    budget.spend(1_000, "audit", "x", 2)
    budget.record_fine(10, 2, "x")
    other = BudgetEngine(org)
    other.load_dict(budget.to_dict())
    assert other.spent == 1_000 and other.amendes_cumulees == 10


# -- intégration simulation -----------------------------------------------------------
def test_cannot_buy_beyond_budget(data) -> None:  # type: ignore[no-untyped-def]
    from game.simulation import Simulation
    sim = Simulation(data, "pme_industrie", seed=1)
    ok, reason = sim.measure_availability("M29")  # SOC 50 k€ > budget PME 19,2 k€
    assert not ok and "Budget" in reason
    with pytest.raises(GameRuleError):
        sim.buy_measure("M29")
    with pytest.raises(GameRuleError):
        sim.buy_measure("M99")


def test_buy_measure_and_prerequisites(sim) -> None:  # type: ignore[no-untyped-def]
    ok, reason = sim.measure_availability("M11")
    assert not ok and "Prérequis" in reason
    sim.buy_measure("M10")
    assert sim.portfolio.has("M10")
    ok, reason = sim.measure_availability("M10")
    assert not ok and "Déploiement" in reason
    assert sim.measure_availability("M11")[0]
    ok, _ = sim.measure_availability("M07")  # socle initial
    assert not ok


def test_insurance_premium_depends_on_prerequisites(sim) -> None:  # type: ignore[no-untyped-def]
    p0 = sim.insurance_premium()
    assert p0 == pytest.approx(round(sim.org.plafond_assurance * INSURANCE_RATE_MAX, -2))
    for mid in ("M10", "M16"):
        sim.portfolio.add(mid, 0, initial=True)
    assert sim.insurance_premium() < p0
    deploy, annual = sim.measure_costs(sim.data.measures["M37"])
    assert deploy == annual == sim.insurance_premium()


def test_measure_cost_bounds(data) -> None:  # type: ignore[no-untyped-def]
    small, big = data.organisations["pme_industrie"], data.organisations["telecom"]
    pentest = data.measures["M25"]
    assert 8_000 <= pentest.deployment_cost(small) <= 25_000
    assert pentest.deployment_cost(big) == 25_000
    siem = data.measures["M28"]
    assert siem.annual_cost(small) == 30_000 < siem.annual_cost(big) <= 80_000
    edu = data.measures["M01"]
    assert edu.deployment_cost(small) == 45 * small.taille_employes


def test_measure_roi_through_simulation(sim) -> None:  # type: ignore[no-untyped-def]
    res = sim.measure_roi("M16")
    assert res["roi"] > 0
    assert set(res["risk_before"]) == set(res["risk_after"])
