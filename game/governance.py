"""Gouvernance : confiance de la direction, comités trimestriels, objectifs de mandat."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from game.simulation import Simulation

TRUST_INITIAL = 60.0
TRUST_DISMISSAL = 15.0
BOARD_PERIOD = 13          # un comité de direction par trimestre


# =============================================================================
# Objectifs de mandat
# =============================================================================
@dataclass(frozen=True)
class ObjectiveDef:
    id: str
    titre: str
    description: str
    applies: Callable[["Simulation"], bool]
    evaluate: Callable[["Simulation", dict[str, Any]], str]   # "en_cours" | "reussi" | "echoue"
    params: Callable[["Simulation"], dict[str, Any]] = lambda sim: {}


def _end(sim: "Simulation") -> bool:
    return sim.finished or sim.turn >= sim.calendar.total_turns


def _deadline(sim: "Simulation", year: int) -> int:
    return min(sim.calendar.total_turns, year * sim.calendar.weeks_per_year)


def _ebios(sim: "Simulation", p: dict[str, Any]) -> str:
    done = sim.risk.study.completed_turn
    if done is not None and done <= p["deadline"]:
        return "reussi"
    return "echoue" if sim.turn > p["deadline"] else "en_cours"


def _hygiene(sim: "Simulation", p: dict[str, Any]) -> str:
    if sim.risk.hygiene_coverage(sim.turn) >= p["target"] - 1e-9:
        return "reussi"
    return "echoue" if sim.turn > p["deadline"] else "en_cours"


def _iso(sim: "Simulation", p: dict[str, Any]) -> str:
    if "M38" in sim.active_measure_ids:
        return "reussi"
    return "echoue" if sim.turn > p["deadline"] else "en_cours"


def _no_fine(sim: "Simulation", p: dict[str, Any]) -> str:
    if sim.budget.amendes_cumulees > 0:
        return "echoue"
    return "reussi" if _end(sim) else "en_cours"


def _notif(sim: "Simulation", p: dict[str, Any]) -> str:
    st = sim.compliance.state
    if st.missed or st.late:
        return "echoue"
    return "reussi" if _end(sim) else "en_cours"


def _phishing(sim: "Simulation", p: dict[str, Any]) -> str:
    if any(r <= p["target"] for _, r in sim.phishing.measured):
        return "reussi"
    return "echoue" if _end(sim) else "en_cours"


def _vulns(sim: "Simulation", p: dict[str, Any]) -> str:
    if sim.objective_flags.get("vuln_breach"):
        return "echoue"
    return "reussi" if _end(sim) else "en_cours"


def _reputation(sim: "Simulation", p: dict[str, Any]) -> str:
    if not _end(sim):
        return "en_cours"
    return "reussi" if sim.reputation.global_score() >= p["target"] else "echoue"


def _trust(sim: "Simulation", p: dict[str, Any]) -> str:
    if not _end(sim):
        return "en_cours"
    return "reussi" if sim.trust >= p["target"] else "echoue"


def _losses(sim: "Simulation", p: dict[str, Any]) -> str:
    if sim.budget.cout_incident_cumule + sim.budget.amendes_cumulees > p["max"]:
        return "echoue"
    return "reussi" if _end(sim) else "en_cours"


def _risk(sim: "Simulation", p: dict[str, Any]) -> str:
    if sim.objective_flags.get("risk_reached"):
        return "reussi"
    return "echoue" if sim.turn > p["deadline"] else "en_cours"


OBJECTIVES: dict[str, ObjectiveDef] = {o.id: o for o in (
    ObjectiveDef("OBJ-EBIOS", "Analyse de risques en 6 mois",
                 "Finaliser l'étude EBIOS RM (5 ateliers) avant la semaine 26.",
                 lambda s: True, _ebios, lambda s: {"deadline": min(26, s.calendar.total_turns)}),
    ObjectiveDef("OBJ-HYG", "Socle d'hygiène renforcé",
                 "Atteindre la couverture cible du socle d'hygiène ANSSI avant la fin de la première année.",
                 lambda s: True, _hygiene,
                 lambda s: {"target": min(0.9, round((s.risk.hygiene_coverage(1) + 0.25) * 20) / 20),
                            "deadline": _deadline(s, 1)}),
    ObjectiveDef("OBJ-ISO", "Certification ISO 27001",
                 "Obtenir la certification ISO/IEC 27001 avant la fin de la deuxième année (exigence clients).",
                 lambda s: s.org.regimes.iso27001 and s.calendar.total_turns >= 104, _iso,
                 lambda s: {"deadline": _deadline(s, 2)}),
    ObjectiveDef("OBJ-NOFINE", "Zéro sanction", "Ne subir aucune sanction financière pendant le mandat.",
                 lambda s: True, _no_fine),
    ObjectiveDef("OBJ-NOTIF", "Notifications exemplaires",
                 "Respecter 100 % des délais de notification réglementaire.",
                 lambda s: s.org.regimes.nis2 is not None or s.org.regimes.lpm_oiv, _notif),
    ObjectiveDef("OBJ-PHISH", "Personnel vigilant",
                 "Mesurer, lors d'une campagne de faux hameçonnage, un taux de clic inférieur à 8 %.",
                 lambda s: True, _phishing, lambda s: {"target": 0.08}),
    ObjectiveDef("OBJ-VULN", "Surface exposée maîtrisée",
                 "Ne jamais laisser une vulnérabilité critique exposée sur Internet sans traitement plus de 4 semaines.",
                 lambda s: True, _vulns),
    ObjectiveDef("OBJ-REP", "Image préservée", "Terminer le mandat avec une réputation globale d'au moins 70/100.",
                 lambda s: True, _reputation, lambda s: {"target": 70}),
    ObjectiveDef("OBJ-TRUST", "Soutien de la direction",
                 "Terminer le mandat avec une confiance de la direction d'au moins 65/100.",
                 lambda s: True, _trust, lambda s: {"target": 65}),
    ObjectiveDef("OBJ-LOSS", "Pertes contenues",
                 "Limiter les pertes (incidents + sanctions) à 40 % d'un budget informatique annuel.",
                 lambda s: True, _losses, lambda s: {"max": round(0.4 * s.org.budget_it, -3)}),
    ObjectiveDef("OBJ-RISK", "Risque ramené sous le critique",
                 "Ramener le niveau de risque global à « élevé » ou moins avant la fin de la deuxième année.",
                 lambda s: True, _risk, lambda s: {"deadline": _deadline(s, 2)}),
)}

OBJECTIVE_STATUS_LABELS = {"en_cours": "En cours", "reussi": "Atteint", "echoue": "Manqué"}


def draw_objectives(sim: "Simulation", rng: random.Random, n: int = 3) -> list[dict[str, Any]]:
    pool = sorted(o.id for o in OBJECTIVES.values() if o.applies(sim))
    chosen = rng.sample(pool, min(n, len(pool)))
    return [{"id": oid, "params": OBJECTIVES[oid].params(sim), "status": "en_cours", "turn": None}
            for oid in sorted(chosen)]


def objective_text(obj: dict[str, Any]) -> str:
    d = OBJECTIVES[obj["id"]]
    text = d.description
    p = obj["params"]
    if "target" in p and obj["id"] == "OBJ-HYG":
        text += f" Cible : {p['target']:.0%}."
    if "max" in p:
        text += f" Plafond : {p['max']:,.0f} €.".replace(",", " ")
    return text


# =============================================================================
# Comité de direction trimestriel
# =============================================================================
BOARD_OPTIONS = {
    "rallonge": "Demander une rallonge budgétaire",
    "recrutement": "Demander le recrutement d'un analyste SSI",
    "exercice": "Proposer un exercice de crise avec le comité",
    "bilan": "Présenter le bilan sans demande particulière",
}


def board_probability(sim: "Simulation", option: str) -> float:
    lenient = sim.difficulty.board_leniency
    trust = sim.trust / 100.0
    level, _ = sim.global_risk()
    if option == "rallonge":
        p = lenient * (0.5 + 0.5 * trust)
        if sim.risk.study.complete:
            p += 0.15       # demande argumentée par une analyse de risques
        if level >= 12:
            p += 0.10       # risque critique documenté
        if sim.budget_flags.get("major_incidents"):
            p += 0.10
        p -= 0.10 * sim.board_state.get("rallonges_annee", 0)
        return max(0.05, min(0.95, p))
    if option == "recrutement":
        p = lenient * trust + (0.25 if sim.team.state.overload_weeks >= 3 else 0.0)
        if sim.board_state.get("recrutements_annee", 0):
            p -= 0.3
        return max(0.05, min(0.9, p))
    return 1.0


def board_amount(sim: "Simulation") -> float:
    return round(0.15 * sim.org.budget_ssi * sim.difficulty.budget_mult, -3)
