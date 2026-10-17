"""Modèle d'organisation (archétype jouable) chargé depuis YAML."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

INCIDENT_TYPES = (
    "ransomware",
    "phishing",
    "fuite_donnees",
    "supply_chain",
    "vpn_exploit",
    "ddos",
    "initie",
    "double_extorsion",
    "compromission_cloud",
    "ot_iot",
)

INCIDENT_TYPE_LABELS = {
    "ransomware": "Rançongiciel",
    "phishing": "Hameçonnage / fraude",
    "fuite_donnees": "Fuite de données",
    "supply_chain": "Chaîne d'approvisionnement",
    "vpn_exploit": "Exploitation VPN",
    "ddos": "Déni de service (DDoS)",
    "initie": "Initié malveillant",
    "double_extorsion": "Double extorsion",
    "compromission_cloud": "Compromission cloud / M365",
    "ot_iot": "Attaque OT / IoT",
}

DIFFICULTY_LABELS = {1: "Débutant", 2: "Intermédiaire", 3: "Confirmé", 4: "Avancé", 5: "Expert"}

REQUIRED_FIELDS = (
    "id", "nom", "secteur", "taille_employes", "budget_it", "budget_ssi",
    "contraintes_reglementaires", "assets_critiques", "probabilites_incidents",
    "description", "difficulte",
)


class OrganisationError(ValueError):
    pass


@dataclass(frozen=True)
class Asset:
    id: str
    nom: str
    type: str
    criticite: str  # "primaire" | "secondaire"
    dict_besoins: dict[str, int]
    description: str = ""


@dataclass(frozen=True)
class Regimes:
    rgpd: bool = True
    nis2: str | None = None  # "essentielle" | "importante" | None
    hds: bool = False
    lpm_oiv: bool = False
    iso27001: bool = False   # certification en cours / exigée

    @property
    def labels(self) -> list[str]:
        out = ["RGPD"] if self.rgpd else []
        if self.nis2:
            out.append(f"NIS2 ({'Essentielle' if self.nis2 == 'essentielle' else 'Importante'})")
        if self.hds:
            out.append("HDS")
        if self.lpm_oiv:
            out.append("LPM / OIV")
        if self.iso27001:
            out.append("ISO 27001")
        return out


@dataclass(frozen=True)
class Organisation:
    id: str
    nom: str
    secteur: str
    taille_employes: int
    budget_it: float
    budget_ssi: float
    chiffre_affaires: float
    contraintes_reglementaires: list[str]
    regimes: Regimes
    assets_critiques: list[Asset]
    valeurs_metier: list[str]
    probabilites_incidents: dict[str, float]
    description: str
    difficulte: int
    enjeux: list[str] = field(default_factory=list)
    postes_travail: int = 0
    equipe_ssi: int = 1
    facteur_cout: float = 0.3
    traitement_grande_echelle: bool = False
    socle_hygiene: list[int] = field(default_factory=list)
    mesures_initiales: list[str] = field(default_factory=list)
    iso_avancement_initial: int = 0
    exposition: dict[str, int] = field(default_factory=dict)
    contrat_majeur: str = "Contrat client majeur"
    plafond_assurance: float = 1_000_000
    repartition_budget: dict[str, float] = field(default_factory=dict)
    type_label: str = ""
    taux_clic_initial: float = 0.20

    # -- propriétés métier ---------------------------------------------------
    @property
    def dpo_required(self) -> bool:
        """Règle de jeu (cf. docs/METHODOLOGIE.md) : >250 employés OU grande échelle.

        NB : en droit (RGPD art. 37), le DPO est obligatoire pour tout organisme
        public et pour les traitements à grande échelle de données sensibles ;
        le seuil de 250 salariés est une simplification pédagogique.
        """
        return self.taille_employes > 250 or self.traitement_grande_echelle

    @property
    def difficulty_label(self) -> str:
        return DIFFICULTY_LABELS.get(self.difficulte, str(self.difficulte))

    @property
    def endpoints(self) -> int:
        return self.postes_travail or self.taille_employes

    def base_probability(self, incident_type: str) -> float:
        return float(self.probabilites_incidents.get(incident_type, 0.0))

    # -- chargement ------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Organisation":
        missing = [f for f in REQUIRED_FIELDS if f not in data]
        if missing:
            raise OrganisationError(f"Champs manquants : {', '.join(missing)}")
        if not 1 <= int(data["difficulte"]) <= 5:
            raise OrganisationError("difficulte doit être comprise entre 1 et 5")
        if float(data["budget_ssi"]) <= 0:
            raise OrganisationError("budget_ssi doit être positif")
        unknown = set(data["probabilites_incidents"]) - set(INCIDENT_TYPES)
        if unknown:
            raise OrganisationError(f"Types d'incident inconnus : {sorted(unknown)}")
        for key, p in data["probabilites_incidents"].items():
            if not 0 <= float(p) <= 1:
                raise OrganisationError(f"Probabilité hors [0,1] pour {key}")
        for key in ("enjeux", "valeurs_metier", "contraintes_reglementaires"):
            if any(not isinstance(x, str) for x in data.get(key, []) or []):
                raise OrganisationError(f"« {key} » doit être une liste de chaînes (guillemets YAML ?)")
        reg = data.get("regimes", {}) or {}
        assets = [
            Asset(
                id=a["id"], nom=a["nom"], type=a.get("type", ""),
                criticite=a.get("criticite", "secondaire"),
                dict_besoins={k: int(v) for k, v in (a.get("dict") or {}).items()},
                description=a.get("description", ""),
            )
            for a in data["assets_critiques"]
        ]
        return cls(
            id=str(data["id"]),
            nom=str(data["nom"]),
            secteur=str(data["secteur"]),
            taille_employes=int(data["taille_employes"]),
            budget_it=float(data["budget_it"]),
            budget_ssi=float(data["budget_ssi"]),
            chiffre_affaires=float(data.get("chiffre_affaires", data["budget_it"] * 20)),
            contraintes_reglementaires=list(data["contraintes_reglementaires"]),
            regimes=Regimes(
                rgpd=bool(reg.get("rgpd", True)),
                nis2=reg.get("nis2"),
                hds=bool(reg.get("hds", False)),
                lpm_oiv=bool(reg.get("lpm_oiv", False)),
                iso27001=bool(reg.get("iso27001", False)),
            ),
            assets_critiques=assets,
            valeurs_metier=list(data.get("valeurs_metier", [])),
            probabilites_incidents={k: float(v) for k, v in data["probabilites_incidents"].items()},
            description=str(data["description"]).strip(),
            difficulte=int(data["difficulte"]),
            enjeux=list(data.get("enjeux", [])),
            postes_travail=int(data.get("postes_travail", 0)),
            equipe_ssi=int(data.get("equipe_ssi", 1)),
            facteur_cout=float(data.get("facteur_cout", 0.3)),
            traitement_grande_echelle=bool(data.get("traitement_grande_echelle", False)),
            socle_hygiene=[int(x) for x in data.get("socle_hygiene", [])],
            mesures_initiales=list(data.get("mesures_initiales", [])),
            iso_avancement_initial=int(data.get("iso_avancement_initial", 0)),
            exposition={k: int(v) for k, v in (data.get("exposition") or {}).items()},
            contrat_majeur=str(data.get("contrat_majeur", "Contrat client majeur")),
            plafond_assurance=float(data.get("plafond_assurance", 1_000_000)),
            repartition_budget={k: float(v) for k, v in (data.get("repartition_budget") or {}).items()},
            type_label=str(data.get("type_label", data["nom"])),
            taux_clic_initial=float(data.get("taux_clic_initial", 0.20)),
        )


def load_organisation(path: Path) -> Organisation:
    with Path(path).open(encoding="utf-8") as fh:
        return Organisation.from_dict(yaml.safe_load(fh))


def load_organisations(directory: Path) -> dict[str, Organisation]:
    orgs = [load_organisation(p) for p in sorted(Path(directory).glob("*.yaml"))]
    orgs.sort(key=lambda o: (o.difficulte, o.nom))
    return {o.id: o for o in orgs}
