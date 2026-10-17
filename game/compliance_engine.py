"""Conformité réglementaire : RGPD, NIS2, LPM/OIV, HDS, ISO 27001.

- Délais de notification suivis en heures à compter de la détection.
- Obligations permanentes (registre, DPO, formation…) suivies à la semaine.
- Contrôles simulés (CNIL, ANSSI, audit ISO) planifiés aléatoirement chaque année.

Les montants de sanction sont des modèles pédagogiques, proportionnés et bornés par
les plafonds légaux (cf. docs/METHODOLOGIE.md) — pas un barème officiel.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from game.organisation import Organisation

HOURS_PER_WEEK = 168


@dataclass(frozen=True)
class ObligationDef:
    key: str
    label: str
    hours: int
    regime: str  # rgpd | nis2 | lpm_oiv | hds | assurance | tous
    reference: str
    authority: str


OBLIGATIONS: dict[str, ObligationDef] = {o.key: o for o in (
    ObligationDef("nis2_24h", "Alerte précoce à l'ANSSI (24 h)", 24, "nis2",
                  "Directive (UE) 2022/2555 (NIS2), art. 23 §4 a)", "ANSSI"),
    ObligationDef("lpm_24h", "Déclaration d'incident OIV à l'ANSSI", 24, "lpm_oiv",
                  "Code de la défense, art. L.1332-6-2 (« sans délai », modélisé à 24 h)", "ANSSI"),
    ObligationDef("hds_signalement", "Signalement d'incident grave (ARS / CERT Santé)", 24, "hds",
                  "Code de la santé publique, art. L.1111-8-2 (« sans délai », modélisé à 24 h)", "ARS"),
    ObligationDef("cnil_72h", "Notification de violation à la CNIL (72 h)", 72, "rgpd",
                  "RGPD, art. 33", "CNIL"),
    ObligationDef("nis2_72h", "Notification d'incident à l'ANSSI (72 h)", 72, "nis2",
                  "Directive (UE) 2022/2555 (NIS2), art. 23 §4 b)", "ANSSI"),
    ObligationDef("plainte_72h", "Dépôt de plainte (condition de prise en charge assurance)", 72, "assurance",
                  "Code des assurances, art. L.12-10-1 (loi LOPMI 2023)", "Police / Gendarmerie"),
    ObligationDef("rgpd_art34", "Information des personnes concernées", 168, "rgpd",
                  "RGPD, art. 34 (« dans les meilleurs délais », modélisé à 7 jours)", "Personnes concernées"),
    ObligationDef("nis2_1mois", "Rapport final à l'ANSSI (1 mois)", 720, "nis2",
                  "Directive (UE) 2022/2555 (NIS2), art. 23 §4 d)", "ANSSI"),
)}


@dataclass(frozen=True)
class PermanentDef:
    key: str
    label: str
    regime: str
    reference: str
    action: str           # libellé de l'action proposée au joueur
    cost: float = 0.0     # coût de l'action (budget SSI), 0 si couvert par une mesure
    category: str = "divers"
    validity_weeks: int | None = None  # None : permanent une fois réalisé
    measure: str | None = None         # mesure du catalogue satisfaisant l'obligation


PERMANENT: dict[str, PermanentDef] = {p.key: p for p in (
    PermanentDef("registre", "Registre des traitements à jour", "rgpd", "RGPD, art. 30",
                 "Mettre à jour le registre (10 j·h/an)", 0.0, "divers", 52),
    PermanentDef("dpo", "Délégué à la protection des données désigné", "rgpd_dpo", "RGPD, art. 37-39",
                 "Désigner un DPO (mesure M39)", measure="M39"),
    PermanentDef("formation_rgpd", "Personnel formé au RGPD", "rgpd", "RGPD, art. 39 §1 b) et art. 32 §4",
                 "Former le personnel (mesure M02)", measure="M02"),
    PermanentDef("nis2_enregistrement", "Entité enregistrée auprès de l'ANSSI", "nis2",
                 "NIS2, art. 3 §3-4 et 27", "S'enregistrer auprès de l'ANSSI", 0.0, "divers"),
    PermanentDef("nis2_gouvernance", "Dirigeants formés à la cybersécurité", "nis2", "NIS2, art. 20 §2",
                 "Former le comité de direction", 4_000.0, "formation", 104),
    PermanentDef("nis2_analyse_risques", "Analyse de risques à jour (< 1 an)", "nis2", "NIS2, art. 21 §2 a)",
                 "Mener l'étude EBIOS RM (5 ateliers)"),
    PermanentDef("hds_hebergeur", "Hébergeur de données de santé certifié HDS vérifié", "hds",
                 "Code de la santé publique, art. L.1111-8", "Vérifier la certification HDS de l'hébergeur",
                 2_500.0, "audit", 52),
    PermanentDef("lpm_homologation", "SIIV homologués", "lpm_oiv",
                 "Arrêtés sectoriels LPM / Code de la défense, art. L.1332-6-1",
                 "Homologuer les SI d'importance vitale", 25_000.0, "audit", 156),
    PermanentDef("iso_certification", "Certification ISO/IEC 27001:2022 active", "iso27001",
                 "ISO/IEC 27001:2022, § 9.2-9.3", "Faire certifier le SMSI (mesure M38)", measure="M38"),
)}

ISO_SMSI_STEP_COST = 3_000.0
ISO_SMSI_STEP_CONTROLS = 5
ISO_PASS_THRESHOLD = 0.70


@dataclass
class Deadline:
    incident_uid: str
    kind: str
    status: str = "pending"  # pending | on_time | late | missed
    done_hour: int | None = None
    penalized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Inspection:
    kind: str     # cnil | anssi | iso
    turn: int
    done: bool = False
    result: str = ""


@dataclass
class ComplianceState:
    deadlines: list[Deadline] = field(default_factory=list)
    permanent: dict[str, int | None] = field(default_factory=dict)  # clé → tour de réalisation
    inspections: list[Inspection] = field(default_factory=list)
    iso_controls: list[str] = field(default_factory=list)
    iso_suspended_until: int | None = None
    on_time: int = 0
    late: int = 0
    missed: int = 0


class ComplianceEngine:
    def __init__(self, org: "Organisation", rng: random.Random, iso_controls: list[dict[str, str]]) -> None:
        self.org = org
        self.rng = rng
        self.iso_catalog = iso_controls  # 93 contrôles {id, titre, theme}
        self.state = ComplianceState()
        baseline = [c["id"] for c in iso_controls][: org.iso_avancement_initial]
        self.state.iso_controls = baseline

    # -- applicabilité ------------------------------------------------------------
    def regime_active(self, regime: str, insured: bool = False) -> bool:
        r = self.org.regimes
        return {
            "rgpd": r.rgpd,
            "rgpd_dpo": r.rgpd and self.org.dpo_required,
            "nis2": r.nis2 is not None,
            "lpm_oiv": r.lpm_oiv,
            "hds": r.hds,
            "iso27001": r.iso27001,
            "assurance": insured,
            "tous": True,
        }.get(regime, False)

    def applicable_obligations(self, kinds: list[str], insured: bool, personal_data: bool = True) -> list[str]:
        out = []
        for k in kinds:
            o = OBLIGATIONS.get(k)
            if o is None or not self.regime_active(o.regime, insured):
                continue
            if o.regime == "rgpd" and not personal_data:
                continue
            out.append(k)
        if insured and "plainte_72h" not in out:
            out.append("plainte_72h")
        return sorted(out, key=lambda k: OBLIGATIONS[k].hours)

    def applicable_permanent(self) -> list[PermanentDef]:
        return [p for p in PERMANENT.values() if self.regime_active(p.regime)]

    # -- délais de notification ---------------------------------------------------------
    def open_deadlines(self, incident_uid: str, kinds: list[str]) -> list[Deadline]:
        existing = {(d.incident_uid, d.kind) for d in self.state.deadlines}
        new = [Deadline(incident_uid, k) for k in kinds if (incident_uid, k) not in existing]
        self.state.deadlines.extend(new)
        return new

    def deadlines_for(self, incident_uid: str) -> list[Deadline]:
        return [d for d in self.state.deadlines if d.incident_uid == incident_uid]

    def pending_deadlines(self) -> list[Deadline]:
        return [d for d in self.state.deadlines if d.status in ("pending", "missed") and d.done_hour is None]

    def notify(self, incident_uid: str, kind: str, at_hour: int) -> Deadline:
        for d in self.state.deadlines:
            if d.incident_uid == incident_uid and d.kind == kind:
                if d.done_hour is not None:
                    return d
                d.done_hour = at_hour
                if at_hour <= OBLIGATIONS[kind].hours and d.status == "pending":
                    d.status = "on_time"
                    self.state.on_time += 1
                else:
                    if d.status == "pending":
                        self.state.missed += 1
                    d.status = "late"
                    self.state.late += 1
                return d
        raise KeyError(f"Aucune obligation {kind} ouverte pour {incident_uid}")

    def time_left(self, deadline: Deadline, current_hour: int) -> int:
        return OBLIGATIONS[deadline.kind].hours - current_hour

    def check_deadlines(self, incident_uid: str, current_hour: int) -> list[Deadline]:
        """Marque « missed » les obligations échues non réalisées. Renvoie les nouveaux manquements."""
        newly = []
        for d in self.deadlines_for(incident_uid):
            if d.status == "pending" and current_hour > OBLIGATIONS[d.kind].hours:
                d.status = "missed"
                self.state.missed += 1
                newly.append(d)
        return newly

    # -- sanctions (modèles pédagogiques) ----------------------------------------------------
    def cnil_fine(self, severity: int, sensitive: bool, delay_hours: int = 0) -> float:
        """Sanction CNIL modélisée : proportion du CA modulée par la gravité, la sensibilité
        des données et le retard ; plancher 15 000 €, plafond RGPD art. 83 §4 (2 % / 10 M€)
        pour un manquement à l'art. 33."""
        ca = self.org.chiffre_affaires
        amount = ca * 0.0003 * max(1, severity) * (1.5 if sensitive else 1.0)
        amount *= 1.0 + min(1.0, delay_hours / 168.0)
        cap = max(10_000_000.0, 0.02 * ca)
        return round(max(15_000.0, min(cap, amount)), -3)

    def nis2_fine(self, severity: int) -> float:
        """Fraction (0,5 % × gravité) du plafond NIS2 art. 34 : max(10 M€, 2 % CA) pour une
        entité essentielle, max(7 M€, 1,4 % CA) pour une entité importante."""
        ca = self.org.chiffre_affaires
        if self.org.regimes.nis2 == "essentielle":
            cap = max(10_000_000.0, 0.02 * ca)
        else:
            cap = max(7_000_000.0, 0.014 * ca)
        return round(max(20_000.0, cap * 0.005 * max(1, severity)), -3)

    def penalty_for(self, deadline: Deadline, severity: int, sensitive: bool) -> tuple[float, dict[str, float]]:
        """Renvoie (amende €, impact réputation) pour un manquement."""
        kind = deadline.kind
        if kind in ("cnil_72h", "rgpd_art34"):
            fine = self.cnil_fine(severity, sensitive) if kind == "cnil_72h" else 0.0
            return fine, {"regulateurs": -10, "utilisateurs": -4 if kind == "rgpd_art34" else -2}
        if kind == "nis2_24h":
            return 0.0, {"regulateurs": -6}  # manquement relevé, sanction portée par la notification 72 h
        if kind == "nis2_72h":
            return self.nis2_fine(severity), {"regulateurs": -8}
        if kind == "nis2_1mois":
            return round(self.nis2_fine(severity) * 0.25, -3), {"regulateurs": -4}
        if kind == "lpm_24h":
            return 150_000.0, {"regulateurs": -12}  # Code de la défense, art. L.1332-7
        if kind == "hds_signalement":
            return 0.0, {"regulateurs": -6, "partenaires": -3}
        if kind == "plainte_72h":
            return 0.0, {}
        return 0.0, {}

    # -- obligations permanentes ---------------------------------------------------------------
    def mark_done(self, key: str, turn: int) -> None:
        self.state.permanent[key] = turn

    def is_satisfied(self, key: str, turn: int, active_measures: set[str], ebios_turn: int | None) -> bool:
        p = PERMANENT[key]
        if key == "nis2_analyse_risques":
            return ebios_turn is not None and turn - ebios_turn <= 52
        if key == "iso_certification":
            suspended = self.state.iso_suspended_until is not None and turn < self.state.iso_suspended_until
            return "M38" in active_measures and not suspended
        if p.measure is not None:
            return p.measure in active_measures
        done = self.state.permanent.get(key)
        if done is None:
            return False
        return p.validity_weeks is None or turn - done < p.validity_weeks

    def compliance_status(self, turn: int, active_measures: set[str], ebios_turn: int | None) -> list[dict[str, Any]]:
        return [
            {"def": p, "ok": self.is_satisfied(p.key, turn, active_measures, ebios_turn)}
            for p in self.applicable_permanent()
        ]

    def compliance_rate(self, turn: int, active_measures: set[str], ebios_turn: int | None) -> float:
        status = self.compliance_status(turn, active_measures, ebios_turn)
        return sum(1 for s in status if s["ok"]) / max(1, len(status))

    def notification_rate(self) -> float:
        total = self.state.on_time + self.state.missed
        return self.state.on_time / total if total else 1.0

    # -- ISO 27001 -------------------------------------------------------------------------
    def iso_covered(self, measure_controls: set[str]) -> set[str]:
        valid = {c["id"] for c in self.iso_catalog}
        return (set(self.state.iso_controls) | measure_controls) & valid

    def iso_progress(self, measure_controls: set[str]) -> float:
        return len(self.iso_covered(measure_controls)) / max(1, len(self.iso_catalog))

    def iso_smsi_step(self, measure_controls: set[str]) -> list[str]:
        """Travaux documentaires du SMSI : couvre les prochains contrôles organisationnels."""
        covered = self.iso_covered(measure_controls)
        todo = [c["id"] for c in self.iso_catalog if c["id"] not in covered]
        todo.sort(key=lambda cid: (not cid.startswith(("5.", "6.")), cid))
        added = todo[:ISO_SMSI_STEP_CONTROLS]
        self.state.iso_controls.extend(added)
        return added

    # -- contrôles simulés -------------------------------------------------------------------
    def schedule_year(self, year: int, turn_for: Callable[[int, int], int], certified: bool) -> list[Inspection]:
        sector_cnil = 0.45 if self.org.secteur == "sante" else 0.30
        planned = []
        if self.rng.random() < sector_cnil:
            planned.append(Inspection("cnil", turn_for(year, self.rng.randint(2, 11))))
        if self.org.regimes.nis2 == "essentielle" or self.org.regimes.lpm_oiv:
            if self.rng.random() < 0.5:
                planned.append(Inspection("anssi", turn_for(year, self.rng.randint(2, 11))))
        if certified or self.org.regimes.iso27001:
            planned.append(Inspection("iso", turn_for(year, self.rng.randint(3, 11))))
        self.state.inspections.extend(planned)
        return planned

    def schedule_anssi_ex_post(self, turn: int) -> Inspection | None:
        """Entité importante : contrôle a posteriori après un incident (NIS2 art. 33)."""
        if self.org.regimes.nis2 != "importante":
            return None
        insp = Inspection("anssi", turn + self.rng.randint(6, 16))
        self.state.inspections.append(insp)
        return insp

    def due_inspections(self, turn: int) -> list[Inspection]:
        return [i for i in self.state.inspections if not i.done and i.turn <= turn]

    def upcoming_inspections(self, turn: int) -> list[Inspection]:
        return sorted((i for i in self.state.inspections if not i.done and i.turn > turn), key=lambda i: i.turn)

    def run_inspection(self, insp: Inspection, turn: int, active_measures: set[str], ebios_turn: int | None,
                       hygiene_coverage: float, measure_controls: set[str],
                       major_incident_mishandled: bool) -> dict[str, Any]:
        insp.done = True
        gaps: list[str] = []
        fine = 0.0
        rep: dict[str, float] = {}
        if insp.kind == "cnil":
            for key in ("registre", "dpo", "formation_rgpd"):
                if self.regime_active(PERMANENT[key].regime) and not self.is_satisfied(
                        key, turn, active_measures, ebios_turn):
                    gaps.append(PERMANENT[key].label)
            missed = [d for d in self.state.deadlines if d.kind == "cnil_72h" and d.status in ("missed", "late")]
            if missed:
                gaps.append("Notification(s) de violation hors délai")
            if not gaps:
                rep = {"regulateurs": 5}
            elif len(gaps) == 1:
                rep = {"regulateurs": -6}
            else:
                fine = self.cnil_fine(2, self.org.secteur == "sante")
                rep = {"regulateurs": -10, "presse": -3}
        elif insp.kind == "anssi":
            for key in ("nis2_enregistrement", "nis2_gouvernance", "nis2_analyse_risques", "lpm_homologation"):
                if self.regime_active(PERMANENT[key].regime) and not self.is_satisfied(
                        key, turn, active_measures, ebios_turn):
                    gaps.append(PERMANENT[key].label)
            if hygiene_coverage < 0.6:
                gaps.append(f"Socle d'hygiène insuffisant ({hygiene_coverage:.0%} < 60 %)")
            if not gaps:
                rep = {"regulateurs": 6}
            elif len(gaps) <= 2:
                rep = {"regulateurs": -6}
            else:
                fine = self.nis2_fine(1) if self.org.regimes.nis2 else 0.0
                rep = {"regulateurs": -12}
        elif insp.kind == "iso":
            progress = self.iso_progress(measure_controls)
            if "M38" not in active_measures:
                gaps.append("Pas de certification en cours (audit client à blanc)")
            if progress < ISO_PASS_THRESHOLD:
                gaps.append(f"Couverture des contrôles de l'annexe A : {progress:.0%} (< 70 %)")
            if major_incident_mishandled:
                gaps.append("Incident majeur mal géré sur la période")
            if not gaps:
                rep = {"partenaires": 6}
            else:
                rep = {"partenaires": -10}
                if "M38" in active_measures:
                    self.state.iso_suspended_until = turn + 26
        insp.result = "conforme" if not gaps else "non conforme"
        return {"inspection": insp, "gaps": gaps, "fine": fine, "reputation": rep}

    # -- sérialisation -------------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        s = self.state
        return {
            "deadlines": [d.to_dict() for d in s.deadlines],
            "permanent": dict(s.permanent),
            "inspections": [asdict(i) for i in s.inspections],
            "iso_controls": list(s.iso_controls),
            "iso_suspended_until": s.iso_suspended_until,
            "on_time": s.on_time, "late": s.late, "missed": s.missed,
        }

    def load_dict(self, d: dict[str, Any]) -> None:
        self.state = ComplianceState(
            deadlines=[Deadline(**x) for x in d.get("deadlines", [])],
            permanent=dict(d.get("permanent", {})),
            inspections=[Inspection(**x) for x in d.get("inspections", [])],
            iso_controls=list(d.get("iso_controls", [])),
            iso_suspended_until=d.get("iso_suspended_until"),
            on_time=int(d.get("on_time", 0)), late=int(d.get("late", 0)), missed=int(d.get("missed", 0)),
        )
