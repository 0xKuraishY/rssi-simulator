"""Catalogue des mesures de sécurité et portefeuille de mesures déployées."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

import yaml

if TYPE_CHECKING:
    from game.organisation import Organisation

MEASURE_TYPES = ("prevention", "detection", "reponse", "gouvernance")
MAX_COMBINED_REDUCTION = 0.9


def combine_reductions(values: Iterable[float], cap: float = MAX_COMBINED_REDUCTION) -> float:
    """Combinaison multiplicative de coefficients de réduction indépendants :
    1 - Π(1 - r_i), plafonnée (aucune mesure ne supprime totalement un risque)."""
    remaining = 1.0
    for r in values:
        remaining *= 1.0 - max(0.0, min(1.0, float(r)))
    return min(cap, 1.0 - remaining)


def _clamp(value: float, lo: float | None, hi: float | None) -> float:
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


@dataclass(frozen=True)
class Measure:
    id: str
    nom: str
    categorie: str
    type: str
    description: str
    controle_iso: list[str]
    guide_anssi: str
    cout_deploiement: float
    delai_semaines: int
    maintenance_annuelle: float
    reduction_risque: dict[str, float]
    reduction_impact: dict[str, float] = field(default_factory=dict)
    detection: float = 0.0
    hygiene: list[int] = field(default_factory=list)
    conformite: list[str] = field(default_factory=list)
    prerequis: list[str] = field(default_factory=list)
    cout_par_employe: float = 0.0
    cout_par_poste: float = 0.0
    cout_par_membre_ssi: float = 0.0
    cout_min: float | None = None
    cout_max: float | None = None
    maintenance_par_employe: float = 0.0
    maintenance_par_poste: float = 0.0
    maintenance_min: float | None = None
    maintenance_max: float | None = None
    assurance: bool = False

    def deployment_cost(self, org: "Organisation") -> float:
        raw = (self.cout_deploiement + self.cout_par_employe * org.taille_employes
               + self.cout_par_poste * org.endpoints + self.cout_par_membre_ssi * org.equipe_ssi)
        return round(_clamp(raw, self.cout_min, self.cout_max))

    def annual_cost(self, org: "Organisation") -> float:
        raw = (self.maintenance_annuelle + self.maintenance_par_employe * org.taille_employes
               + self.maintenance_par_poste * org.endpoints)
        return round(_clamp(raw, self.maintenance_min, self.maintenance_max)) if raw else 0.0

    def reduction_for(self, incident_type: str) -> float:
        return float(self.reduction_risque.get(incident_type, self.reduction_risque.get("tous", 0.0)))

    def impact_reduction_for(self, incident_type: str) -> float:
        return float(self.reduction_impact.get(incident_type, self.reduction_impact.get("tous", 0.0)))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Measure":
        iso = d.get("controle_iso", [])
        return cls(
            id=d["id"],
            nom=d["nom"],
            categorie=d.get("categorie", "outils"),
            type=d.get("type", "prevention"),
            description=str(d.get("description", "")).strip(),
            controle_iso=[str(x) for x in (iso if isinstance(iso, list) else [iso])],
            guide_anssi=str(d.get("guide_anssi", "")),
            cout_deploiement=float(d.get("cout_deploiement", 0)),
            delai_semaines=int(d.get("delai_semaines", 1)),
            maintenance_annuelle=float(d.get("maintenance_annuelle", 0)),
            reduction_risque={k: float(v) for k, v in (d.get("reduction_risque") or {}).items()},
            reduction_impact={k: float(v) for k, v in (d.get("reduction_impact") or {}).items()},
            detection=float(d.get("detection", 0.0)),
            hygiene=[int(x) for x in d.get("hygiene", [])],
            conformite=list(d.get("conformite", [])),
            prerequis=list(d.get("prerequis", [])),
            cout_par_employe=float(d.get("cout_par_employe", 0)),
            cout_par_poste=float(d.get("cout_par_poste", 0)),
            cout_par_membre_ssi=float(d.get("cout_par_membre_ssi", 0)),
            cout_min=d.get("cout_min"),
            cout_max=d.get("cout_max"),
            maintenance_par_employe=float(d.get("maintenance_par_employe", 0)),
            maintenance_par_poste=float(d.get("maintenance_par_poste", 0)),
            maintenance_min=d.get("maintenance_min"),
            maintenance_max=d.get("maintenance_max"),
            assurance=bool(d.get("assurance", False)),
        )


def load_catalogue(path: Path) -> dict[str, Measure]:
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    items = data["mesures"] if isinstance(data, dict) else data
    return {m.id: m for m in (Measure.from_dict(x) for x in items)}


@dataclass
class MeasureStatus:
    measure_id: str
    ordered_turn: int
    ready_turn: int
    initial: bool = False   # socle existant, financé hors budget SSI
    suspended: bool = False

    def is_active(self, turn: int) -> bool:
        return not self.suspended and turn >= self.ready_turn


class MeasurePortfolio:
    """Mesures commandées / déployées par l'organisation."""

    def __init__(self, catalogue: dict[str, Measure]) -> None:
        self.catalogue = catalogue
        self.items: dict[str, MeasureStatus] = {}

    def add(self, measure_id: str, turn: int, initial: bool = False) -> MeasureStatus:
        if measure_id not in self.catalogue:
            raise KeyError(f"Mesure inconnue : {measure_id}")
        delay = 0 if initial else self.catalogue[measure_id].delai_semaines
        status = MeasureStatus(measure_id, turn, turn + delay, initial)
        self.items[measure_id] = status
        return status

    def has(self, measure_id: str) -> bool:
        return measure_id in self.items and not self.items[measure_id].suspended

    def active_ids(self, turn: int) -> list[str]:
        return [mid for mid, st in self.items.items() if st.is_active(turn)]

    def active(self, turn: int) -> list[Measure]:
        return [self.catalogue[mid] for mid in self.active_ids(turn)]

    def in_progress(self, turn: int) -> list[MeasureStatus]:
        return [st for st in self.items.values() if not st.suspended and turn < st.ready_turn]

    def newly_ready(self, turn: int) -> list[Measure]:
        return [self.catalogue[mid] for mid, st in self.items.items()
                if not st.suspended and not st.initial and st.ready_turn == turn]

    def suspend(self, measure_id: str) -> None:
        if measure_id in self.items:
            self.items[measure_id].suspended = True

    def resume(self, measure_id: str, turn: int) -> None:
        st = self.items.get(measure_id)
        if st is not None and st.suspended:
            st.suspended = False
            st.ready_turn = max(st.ready_turn, turn)

    def paid_ids(self) -> list[str]:
        """Mesures dont la maintenance est imputée au budget SSI."""
        return [mid for mid, st in self.items.items() if not st.initial and not st.suspended]

    def to_dict(self) -> dict[str, Any]:
        return {mid: vars(st).copy() for mid, st in self.items.items()}

    def load_dict(self, data: dict[str, Any]) -> None:
        self.items = {mid: MeasureStatus(**st) for mid, st in data.items() if mid in self.catalogue}
