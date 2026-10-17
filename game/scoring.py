"""Score de fin de partie (0-100), grille d'évaluation et synthèse pédagogique."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import config
from game.state import DecisionRecord, Mistake

if TYPE_CHECKING:
    from game.simulation import Simulation

WEIGHTS = {"reputation": 0.25, "risque": 0.20, "conformite": 0.15, "crise": 0.15, "finances": 0.10,
           "objectifs": 0.15}
WEIGHT_LABELS = {
    "objectifs": "Objectifs de mandat",
    "reputation": "Réputation et confiance de la direction",
    "risque": "Maîtrise du risque (EBIOS RM)",
    "conformite": "Conformité réglementaire",
    "crise": "Gestion de crise",
    "finances": "Impact financier",
}
# Distribution de référence (parties simulées par des joueurs automatiques de niveaux
# variés : 120 parties = 4 difficultés × 3 profils × 5 organisations × 2 graines, cf. docs/METHODOLOGIE.md).
# Ce n'est PAS un benchmark officiel de l'ANSSI.
REFERENCE_MEAN = 46.0
REFERENCE_SD = 25.0
GAME_OVER_CAP = 30.0


@dataclass
class ScoreCard:
    total: float
    grade: str
    percentile: int
    components: dict[str, float]
    best_decisions: list[DecisionRecord] = field(default_factory=list)
    worst_mistakes: list[Mistake] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "grade": self.grade, "percentile": self.percentile,
                "components": dict(self.components)}


def grade_for(score: float) -> str:
    label = config.SCORE_GRADES[0][1]
    for threshold, name in config.SCORE_GRADES:
        if score >= threshold:
            label = name
    return label


def percentile_for(score: float) -> int:
    z = (score - REFERENCE_MEAN) / REFERENCE_SD
    return int(round(100 * 0.5 * (1 + math.erf(z / math.sqrt(2)))))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_components(sim: "Simulation") -> dict[str, float]:
    turn = sim.turn
    reputation = _clamp01(0.8 * sim.reputation.global_score() / 100.0 + 0.2 * sim.trust / 100.0)

    initial = sim.initial_risk or 1.0
    current = sim.risk.average_risk(turn)
    improvement = _clamp01(0.5 + 0.5 * (initial - current) / initial)
    risque = 0.6 * improvement + 0.4 * sim.risk.study_quality()

    rate = sim.compliance.compliance_rate(turn, sim.active_measure_ids, sim.risk.study.completed_turn)
    conformite = 0.5 * sim.compliance.notification_rate() + 0.5 * rate

    incidents = [i for i in sim.incidents.incidents if i.decisions_taken]
    if incidents:
        crise = sum(sim.incidents.decision_quality(i) for i in incidents) / len(incidents)
    else:
        crise = 0.7  # aucune crise : neutre, ni bonus ni malus
    losses = sim.budget.cout_incident_cumule + sim.budget.amendes_cumulees
    finances = _clamp01(1.0 - losses / max(1.0, sim.org.budget_it * sim.years))
    objs = sim.objectives
    if objs:
        objectifs = sum({"reussi": 1.0, "en_cours": 0.5, "echoue": 0.0}[o["status"]] for o in objs) / len(objs)
    else:
        objectifs = 0.5
    return {"reputation": reputation, "risque": _clamp01(risque), "conformite": _clamp01(conformite),
            "crise": _clamp01(crise), "finances": finances, "objectifs": objectifs}


def compute_score(sim: "Simulation") -> ScoreCard:
    comps = compute_components(sim)
    total = 100.0 * sum(comps[k] * w for k, w in WEIGHTS.items())
    if sim.reputation.is_game_over() or (sim.game_over_reason or "").startswith("Fin de mandat anticipée"):
        total = min(total, GAME_OVER_CAP)
    total = round(total, 1)
    good = [d for d in sim.decisions if d.quality == "bonne"]
    good.sort(key=lambda d: (0 if "#" in d.source else 1, -len(d.feedback)))
    mistakes = sorted(sim.mistakes, key=lambda m: (-m.weight, m.turn))
    return ScoreCard(total, grade_for(total), percentile_for(total), comps,
                     _unique(good, lambda d: d.choice)[:3], _unique(mistakes, lambda m: m.title)[:3])


def _unique(items: list, key) -> list:  # type: ignore[type-arg, no-untyped-def]
    """Supprime les doublons (même décision ou même erreur répétée sur plusieurs incidents)."""
    seen, out = set(), []
    for it in items:
        k = key(it)
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out
