"""Types d'état partagés : écrans, fil d'actualité, journal des décisions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class GameScreen(str, Enum):
    MENU = "MENU"
    ORG_SELECT = "ORG_SELECT"
    DASHBOARD = "DASHBOARD"
    INCIDENT = "INCIDENT"
    EBIOS = "EBIOS"
    AUDIT = "AUDIT"
    BUDGET = "BUDGET"
    GAME_OVER = "GAME_OVER"
    OPERATIONS = "OPERATIONS"
    LOBBY = "LOBBY"


class Severity(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"


class Quality(str, Enum):
    BONNE = "bonne"
    MOYENNE = "moyenne"
    MAUVAISE = "mauvaise"


QUALITY_SCORE = {Quality.BONNE.value: 1.0, Quality.MOYENNE.value: 0.5, Quality.MAUVAISE.value: 0.0}


@dataclass
class NewsItem:
    turn: int
    category: str  # incident | budget | conformite | reputation | evenement | mesure | ebios
    text: str
    severity: str = Severity.INFO.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NewsItem":
        return cls(**d)


@dataclass
class DecisionRecord:
    """Trace d'une décision du joueur, utilisée pour le rapport pédagogique."""

    turn: int
    source: str          # identifiant de l'incident ou de l'événement
    source_title: str
    question: str
    choice: str
    quality: str
    feedback: str = ""
    reference: str = ""
    impact_eur: float = 0.0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DecisionRecord":
        return cls(**d)


@dataclass
class Mistake:
    """Erreur critique détectée par le moteur (délai manqué, risque accepté…)."""

    turn: int
    title: str
    explanation: str
    reference: str
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Mistake":
        return cls(**d)
