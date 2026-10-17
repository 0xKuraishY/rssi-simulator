"""Moteur budgétaire SSI : enveloppe annuelle, 6 postes, coûts d'incident, amendes, ROI.

Formule ROI (affichée au joueur) :
    ROI = Σ_types (fréquence annuelle × coût moyen d'incident × coefficient de réduction) / coût annuel de la mesure
    ROI > 1 → la mesure est rentable (coût évité supérieur à son coût).

Le coût annuel d'une mesure = coût de déploiement amorti sur 3 ans + maintenance annuelle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import config

if TYPE_CHECKING:
    from game.measures import Measure
    from game.organisation import Organisation

AMORTIZATION_YEARS = 3
DEFAULT_SPLIT = {
    "outils": 0.35, "formation": 0.15, "audit": 0.15,
    "assurance": 0.10, "externalisation": 0.20, "divers": 0.05,
}
# Assurance cyber : taux appliqué au plafond de garantie (cf. docs/METHODOLOGIE.md)
INSURANCE_RATE_MAX = 0.015
INSURANCE_RATE_MIN = 0.003
INSURANCE_COVER = 0.70
INSURANCE_DEDUCTIBLE = 10_000
INSURANCE_PREREQUISITES = ("M10", "M16")  # MFA + sauvegardes hors ligne


class BudgetExceededError(Exception):
    pass


@dataclass
class Expense:
    turn: int
    category: str
    label: str
    amount: float

    def to_dict(self) -> dict[str, Any]:
        return vars(self).copy()


def roi(freq: float, cout_moyen_incident: float, coeff_reduction: float, cout_mesure: float) -> float:
    """ROI = (freq_incident × cout_moyen_incident × coeff_reduction) / cout_mesure."""
    if cout_mesure <= 0:
        return float("inf") if freq * cout_moyen_incident * coeff_reduction > 0 else 0.0
    return freq * cout_moyen_incident * coeff_reduction / cout_mesure


def insurance_rate(maturity: float, prerequisites_met: bool) -> float:
    """Taux de prime selon le profil de risque : 0,3 % (mature) à 1,5 % (exposé)."""
    rate = INSURANCE_RATE_MAX - (INSURANCE_RATE_MAX - INSURANCE_RATE_MIN) * max(0.0, min(1.0, maturity))
    return rate if prerequisites_met else INSURANCE_RATE_MAX


class BudgetEngine:
    def __init__(self, org: "Organisation", budget_annuel_ssi: float | None = None) -> None:
        self.org = org
        self.budget_annuel_ssi: float = float(budget_annuel_ssi or org.budget_ssi)
        self.year = 1
        split = org.repartition_budget or DEFAULT_SPLIT
        total = sum(split.values()) or 1.0
        self.categories: dict[str, dict[str, float]] = {
            c: {"alloue": float(round(self.budget_annuel_ssi * split.get(c, 0) / total)), "depense": 0.0}
            for c in config.BUDGET_CATEGORIES
        }
        self._fix_rounding()
        self.cout_incident_cumule = 0.0
        self.amendes_cumulees = 0.0
        self.remboursements_assurance = 0.0
        self.roi_mesures: dict[str, float] = {}
        self.history: list[Expense] = []
        self.yearly: list[dict[str, float]] = []

    # -- enveloppes --------------------------------------------------------------
    def _fix_rounding(self) -> None:
        diff = self.budget_annuel_ssi - sum(c["alloue"] for c in self.categories.values())
        self.categories["divers"]["alloue"] += diff

    @property
    def spent(self) -> float:
        return sum(c["depense"] for c in self.categories.values())

    @property
    def remaining(self) -> float:
        return self.budget_annuel_ssi - self.spent

    def category_remaining(self, category: str) -> float:
        c = self.categories[category]
        return c["alloue"] - c["depense"]

    def can_afford(self, amount: float, category: str | None = None, auto_realloc: bool = True) -> bool:
        if amount > self.remaining + 1e-6:
            return False
        if category is None or auto_realloc:
            return True
        return amount <= self.category_remaining(category) + 1e-6

    def reallocate(self, source: str, target: str, amount: float) -> None:
        if amount <= 0:
            raise ValueError("Montant de réallocation invalide")
        if amount > self.category_remaining(source) + 1e-6:
            raise BudgetExceededError(f"Le poste « {source} » ne dispose pas de {amount:.0f} €")
        self.categories[source]["alloue"] -= amount
        self.categories[target]["alloue"] += amount

    def _auto_reallocate(self, category: str, needed: float) -> None:
        missing = needed - self.category_remaining(category)
        for src in sorted(self.categories, key=self.category_remaining, reverse=True):
            if missing <= 1e-6:
                break
            if src == category:
                continue
            take = min(missing, max(0.0, self.category_remaining(src)))
            if take > 0:
                self.reallocate(src, category, take)
                missing -= take

    def spend(self, amount: float, category: str, label: str, turn: int, auto_realloc: bool = True) -> Expense:
        if category not in self.categories:
            raise KeyError(f"Poste budgétaire inconnu : {category}")
        if amount < 0:
            raise ValueError("Montant négatif")
        if amount > self.remaining + 1e-6:
            raise BudgetExceededError(
                f"Budget SSI insuffisant : {amount:,.0f} € demandés, {self.remaining:,.0f} € disponibles"
            )
        if amount > self.category_remaining(category) + 1e-6:
            if not auto_realloc:
                raise BudgetExceededError(f"Enveloppe « {category} » insuffisante")
            self._auto_reallocate(category, amount)
        self.categories[category]["depense"] += amount
        expense = Expense(turn, category, label, float(amount))
        self.history.append(expense)
        return expense

    def adjust_budget(self, delta: float, category: str = "divers") -> float:
        """Rallonge (delta > 0) ou coupe (delta < 0) en cours d'exercice.

        Une coupe ne peut porter que sur les crédits non encore dépensés : elle est
        prélevée d'abord sur ``category`` puis sur les autres postes. Renvoie le
        montant réellement appliqué."""
        if delta >= 0:
            self.budget_annuel_ssi += delta
            self.categories[category]["alloue"] += delta
            return delta
        cut = min(-delta, max(0.0, self.remaining))
        left = cut
        order = [category] + sorted((c for c in self.categories if c != category),
                                    key=self.category_remaining, reverse=True)
        for c in order:
            take = min(left, max(0.0, self.category_remaining(c)))
            self.categories[c]["alloue"] -= take
            left -= take
            if left <= 1e-6:
                break
        self.budget_annuel_ssi -= cut
        return -cut

    # -- coûts subis ---------------------------------------------------------------
    def record_incident_cost(self, amount: float, turn: int, insured: bool = False,
                             cover_condition_met: bool = True) -> dict[str, float]:
        """Les coûts d'incident sont supportés par l'organisation (hors budget SSI)."""
        reimbursed = 0.0
        if insured and cover_condition_met:
            reimbursed = min(self.org.plafond_assurance,
                             max(0.0, amount - INSURANCE_DEDUCTIBLE) * INSURANCE_COVER)
        net = amount - reimbursed
        self.cout_incident_cumule += net
        self.remboursements_assurance += reimbursed
        return {"brut": amount, "rembourse": reimbursed, "net": net}

    def record_fine(self, amount: float, turn: int, label: str) -> None:
        self.amendes_cumulees += amount

    # -- exercice budgétaire -----------------------------------------------------------
    def new_year(self, new_budget: float, maintenance: list[tuple[str, str, float, str]], turn: int) -> list[str]:
        """Clôt l'exercice, ouvre le suivant et impute les maintenances.

        ``maintenance`` : liste (id_mesure, libellé, coût annuel, poste). Les mesures dont
        la maintenance ne peut être financée sont renvoyées (à suspendre).
        """
        self.yearly.append({"annee": self.year, "budget": self.budget_annuel_ssi, "depense": self.spent})
        self.year += 1
        old_total = self.budget_annuel_ssi or 1.0
        self.budget_annuel_ssi = float(new_budget)
        for c in self.categories.values():
            c["alloue"] = float(round(c["alloue"] * new_budget / old_total))
            c["depense"] = 0.0
        self._fix_rounding()
        unfunded = []
        for mid, label, cost, category in sorted(maintenance, key=lambda m: m[2]):
            if cost <= 0:
                continue
            if cost <= self.remaining + 1e-6:
                self.spend(cost, category, f"Maintenance — {label}", turn)
            else:
                unfunded.append(mid)
        return unfunded

    # -- ROI -----------------------------------------------------------------------------
    @staticmethod
    def annualized_cost(deploy_cost: float, annual_cost: float) -> float:
        return deploy_cost / AMORTIZATION_YEARS + annual_cost

    def measure_roi(self, measure: "Measure", deploy_cost: float, annual_cost: float,
                    frequencies: dict[str, float], avg_costs: dict[str, float]) -> dict[str, Any]:
        """ROI détaillé d'une mesure (détail par type d'incident pour l'affichage)."""
        cost = self.annualized_cost(deploy_cost, annual_cost)
        lines, avoided = [], 0.0
        for t, freq in frequencies.items():
            r_p = measure.reduction_for(t)
            r_i = measure.impact_reduction_for(t)
            coeff = 1.0 - (1.0 - r_p) * (1.0 - r_i)
            if coeff <= 0 or freq <= 0:
                continue
            value = freq * avg_costs.get(t, 0.0) * coeff
            avoided += value
            lines.append({"type": t, "freq": freq, "cout_moyen": avg_costs.get(t, 0.0),
                          "coeff": coeff, "evite": value})
        ratio = avoided / cost if cost > 0 else (float("inf") if avoided > 0 else 0.0)
        self.roi_mesures[measure.id] = ratio
        return {"roi": ratio, "cout_annuel": cost, "cout_evite": avoided, "detail": lines,
                "rentable": ratio > 1}

    def weekly_spending(self, turn: int, weeks: int = 12) -> list[tuple[int, float]]:
        start = max(1, turn - weeks + 1)
        totals = {t: 0.0 for t in range(start, turn + 1)}
        for e in self.history:
            if e.turn in totals:
                totals[e.turn] += e.amount
        return sorted(totals.items())

    # -- sérialisation ----------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_annuel_ssi": self.budget_annuel_ssi, "year": self.year,
            "categories": {k: dict(v) for k, v in self.categories.items()},
            "cout_incident_cumule": self.cout_incident_cumule, "amendes_cumulees": self.amendes_cumulees,
            "remboursements_assurance": self.remboursements_assurance,
            "roi_mesures": dict(self.roi_mesures), "history": [e.to_dict() for e in self.history],
            "yearly": list(self.yearly),
        }

    def load_dict(self, d: dict[str, Any]) -> None:
        self.budget_annuel_ssi = float(d["budget_annuel_ssi"])
        self.year = int(d["year"])
        self.categories = {k: {"alloue": float(v["alloue"]), "depense": float(v["depense"])}
                           for k, v in d["categories"].items()}
        self.cout_incident_cumule = float(d["cout_incident_cumule"])
        self.amendes_cumulees = float(d["amendes_cumulees"])
        self.remboursements_assurance = float(d.get("remboursements_assurance", 0.0))
        self.roi_mesures = dict(d.get("roi_mesures", {}))
        self.history = [Expense(**e) for e in d.get("history", [])]
        self.yearly = list(d.get("yearly", []))
