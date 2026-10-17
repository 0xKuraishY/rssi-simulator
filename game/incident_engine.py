"""Moteur d'incidents : déclenchement probabiliste, timeline en 7 phases, décisions.

Timeline d'un incident :
  1. Compromission initiale (invisible)    — tour de départ
  2. Latence / propagation (invisible)      — jusqu'au tour de détection
  3. Détection (visible → salle de crise)   — horloge de crise H+0
  4. Confinement  ┐
  5. Éradication  ├ décisions du joueur, horodatées H+n
  6. Reprise      ┘ puis reprise opérationnelle sur plusieurs semaines
  7. Retour d'expérience (rapport)          — à la clôture
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml

from game.organisation import INCIDENT_TYPES, Organisation


class Phase(IntEnum):
    COMPROMISSION = 1
    LATENCE = 2
    DETECTION = 3
    CONFINEMENT = 4
    ERADICATION = 5
    REPRISE = 6
    REX = 7
    CLOS = 8


PHASE_LABELS = {
    Phase.COMPROMISSION: "Compromission initiale",
    Phase.LATENCE: "Latence / propagation",
    Phase.DETECTION: "Détection",
    Phase.CONFINEMENT: "Confinement",
    Phase.ERADICATION: "Éradication",
    Phase.REPRISE: "Reprise",
    Phase.REX: "Retour d'expérience",
    Phase.CLOS: "Clos",
}
PHASE_BY_NAME = {
    "detection": Phase.DETECTION, "confinement": Phase.CONFINEMENT,
    "eradication": Phase.ERADICATION, "reprise": Phase.REPRISE, "rex": Phase.REX,
}
QUALITIES = ("bonne", "moyenne", "mauvaise")
GRACE_TURNS = 3            # aucune compromission pendant les premières semaines (prise en main)
MAX_OPEN_INCIDENTS = 2
UNDETECTED_COST_PER_WEEK = 0.02
UNDETECTED_COST_CAP = 1.5


class IncidentError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Modèle de données (YAML)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Choice:
    id: str
    texte: str
    qualite: str
    effets: dict[str, Any]
    feedback: str = ""
    reference: str = ""
    defaut: bool = False


@dataclass(frozen=True)
class Decision:
    id: str
    heure: int
    phase: Phase
    texte: str
    choix: list[Choice]
    urgence: bool = False
    delai_secondes: int = 90
    de: str = "Cellule de crise"

    def choice(self, choice_id: str) -> Choice:
        for c in self.choix:
            if c.id == choice_id:
                return c
        raise IncidentError(f"Choix {choice_id} inconnu pour la décision {self.id}")

    @property
    def default_choice(self) -> Choice:
        for c in self.choix:
            if c.defaut:
                return c
        return max(self.choix, key=lambda c: QUALITIES.index(c.qualite))


@dataclass(frozen=True)
class IncidentTemplate:
    id: str
    type: str
    title: str
    description: str
    based_on: str
    cve_references: list[dict[str, str]]
    initial_vector: str
    attack_chain: list[str]
    impact: dict[str, int]
    cout_min: float
    cout_max: float
    duree_semaines: dict[str, int]
    phase_detection_semaines: dict[str, int]
    obligations_declenchees: list[str]
    decisions: list[Decision]
    organisations: list[str] = field(default_factory=list)
    messages: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    mesures_cles: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    rex: str = ""
    donnees_personnelles: bool = False
    impact_reputation: dict[str, int] = field(default_factory=dict)

    def applies_to(self, org: Organisation) -> bool:
        if self.organisations and org.id not in self.organisations:
            return False
        return org.base_probability(self.type) > 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IncidentTemplate":
        for key in ("id", "type", "title", "impact", "cout_min", "cout_max", "decisions"):
            if key not in d:
                raise IncidentError(f"{d.get('id', '?')} : champ « {key} » manquant")
        if d["type"] not in INCIDENT_TYPES:
            raise IncidentError(f"{d['id']} : type inconnu {d['type']}")
        if float(d["cout_min"]) > float(d["cout_max"]):
            raise IncidentError(f"{d['id']} : cout_min > cout_max")
        if not 3 <= len(d["decisions"]) <= 5:
            raise IncidentError(f"{d['id']} : 3 à 5 décisions attendues")
        decisions = []
        for dec in d["decisions"]:
            choices = [
                Choice(
                    id=str(c["id"]), texte=c["texte"], qualite=c.get("qualite", "moyenne"),
                    effets=dict(c.get("effets") or {}), feedback=str(c.get("feedback", "")).strip(),
                    reference=str(c.get("reference", "")), defaut=bool(c.get("defaut", False)),
                )
                for c in dec["choix"]
            ]
            if any(c.qualite not in QUALITIES for c in choices):
                raise IncidentError(f"{d['id']}/{dec['id']} : qualité invalide")
            decisions.append(Decision(
                id=str(dec["id"]), heure=int(dec["heure"]),
                phase=PHASE_BY_NAME.get(dec.get("phase", "confinement"), Phase.CONFINEMENT),
                texte=str(dec["texte"]).strip(), choix=choices, urgence=bool(dec.get("urgence", False)),
                delai_secondes=int(dec.get("delai_secondes", 90)), de=dec.get("de", "Cellule de crise"),
            ))
        decisions.sort(key=lambda x: x.heure)
        return cls(
            id=d["id"], type=d["type"], title=d["title"], description=str(d.get("description", "")).strip(),
            based_on=str(d.get("based_on", "")), cve_references=list(d.get("cve_references") or []),
            initial_vector=str(d.get("initial_vector", "")), attack_chain=list(d.get("attack_chain") or []),
            impact={k: int(v) for k, v in d["impact"].items()},
            cout_min=float(d["cout_min"]), cout_max=float(d["cout_max"]),
            duree_semaines=dict(d.get("duree_semaines") or {"min": 1, "max": 4}),
            phase_detection_semaines=dict(d.get("phase_detection_semaines") or {"min": 0, "max": 4}),
            obligations_declenchees=list(d.get("obligations_declenchees") or []),
            decisions=decisions, organisations=list(d.get("organisations") or []),
            messages=dict(d.get("messages") or {}), mesures_cles=list(d.get("mesures_cles") or []),
            references=list(d.get("references") or []), rex=str(d.get("rex", "")).strip(),
            donnees_personnelles=bool(d.get("donnees_personnelles", False)),
            impact_reputation={k: int(v) for k, v in (d.get("impact_reputation") or {}).items()},
        )


def load_incident_templates(directory: Path) -> dict[str, IncidentTemplate]:
    templates = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            t = IncidentTemplate.from_dict(yaml.safe_load(fh))
        templates[t.id] = t
    return templates


# ---------------------------------------------------------------------------
# Incident en cours
# ---------------------------------------------------------------------------
@dataclass
class ActiveIncident:
    uid: str
    template_id: str
    start_turn: int
    detection_turn: int
    base_cost: float
    recovery_weeks: int
    impact_reduction: float = 0.0
    phase: int = Phase.COMPROMISSION
    crisis_hour: int = 0
    decisions_taken: list[dict[str, Any]] = field(default_factory=list)
    cost_mult: float = 1.0
    cost_fixed: float = 0.0
    extra_weeks: int = 0
    triggered: list[str] = field(default_factory=list)
    recovery_end_turn: int | None = None
    closed_turn: int | None = None
    final_cost: float | None = None

    @property
    def detected(self) -> bool:
        return self.phase >= Phase.DETECTION

    @property
    def in_crisis(self) -> bool:
        """Détecté, salle de crise non encore levée."""
        return self.detected and self.recovery_end_turn is None and self.phase != Phase.CLOS

    @property
    def closed(self) -> bool:
        return self.phase == Phase.CLOS

    @property
    def undetected_weeks(self) -> int:
        return max(0, self.detection_turn - self.start_turn)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActiveIncident":
        return cls(**d)


class IncidentEngine:
    def __init__(self, org: Organisation, templates: dict[str, IncidentTemplate], rng: random.Random,
                 grace_turns: int = GRACE_TURNS, max_open: int = MAX_OPEN_INCIDENTS, cost_mult: float = 1.0) -> None:
        self.org = org
        self.grace_turns = grace_turns
        self.max_open = max_open
        self.cost_mult = cost_mult
        self.templates = {k: t for k, t in templates.items() if t.applies_to(org)}
        self.rng = rng
        self.incidents: list[ActiveIncident] = []
        self._counter = 0

    # -- accès -----------------------------------------------------------------
    def template(self, incident: ActiveIncident | str) -> IncidentTemplate:
        tid = incident if isinstance(incident, str) else incident.template_id
        return self.templates[tid]

    def get(self, uid: str) -> ActiveIncident:
        for inc in self.incidents:
            if inc.uid == uid:
                return inc
        raise IncidentError(f"Incident {uid} introuvable")

    def open_incidents(self) -> list[ActiveIncident]:
        return [i for i in self.incidents if not i.closed]

    def crises(self) -> list[ActiveIncident]:
        """Incidents détectés dont la gestion de crise n'est pas terminée."""
        return [i for i in self.incidents if i.in_crisis]

    def closed_incidents(self) -> list[ActiveIncident]:
        return [i for i in self.incidents if i.closed]

    def template_for_type(self, incident_type: str) -> IncidentTemplate | None:
        for t in self.templates.values():
            if t.type == incident_type:
                return t
        return None

    # -- création ----------------------------------------------------------------
    def sample_cost(self, template: IncidentTemplate) -> float:
        span = template.cout_max - template.cout_min
        raw = template.cout_min + span * self.org.facteur_cout * self.rng.uniform(0.6, 1.4)
        return round(max(template.cout_min, min(template.cout_max, raw)), -2)

    def start(self, template_id: str, turn: int, detection_factor: float = 1.0,
              impact_reduction: float = 0.0) -> ActiveIncident:
        t = self.templates.get(template_id)
        if t is None:
            raise IncidentError(f"Scénario {template_id} non applicable à {self.org.id}")
        lo = int(t.phase_detection_semaines.get("min", 0))
        hi = int(t.phase_detection_semaines.get("max", lo))
        delay = int(round(self.rng.randint(lo, max(lo, hi)) * max(0.0, detection_factor)))
        dmin, dmax = int(t.duree_semaines.get("min", 1)), int(t.duree_semaines.get("max", 1))
        self._counter += 1
        incident = ActiveIncident(
            uid=f"{t.id}#{self._counter}",
            template_id=t.id,
            start_turn=turn,
            detection_turn=turn + delay,
            base_cost=self.sample_cost(t),
            recovery_weeks=self.rng.randint(dmin, max(dmin, dmax)),
            impact_reduction=impact_reduction,
            triggered=list(t.obligations_declenchees),
        )
        self.incidents.append(incident)
        return incident

    def can_open(self, incident_type: str | None = None) -> bool:
        """Un nouvel incident peut-il démarrer (plafond d'incidents ouverts, type déjà en cours) ?"""
        if len(self.open_incidents()) >= self.max_open:
            return False
        return incident_type is None or incident_type not in {self.template(i).type for i in self.open_incidents()}

    def roll(self, turn: int, weekly_probability: dict[str, float]) -> str | None:
        """Tire au plus un nouvel incident pour le tour. Renvoie l'id du scénario."""
        if turn <= self.grace_turns or len(self.open_incidents()) >= self.max_open:
            return None
        busy_types = {self.template(i).type for i in self.open_incidents()}
        candidates = [t for t in self.templates.values() if t.type not in busy_types]
        self.rng.shuffle(candidates)
        for t in sorted(candidates, key=lambda x: x.id):
            p = weekly_probability.get(t.type, 0.0)
            if p > 0 and self.rng.random() < p:
                return t.id
        return None

    # -- progression hebdomadaire -------------------------------------------------
    def advance(self, turn: int) -> dict[str, list[ActiveIncident]]:
        """Fait progresser les incidents. Renvoie les incidents détectés / clos ce tour."""
        detected, closed = [], []
        for inc in self.incidents:
            if inc.phase in (Phase.COMPROMISSION, Phase.LATENCE):
                if turn >= inc.detection_turn:
                    inc.phase = Phase.DETECTION
                    inc.crisis_hour = 0
                    detected.append(inc)
                elif turn > inc.start_turn:
                    inc.phase = Phase.LATENCE
            elif inc.recovery_end_turn is not None and not inc.closed and turn >= inc.recovery_end_turn:
                inc.phase = Phase.CLOS
                inc.closed_turn = turn
                closed.append(inc)
        return {"detected": detected, "closed": closed}

    # -- décisions de crise --------------------------------------------------------
    def pending_decision(self, incident: ActiveIncident) -> Decision | None:
        taken = {d["decision_id"] for d in incident.decisions_taken}
        for dec in self.template(incident).decisions:
            if dec.id not in taken:
                return dec
        return None

    def decide(self, incident: ActiveIncident, decision_id: str, choice_id: str) -> Choice:
        if not incident.in_crisis:
            raise IncidentError("Aucune décision attendue pour cet incident")
        decision = self.pending_decision(incident)
        if decision is None or decision.id != decision_id:
            raise IncidentError(f"La décision attendue n'est pas {decision_id}")
        choice = decision.choice(choice_id)
        effects = choice.effets
        incident.crisis_hour = max(incident.crisis_hour, decision.heure)
        incident.cost_mult *= float(effects.get("cout_mult", 1.0))
        incident.cost_fixed += float(effects.get("cout_fixe", 0.0))
        incident.extra_weeks += int(effects.get("duree_semaines", 0))
        for obligation in effects.get("declenche", []) or []:
            if obligation not in incident.triggered:
                incident.triggered.append(obligation)
        incident.decisions_taken.append({
            "decision_id": decision.id, "choice_id": choice.id, "hour": decision.heure,
            "quality": choice.qualite,
        })
        nxt = self.pending_decision(incident)
        if nxt is not None:
            incident.phase = max(Phase.CONFINEMENT, nxt.phase)
        else:
            incident.phase = max(Phase.CONFINEMENT, decision.phase)
        return choice

    def compute_final_cost(self, incident: ActiveIncident) -> float:
        lateness = min(UNDETECTED_COST_CAP, 1.0 + UNDETECTED_COST_PER_WEEK * incident.undetected_weeks)
        cost = (incident.base_cost * incident.cost_mult * lateness + incident.cost_fixed) * self.cost_mult
        cost *= (1.0 - incident.impact_reduction)
        return round(max(0.0, cost), -2)

    def end_crisis(self, incident: ActiveIncident, turn: int) -> float:
        """Toutes les décisions sont prises : la reprise opérationnelle commence."""
        if self.pending_decision(incident) is not None:
            raise IncidentError("Des décisions restent à prendre")
        weeks = max(1, round((incident.recovery_weeks + incident.extra_weeks) * (1 - 0.5 * incident.impact_reduction)))
        incident.recovery_end_turn = turn + weeks
        incident.phase = Phase.REPRISE
        incident.crisis_hour = max(incident.crisis_hour, 168)
        incident.final_cost = self.compute_final_cost(incident)
        return incident.final_cost

    def decision_quality(self, incident: ActiveIncident) -> float:
        if not incident.decisions_taken:
            return 0.0
        scores = {"bonne": 1.0, "moyenne": 0.5, "mauvaise": 0.0}
        return sum(scores[d["quality"]] for d in incident.decisions_taken) / len(incident.decisions_taken)

    # -- sérialisation --------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {"counter": self._counter, "incidents": [i.to_dict() for i in self.incidents]}

    def load_dict(self, data: dict[str, Any]) -> None:
        self._counter = int(data.get("counter", 0))
        self.incidents = [ActiveIncident.from_dict(d) for d in data.get("incidents", [])
                          if d.get("template_id") in self.templates]
