"""Réputation sur 4 dimensions (0-100) et score global pondéré."""
from __future__ import annotations

from typing import Any

import config

DIMENSION_LABELS = {
    "utilisateurs": "Usagers / clients",
    "partenaires": "Partenaires",
    "regulateurs": "Régulateurs",
    "presse": "Presse",
}
RECOVERY_PER_WEEK = 0.25      # retour lent vers le niveau de départ
CONTRACT_RESET_MARGIN = 5     # le seuil doit être dépassé de 5 points pour « réarmer »


class ReputationEngine:
    def __init__(self, initial: dict[str, float] | None = None, weights: dict[str, float] | None = None,
                 recovery: float = RECOVERY_PER_WEEK) -> None:
        self.recovery = recovery
        self.initial = {k: float(v) for k, v in (initial or config.REPUTATION_INITIAL).items()}
        self.weights = dict(weights or config.REPUTATION_WEIGHTS)
        total = sum(self.weights.values())
        if total <= 0:
            raise ValueError("Pondérations de réputation invalides")
        self.weights = {k: v / total for k, v in self.weights.items()}
        self.values: dict[str, float] = {k: float(v) for k, v in self.initial.items()}
        self.history: list[tuple[int, float]] = []
        self.contract_lost_count = 0
        self._contract_armed = True

    @property
    def reputation(self) -> dict[str, float]:
        return self.values

    def global_score(self) -> float:
        return sum(self.values[k] * self.weights.get(k, 0) for k in self.values)

    def apply(self, deltas: dict[str, float]) -> dict[str, float]:
        applied = {}
        for dim, delta in (deltas or {}).items():
            if dim == "tous":
                for k in self.values:
                    applied[k] = applied.get(k, 0) + self._shift(k, delta)
            elif dim in self.values:
                applied[dim] = applied.get(dim, 0) + self._shift(dim, delta)
        return applied

    def _shift(self, dim: str, delta: float) -> float:
        before = self.values[dim]
        self.values[dim] = max(0.0, min(100.0, before + float(delta)))
        return self.values[dim] - before

    def weekly_update(self, turn: int) -> None:
        for k, v in self.values.items():
            target = self.initial.get(k, v)
            if v < target:
                self.values[k] = min(target, v + self.recovery)
        self.history.append((turn, round(self.global_score(), 2)))

    def is_game_over(self) -> bool:
        return self.global_score() < config.REPUTATION_GAME_OVER

    def check_contract_loss(self) -> bool:
        """Vrai une fois à chaque passage sous le seuil de perte de contrat."""
        score = self.global_score()
        if self._contract_armed and score < config.REPUTATION_CONTRACT_LOSS:
            self._contract_armed = False
            self.contract_lost_count += 1
            return True
        if not self._contract_armed and score >= config.REPUTATION_CONTRACT_LOSS + CONTRACT_RESET_MARGIN:
            self._contract_armed = True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {"values": dict(self.values), "history": [list(h) for h in self.history],
                "contract_lost_count": self.contract_lost_count, "armed": self._contract_armed}

    def load_dict(self, d: dict[str, Any]) -> None:
        self.values = {k: float(v) for k, v in d["values"].items()}
        self.history = [(int(t), float(s)) for t, s in d.get("history", [])]
        self.contract_lost_count = int(d.get("contract_lost_count", 0))
        self._contract_armed = bool(d.get("armed", True))
