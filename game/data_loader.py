"""Chargement centralisé des référentiels (YAML / JSON embarqués)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

import config
from game.event_engine import GameEvent, load_events
from game.incident_engine import IncidentTemplate, load_incident_templates
from game.measures import Measure, load_catalogue
from game.operations import Campaign, VulnDef, load_campaigns, load_vulns
from game.organisation import Organisation, load_organisations
from game.risk_engine import RiskReferential


def load_yaml(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_json(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class GameData:
    organisations: dict[str, Organisation]
    incidents: dict[str, IncidentTemplate]
    measures: dict[str, Measure]
    events: dict[str, GameEvent]
    referential: RiskReferential
    iso_controls: list[dict[str, str]]
    mitre: dict[str, dict[str, str]]
    threats: dict[str, Any]
    regulations: dict[str, Any]
    vulns: dict[str, VulnDef]
    campaigns: dict[str, Campaign]

    @classmethod
    def load(cls, root: Path | None = None) -> "GameData":
        root = Path(root) if root else config.ROOT_DIR
        scen, data = root / "scenarios", root / "data"
        risk_raw = load_yaml(data / "threats" / "sources_risque.yaml")
        hygiene_raw = load_yaml(data / "regulations" / "hygiene_anssi_42.yaml")
        iso_raw = load_yaml(data / "regulations" / "iso27001_2022_annexe_a.yaml")
        iso_controls = [
            {"id": str(c["id"]), "titre": c["titre"], "theme": theme["nom"]}
            for theme in iso_raw["themes"] for c in theme["controles"]
        ]
        return cls(
            organisations=load_organisations(scen / "organisations"),
            incidents=load_incident_templates(scen / "incidents"),
            measures=load_catalogue(data / "measures" / "catalogue.yaml"),
            events=load_events(scen / "events"),
            referential=RiskReferential.from_dicts(risk_raw, hygiene_raw),
            iso_controls=iso_controls,
            mitre={t["id"]: t for t in load_json(data / "threats" / "mitre_attack.json")["techniques"]},
            threats=load_json(data / "threats" / "anssi_panorama_2024.json"),
            regulations=load_yaml(data / "regulations" / "obligations.yaml"),
            vulns=load_vulns(data / "threats" / "vulnerabilites.yaml"),
            campaigns=load_campaigns(data / "threats" / "campagnes.yaml"),
        )


_CACHE: dict[str, GameData] = {}


def get_data(root: Path | None = None) -> GameData:
    key = str(root or config.ROOT_DIR)
    if key not in _CACHE:
        _CACHE[key] = GameData.load(root)
    return _CACHE[key]
