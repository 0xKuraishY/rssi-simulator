"""Événements hebdomadaires hors incident (alertes CERT-FR, vie de l'organisation, réglementaire)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from game.organisation import Organisation

MAX_EVENTS_PER_YEAR = 10


@dataclass(frozen=True)
class EventChoice:
    id: str
    texte: str
    qualite: str
    effets: dict[str, Any]
    feedback: str = ""
    reference: str = ""


@dataclass(frozen=True)
class GameEvent:
    id: str
    titre: str
    description: str
    categorie: str
    choix: list[EventChoice]
    de: str = ""
    probabilite_semaine: float = 0.01
    organisations: list[str] = field(default_factory=list)
    unique: bool = True
    annee_min: int = 1
    tour_min: int = 1

    def applies_to(self, org: "Organisation") -> bool:
        return not self.organisations or org.id in self.organisations

    def choice(self, choice_id: str) -> EventChoice:
        for c in self.choix:
            if c.id == choice_id:
                return c
        raise KeyError(f"Choix {choice_id} inconnu pour {self.id}")

    @classmethod
    def from_dict(cls, d: dict[str, Any], categorie: str) -> "GameEvent":
        return cls(
            id=d["id"], titre=d["titre"], description=str(d.get("description", "")).strip(),
            categorie=d.get("categorie", categorie), de=d.get("de", ""),
            probabilite_semaine=float(d.get("probabilite_semaine", 0.01)),
            organisations=list(d.get("organisations") or []), unique=bool(d.get("unique", True)),
            annee_min=int(d.get("annee_min", 1)), tour_min=int(d.get("tour_min", 1)),
            choix=[EventChoice(str(c["id"]), c["texte"], c.get("qualite", "moyenne"), dict(c.get("effets") or {}),
                               str(c.get("feedback", "")).strip(), str(c.get("reference", "")))
                   for c in d["choix"]],
        )


def load_events(directory: Path) -> dict[str, GameEvent]:
    events: dict[str, GameEvent] = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        for d in data["evenements"]:
            ev = GameEvent.from_dict(d, data.get("categorie", path.stem))
            events[ev.id] = ev
    return events


class EventEngine:
    def __init__(self, org: "Organisation", events: dict[str, GameEvent], rng: random.Random) -> None:
        self.org = org
        self.events = {k: e for k, e in events.items() if e.applies_to(org)}
        self.rng = rng
        self.seen: list[str] = []
        self.per_year: dict[int, int] = {}

    def roll(self, turn: int, year: int) -> GameEvent | None:
        if self.per_year.get(year, 0) >= MAX_EVENTS_PER_YEAR:
            return None
        for ev in sorted(self.events.values(), key=lambda e: e.id):
            if ev.unique and ev.id in self.seen:
                continue
            if year < ev.annee_min or turn < ev.tour_min:
                continue
            if self.rng.random() < ev.probabilite_semaine:
                self.seen.append(ev.id)
                self.per_year[year] = self.per_year.get(year, 0) + 1
                return ev
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"seen": list(self.seen), "per_year": {str(k): v for k, v in self.per_year.items()}}

    def load_dict(self, d: dict[str, Any]) -> None:
        self.seen = list(d.get("seen", []))
        self.per_year = {int(k): int(v) for k, v in d.get("per_year", {}).items()}
