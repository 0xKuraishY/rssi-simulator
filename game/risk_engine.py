"""Moteur de risque conforme à la méthode EBIOS Risk Manager (ANSSI, 2018 — v1.5 2024).

Les 5 ateliers sont modélisés comme des étapes jouables :

1. Cadrage et socle de sécurité : classement des biens supports, socle d'hygiène (42 mesures)
2. Sources de risque : couples SR/OV jugés pertinents
3. Scénarios stratégiques : SR + OV + chemin d'attaque, matrice 4×4 ajustable
4. Scénarios opérationnels : mode opératoire MITRE ATT&CK, vraisemblance résiduelle
5. Traitement : Accepter | Réduire | Transférer | Refuser, sous contrainte budgétaire

Formules (documentées dans docs/METHODOLOGIE.md) :
- Niveau de risque = Vraisemblance (1-4) × Gravité (1-4)
- Gravité = max(D, I, C, T) de l'impact du scénario (approche « pire cas » EBIOS RM)
- Vraisemblance stratégique = arrondi((2 × pertinence SR + ressources SR + exposition) / 4)
- Vraisemblance opérationnelle = max(1, arrondi(V × (1 - réduction combinée des mesures)))
- Réduction combinée = 1 - Π(1 - r_i), plafonnée à 90 %
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from game.measures import Measure, MeasurePortfolio, combine_reductions
from game.organisation import INCIDENT_TYPES, Organisation

SCALE_MIN, SCALE_MAX = 1, 4
LIKELIHOOD_LABELS = {1: "Peu vraisemblable", 2: "Vraisemblable", 3: "Très vraisemblable", 4: "Quasi certain"}
SEVERITY_LABELS = {1: "Mineure", 2: "Significative", 3: "Grave", 4: "Critique"}
RISK_LABELS = {"faible": "Faible", "modere": "Modéré", "eleve": "Élevé", "critique": "Critique"}
HYGIENE_COUNT = 42
REFUSAL_FACTOR = 0.4  # « Refuser » : l'activité exposée est supprimée / fortement restreinte


class Treatment(str, Enum):
    ACCEPTER = "accepter"
    REDUIRE = "reduire"
    TRANSFERER = "transferer"
    REFUSER = "refuser"


TREATMENT_LABELS = {
    Treatment.ACCEPTER.value: "Accepter",
    Treatment.REDUIRE.value: "Réduire",
    Treatment.TRANSFERER.value: "Transférer",
    Treatment.REFUSER.value: "Refuser",
}


# ---------------------------------------------------------------------------
# Fonctions de calcul pures
# ---------------------------------------------------------------------------
def clamp_scale(value: float) -> int:
    return int(max(SCALE_MIN, min(SCALE_MAX, round(value))))


def risk_score(likelihood: int, severity: int) -> int:
    if not (SCALE_MIN <= likelihood <= SCALE_MAX and SCALE_MIN <= severity <= SCALE_MAX):
        raise ValueError("Vraisemblance et gravité doivent être comprises entre 1 et 4")
    return likelihood * severity


def risk_category(score: int) -> str:
    if score >= 12:
        return "critique"
    if score >= 8:
        return "eleve"
    if score >= 4:
        return "modere"
    return "faible"


def severity_from_dict(impact: dict[str, int]) -> int:
    values = [int(impact.get(k, 1)) for k in ("D", "I", "C", "T")]
    return clamp_scale(max(values))


def likelihood_from_probability(p_annual: float) -> int:
    """Conversion probabilité annuelle → échelle de vraisemblance EBIOS."""
    if p_annual >= 0.30:
        return 4
    if p_annual >= 0.15:
        return 3
    if p_annual >= 0.05:
        return 2
    return 1


def operational_likelihood(strategic_likelihood: int, reduction: float) -> int:
    return clamp_scale(strategic_likelihood * (1.0 - reduction))


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


# ---------------------------------------------------------------------------
# Référentiels
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RiskSource:
    id: str
    nom: str
    description: str
    motivation: int
    ressources: int
    objectifs: list[str]
    pertinence: dict[str, int]

    def pertinence_for(self, secteur: str) -> int:
        return int(self.pertinence.get(secteur, self.pertinence.get("defaut", 1)))


@dataclass(frozen=True)
class TargetObjective:
    id: str
    nom: str
    description: str
    types_incident: list[str]


@dataclass(frozen=True)
class AttackPath:
    id: str
    nom: str
    description: str
    vecteur: str  # internet | ecosysteme | interne | physique
    types_incident: list[str]


@dataclass(frozen=True)
class HygieneMeasure:
    id: int
    theme: str
    titre: str


@dataclass(frozen=True)
class RiskReferential:
    sources: dict[str, RiskSource]
    objectives: dict[str, TargetObjective]
    paths: dict[str, AttackPath]
    hygiene: dict[int, HygieneMeasure]

    @classmethod
    def from_dicts(cls, risk_data: dict[str, Any], hygiene_data: dict[str, Any]) -> "RiskReferential":
        sources = {
            s["id"]: RiskSource(s["id"], s["nom"], s.get("description", ""), int(s["motivation"]),
                                int(s["ressources"]), list(s["objectifs"]),
                                {k: int(v) for k, v in s["pertinence"].items()})
            for s in risk_data["sources_risque"]
        }
        objectives = {
            o["id"]: TargetObjective(o["id"], o["nom"], o.get("description", ""), list(o["types_incident"]))
            for o in risk_data["objectifs_vises"]
        }
        paths = {
            p["id"]: AttackPath(p["id"], p["nom"], p.get("description", ""), p["vecteur"],
                                list(p["types_incident"]))
            for p in risk_data["chemins_attaque"]
        }
        hygiene = {}
        for theme in hygiene_data["themes"]:
            for m in theme["mesures"]:
                hygiene[int(m["id"])] = HygieneMeasure(int(m["id"]), theme["nom"], m["titre"])
        return cls(sources, objectives, paths, hygiene)


# ---------------------------------------------------------------------------
# Étude EBIOS RM (état du joueur)
# ---------------------------------------------------------------------------
@dataclass
class StrategicScenario:
    id: str
    sr_id: str
    ov_id: str
    path_id: str
    likelihood_calc: int
    severity_calc: int
    likelihood: int
    severity: int
    incident_types: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return risk_score(self.likelihood, self.severity)

    @property
    def deviation(self) -> int:
        return abs(self.likelihood - self.likelihood_calc) + abs(self.severity - self.severity_calc)


@dataclass
class OperationalScenario:
    id: str
    strategic_id: str
    incident_type: str
    techniques: list[str]
    impact: dict[str, int]
    likelihood_base: int
    likelihood: int
    severity: int

    @property
    def score(self) -> int:
        return risk_score(self.likelihood, self.severity)

    @property
    def category(self) -> str:
        return risk_category(self.score)


@dataclass
class EbiosStudy:
    done: list[bool] = field(default_factory=lambda: [False] * 5)
    completed_turn: int | None = None
    asset_classification: dict[str, str] = field(default_factory=dict)
    hygiene_validated: bool = False
    hygiene_priorities: list[int] = field(default_factory=list)
    selected_pairs: list[str] = field(default_factory=list)  # "SR1:OV2"
    strategic: list[StrategicScenario] = field(default_factory=list)
    operational: list[OperationalScenario] = field(default_factory=list)
    treatments: dict[str, str] = field(default_factory=dict)  # scénario opérationnel → option
    scores: list[float] = field(default_factory=lambda: [0.0] * 5)

    def unlocked(self, workshop: int) -> bool:
        """Les ateliers sont accessibles séquentiellement (1 → 5)."""
        return workshop == 1 or all(self.done[: workshop - 1])

    @property
    def complete(self) -> bool:
        return all(self.done)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EbiosStudy":
        d = dict(d)
        d["strategic"] = [StrategicScenario(**s) for s in d.get("strategic", [])]
        d["operational"] = [OperationalScenario(**s) for s in d.get("operational", [])]
        return cls(**d)


# ---------------------------------------------------------------------------
# Moteur
# ---------------------------------------------------------------------------
class RiskEngine:
    def __init__(
        self,
        org: Organisation,
        referential: RiskReferential,
        portfolio: MeasurePortfolio,
        incident_impacts: dict[str, dict[str, int]],
        attack_chains: dict[str, list[str]] | None = None,
    ) -> None:
        self.org = org
        self.ref = referential
        self.portfolio = portfolio
        self.incident_impacts = incident_impacts
        self.attack_chains = attack_chains or {}
        self.study = EbiosStudy()
        # Multiplicateurs temporaires de probabilité : type → [(facteur, tour d'expiration)]
        self.modifiers: list[dict[str, Any]] = []
        # Facteur contextuel fourni par la simulation (difficulté, niveau de menace, vulnérabilités…)
        self.external_factor: Callable[[str, int], float] | None = None

    # -- types applicables -------------------------------------------------------
    def applicable_types(self) -> list[str]:
        return [t for t in INCIDENT_TYPES if self.org.base_probability(t) > 0]

    # -- socle d'hygiène -----------------------------------------------------------
    def hygiene_in_place(self, turn: int) -> set[int]:
        ids = set(self.org.socle_hygiene)
        ids.add(39)  # un référent SSI est désigné : c'est le joueur
        for m in self.portfolio.active(turn):
            ids.update(m.hygiene)
        if self.study.complete:
            ids.add(41)  # analyse de risques formelle menée
        return {i for i in ids if 1 <= i <= HYGIENE_COUNT}

    def hygiene_coverage(self, turn: int) -> float:
        return len(self.hygiene_in_place(turn)) / HYGIENE_COUNT

    def hygiene_factor(self, turn: int) -> float:
        """Socle faible → ×1,2 ; socle complet → ×0,8."""
        return 1.2 - 0.4 * self.hygiene_coverage(turn)

    # -- réductions ----------------------------------------------------------------
    def reduction(self, incident_type: str, turn: int, measures: Iterable[Measure] | None = None) -> float:
        active = list(measures) if measures is not None else self.portfolio.active(turn)
        return combine_reductions(m.reduction_for(incident_type) for m in active)

    def impact_reduction(self, incident_type: str, turn: int,
                         measures: Iterable[Measure] | None = None) -> float:
        active = list(measures) if measures is not None else self.portfolio.active(turn)
        return combine_reductions(m.impact_reduction_for(incident_type) for m in active)

    def detection_factor(self, turn: int, measures: Iterable[Measure] | None = None) -> float:
        """Facteur multiplicatif du délai de détection (1 = aucune capacité)."""
        active = list(measures) if measures is not None else self.portfolio.active(turn)
        return 1.0 - combine_reductions((m.detection for m in active), cap=0.85)

    # -- modificateurs temporaires -----------------------------------------------------
    def add_modifier(self, incident_type: str, factor: float, until_turn: int, source: str = "") -> None:
        self.modifiers.append({"type": incident_type, "factor": factor, "until": until_turn, "source": source})

    def purge_modifiers(self, turn: int) -> None:
        self.modifiers = [m for m in self.modifiers if m["until"] >= turn]

    def modifier_factor(self, incident_type: str, turn: int) -> float:
        f = 1.0
        for m in self.modifiers:
            if m["until"] >= turn and m["type"] in (incident_type, "tous"):
                f *= float(m["factor"])
        return f

    def treatment_factor(self, incident_type: str) -> float:
        refused = {op.incident_type for op in self.study.operational
                   if self.study.treatments.get(op.id) == Treatment.REFUSER.value}
        return REFUSAL_FACTOR if incident_type in refused else 1.0

    # -- probabilités ----------------------------------------------------------------
    def annual_probability(self, incident_type: str, turn: int,
                           measures: Iterable[Measure] | None = None) -> float:
        base = self.org.base_probability(incident_type)
        if base <= 0:
            return 0.0
        measures = list(measures) if measures is not None else None
        p = (base * self.hygiene_factor(turn) * (1.0 - self.reduction(incident_type, turn, measures))
             * self.modifier_factor(incident_type, turn) * self.treatment_factor(incident_type)
             * (self.external_factor(incident_type, turn) if self.external_factor else 1.0))
        return max(0.0, min(0.95, p))

    def weekly_probability(self, incident_type: str, turn: int) -> float:
        """Probabilité hebdomadaire équivalente : 1 - (1 - p)^(1/52)."""
        p = self.annual_probability(incident_type, turn)
        return 1.0 - (1.0 - p) ** (1.0 / 52.0)

    # -- risque résiduel par type ------------------------------------------------------
    def residual_severity(self, incident_type: str, turn: int,
                          measures: Iterable[Measure] | None = None) -> int:
        g = severity_from_dict(self.incident_impacts.get(incident_type, {}))
        red = self.impact_reduction(incident_type, turn, measures)
        return clamp_scale(math.ceil(g * (1.0 - 0.5 * red)))

    def type_risk(self, incident_type: str, turn: int,
                  measures: Iterable[Measure] | None = None) -> tuple[int, int]:
        measures = list(measures) if measures is not None else None
        v = likelihood_from_probability(self.annual_probability(incident_type, turn, measures))
        g = self.residual_severity(incident_type, turn, measures)
        return v, g

    def risk_matrix(self, turn: int, measures: Iterable[Measure] | None = None) -> dict[str, tuple[int, int]]:
        measures = list(measures) if measures is not None else None
        return {t: self.type_risk(t, turn, measures) for t in self.applicable_types()}

    def global_risk(self, turn: int) -> tuple[int, str]:
        """Niveau de risque global = pire couple (V×G) parmi les menaces applicables."""
        matrix = self.risk_matrix(turn)
        if not matrix:
            return 1, "faible"
        worst = max(v * g for v, g in matrix.values())
        return worst, risk_category(worst)

    def average_risk(self, turn: int) -> float:
        matrix = self.risk_matrix(turn)
        return sum(v * g for v, g in matrix.values()) / max(1, len(matrix))

    # =========================================================================
    # Atelier 1 — Cadrage et socle
    # =========================================================================
    def classify_asset(self, asset_id: str, criticite: str) -> None:
        if criticite not in ("primaire", "secondaire"):
            raise ValueError("criticite doit valoir 'primaire' ou 'secondaire'")
        if asset_id not in {a.id for a in self.org.assets_critiques}:
            raise KeyError(asset_id)
        self.study.asset_classification[asset_id] = criticite

    def workshop1_score(self) -> float:
        assets = self.org.assets_critiques
        if not assets:
            return 1.0
        good = sum(1 for a in assets if self.study.asset_classification.get(a.id) == a.criticite)
        return good / len(assets)

    def hygiene_gaps(self, turn: int) -> list[HygieneMeasure]:
        in_place = self.hygiene_in_place(turn)
        return [m for i, m in sorted(self.ref.hygiene.items()) if i not in in_place]

    def toggle_hygiene_priority(self, hygiene_id: int) -> None:
        pr = self.study.hygiene_priorities
        if hygiene_id in pr:
            pr.remove(hygiene_id)
        elif len(pr) < 10:
            pr.append(hygiene_id)

    def complete_workshop1(self) -> float:
        if len(self.study.asset_classification) < len(self.org.assets_critiques):
            raise ValueError("Tous les biens supports doivent être classés")
        self.study.hygiene_validated = True
        return self._complete(1, self.workshop1_score())

    # =========================================================================
    # Atelier 2 — Sources de risque
    # =========================================================================
    def all_pairs(self) -> list[tuple[RiskSource, TargetObjective]]:
        return [(sr, self.ref.objectives[ov]) for sr in self.ref.sources.values()
                for ov in sr.objectifs if ov in self.ref.objectives]

    def pair_pertinence(self, sr_id: str) -> int:
        return self.ref.sources[sr_id].pertinence_for(self.org.secteur)

    def expected_pairs(self) -> set[str]:
        """Couples de référence : pertinence sectorielle ≥ 3."""
        return {f"{sr.id}:{ov.id}" for sr, ov in self.all_pairs() if self.pair_pertinence(sr.id) >= 3}

    def toggle_pair(self, sr_id: str, ov_id: str) -> bool:
        key = f"{sr_id}:{ov_id}"
        if ov_id not in self.ref.sources[sr_id].objectifs:
            raise ValueError(f"{ov_id} n'est pas un objectif de {sr_id}")
        if key in self.study.selected_pairs:
            self.study.selected_pairs.remove(key)
            return False
        self.study.selected_pairs.append(key)
        return True

    def workshop2_score(self) -> float:
        """F-mesure entre la sélection du joueur et la référence sectorielle."""
        selected, expected = set(self.study.selected_pairs), self.expected_pairs()
        if not expected:
            return 1.0 if not selected else 0.5
        tp = len(selected & expected)
        if tp == 0:
            return 0.0
        precision, recall = tp / len(selected), tp / len(expected)
        return 2 * precision * recall / (precision + recall)

    def complete_workshop2(self) -> float:
        if not self.study.selected_pairs:
            raise ValueError("Sélectionnez au moins un couple SR/OV")
        return self._complete(2, self.workshop2_score())

    # =========================================================================
    # Atelier 3 — Scénarios stratégiques
    # =========================================================================
    def scenario_types(self, ov_id: str, path_id: str) -> list[str]:
        ov_types = self.ref.objectives[ov_id].types_incident
        path_types = self.ref.paths[path_id].types_incident
        types = [t for t in ov_types if t in path_types] or list(ov_types)
        applicable = set(self.applicable_types())
        return [t for t in types if t in applicable]

    def strategic_likelihood(self, sr_id: str, path_id: str) -> int:
        sr = self.ref.sources[sr_id]
        exposure = self.org.exposition.get(self.ref.paths[path_id].vecteur, 2)
        return clamp_scale(round_half_up((2 * self.pair_pertinence(sr_id) + sr.ressources + exposure) / 4))

    def strategic_severity(self, types: list[str]) -> int:
        if not types:
            return 1
        return max(severity_from_dict(self.incident_impacts.get(t, {})) for t in types)

    def add_strategic_scenario(self, pair_key: str, path_id: str) -> StrategicScenario:
        if pair_key not in self.study.selected_pairs:
            raise ValueError("Le couple SR/OV doit avoir été retenu en atelier 2")
        if path_id not in self.ref.paths:
            raise KeyError(path_id)
        sr_id, ov_id = pair_key.split(":")
        types = self.scenario_types(ov_id, path_id)
        v = self.strategic_likelihood(sr_id, path_id)
        g = self.strategic_severity(types)
        scenario = StrategicScenario(
            id=f"SS{len(self.study.strategic) + 1:02d}", sr_id=sr_id, ov_id=ov_id, path_id=path_id,
            likelihood_calc=v, severity_calc=g, likelihood=v, severity=g, incident_types=types,
        )
        self.study.strategic.append(scenario)
        return scenario

    def remove_strategic_scenario(self, scenario_id: str) -> None:
        self.study.strategic = [s for s in self.study.strategic if s.id != scenario_id]

    def adjust_strategic(self, scenario_id: str, likelihood: int, severity: int) -> StrategicScenario:
        for s in self.study.strategic:
            if s.id == scenario_id:
                s.likelihood, s.severity = clamp_scale(likelihood), clamp_scale(severity)
                return s
        raise KeyError(scenario_id)

    def workshop3_score(self) -> float:
        if not self.study.strategic:
            return 0.0
        covered = {f"{s.sr_id}:{s.ov_id}" for s in self.study.strategic}
        coverage = len(covered & set(self.study.selected_pairs)) / max(1, len(self.study.selected_pairs))
        # Un ajustement est légitime (contexte), mais un écart > 1 cran pénalise
        calibration = sum(1.0 if s.deviation <= 1 else 0.5 for s in self.study.strategic) / len(self.study.strategic)
        return round(0.5 * coverage + 0.5 * calibration, 3)

    def complete_workshop3(self) -> float:
        if not self.study.strategic:
            raise ValueError("Construisez au moins un scénario stratégique")
        return self._complete(3, self.workshop3_score())

    # =========================================================================
    # Atelier 4 — Scénarios opérationnels
    # =========================================================================
    def build_operational(self, turn: int, measures: Iterable[Measure] | None = None) -> list[OperationalScenario]:
        measures = list(measures) if measures is not None else None
        result: list[OperationalScenario] = []
        for s in self.study.strategic:
            for t in s.incident_types:
                red = self.reduction(t, turn, measures)
                result.append(OperationalScenario(
                    id=f"{s.id}-{t}",
                    strategic_id=s.id,
                    incident_type=t,
                    techniques=list(self.attack_chains.get(t, [])),
                    impact=dict(self.incident_impacts.get(t, {})),
                    likelihood_base=s.likelihood,
                    likelihood=operational_likelihood(s.likelihood, red),
                    severity=self.residual_severity(t, turn, measures),
                ))
        return result

    def generate_operational(self, turn: int) -> list[OperationalScenario]:
        self.study.operational = self.build_operational(turn)
        return self.study.operational

    def complete_workshop4(self, turn: int) -> float:
        if not self.study.operational:
            self.generate_operational(turn)
        if not self.study.operational:
            raise ValueError("Aucun scénario opérationnel applicable")
        return self._complete(4, 1.0)

    # =========================================================================
    # Atelier 5 — Traitement du risque
    # =========================================================================
    def set_treatment(self, scenario_id: str, option: str) -> None:
        if option not in TREATMENT_LABELS:
            raise ValueError(f"Option de traitement inconnue : {option}")
        if scenario_id not in {o.id for o in self.study.operational}:
            raise KeyError(scenario_id)
        self.study.treatments[scenario_id] = option

    def simulate_treatment(self, turn: int, extra_measures: Iterable[Measure]) -> dict[str, Any]:
        """Avant/après : scénarios opérationnels avec les mesures actives
        puis avec les mesures actives + celles envisagées."""
        current = self.portfolio.active(turn)
        extra = [m for m in extra_measures if m.id not in {c.id for c in current}]
        before = self.build_operational(turn, current)
        after = self.build_operational(turn, current + extra)
        return {
            "before": before,
            "after": after,
            "before_max": max((o.score for o in before), default=0),
            "after_max": max((o.score for o in after), default=0),
            "before_avg": sum(o.score for o in before) / max(1, len(before)),
            "after_avg": sum(o.score for o in after) / max(1, len(after)),
        }

    def workshop5_score(self, has_insurance: bool) -> float:
        ops = self.study.operational
        if not ops:
            return 0.0
        points = 0.0
        for op in ops:
            option = self.study.treatments.get(op.id)
            if option is None:
                continue
            if option == Treatment.ACCEPTER.value:
                points += 1.0 if op.score < 8 else 0.0  # accepter un risque élevé/critique = faute
            elif option == Treatment.TRANSFERER.value:
                points += 1.0 if has_insurance else 0.25
            elif option == Treatment.REFUSER.value:
                points += 0.75 if op.score >= 8 else 0.25
            else:
                points += 1.0 if op.score >= 4 else 0.75
        return round(points / len(ops), 3)

    def complete_workshop5(self, turn: int, has_insurance: bool) -> float:
        missing = [o.id for o in self.study.operational if o.id not in self.study.treatments]
        if missing:
            raise ValueError(f"Choisissez une option de traitement pour : {', '.join(missing)}")
        score = self._complete(5, self.workshop5_score(has_insurance))
        self.study.completed_turn = turn
        return score

    def accepted_high_risk_types(self) -> set[str]:
        return {o.incident_type for o in self.study.operational
                if self.study.treatments.get(o.id) == Treatment.ACCEPTER.value and o.score >= 8}

    # -- commun ------------------------------------------------------------------------
    def _complete(self, workshop: int, score: float) -> float:
        if not self.study.unlocked(workshop):
            raise ValueError(f"L'atelier {workshop} n'est pas encore accessible")
        self.study.done[workshop - 1] = True
        self.study.scores[workshop - 1] = round(score, 3)
        return self.study.scores[workshop - 1]

    def reset_study(self) -> None:
        self.study = EbiosStudy()

    def study_quality(self) -> float:
        return sum(self.study.scores) / 5.0

    # -- sérialisation -------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {"study": self.study.to_dict(), "modifiers": list(self.modifiers)}

    def load_dict(self, data: dict[str, Any]) -> None:
        self.study = EbiosStudy.from_dict(data.get("study", {}))
        self.modifiers = list(data.get("modifiers", []))
