"""Orchestrateur de partie : relie les moteurs et applique les règles transverses.

L'interface graphique ne manipule que cette façade ; elle est entièrement
utilisable sans affichage (tests, mode --headless).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import config
from engine.event_bus import EventBus
from game.budget_engine import INSURANCE_PREREQUISITES, BudgetEngine, BudgetExceededError, insurance_rate
from game.calendar import GameCalendar
from game.compliance_engine import ISO_SMSI_STEP_COST, OBLIGATIONS, PERMANENT, ComplianceEngine, Deadline
from game.data_loader import GameData
from game.difficulty import DEFAULT_DIFFICULTY, Difficulty, get_difficulty
from game.event_engine import EventEngine
from game.governance import (
    BOARD_OPTIONS,
    BOARD_PERIOD,
    OBJECTIVES,
    TRUST_INITIAL,
    board_amount,
    board_probability,
    draw_objectives,
)
from game.incident_engine import PHASE_LABELS, ActiveIncident, IncidentEngine, Phase
from game.measures import Measure, MeasurePortfolio
from game.operations import (
    PHISHING_CAMPAIGN_COST,
    VULN_ACTIONS,
    PhishingKPI,
    TeamEngine,
    ThreatEngine,
    VulnerabilityEngine,
    measure_weekly_load,
)
from game.organisation import INCIDENT_TYPE_LABELS
from game.reputation_engine import ReputationEngine
from game.risk_engine import RiskEngine, Treatment, severity_from_dict
from game.state import DecisionRecord, Mistake, NewsItem, Severity

SAVE_VERSION = 2
TRUST_RECOVERY = 0.15
MAJOR_SEVERITY = 3
BUDGET_INFLATION = 0.02
BUDGET_POST_INCIDENT_BONUS = 0.15
BUDGET_CONTRACT_LOSS_MALUS = 0.10
EBIOS_WORKSHOP_JH = 1.5
SMSI_STEP_JH = 2.0
PHISHING_CAMPAIGN_JH = 1.0
EXERCISE_COST = 3_000.0
ACTION_JH = {"registre": 2.0, "nis2_enregistrement": 0.5, "nis2_gouvernance": 1.0, "hds_hebergeur": 1.0,
             "lpm_homologation": 3.0}
PHISHING_TYPES = ("phishing", "compromission_cloud")


class GameRuleError(Exception):
    """Action refusée par les règles du jeu (message affichable au joueur)."""


@dataclass
class TurnReport:
    turn: int
    news: list[NewsItem] = field(default_factory=list)
    detected: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    board: bool = False
    game_over: bool = False


def _eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", " ")


class Simulation:
    def __init__(self, data: GameData, org_id: str, seed: int | None = None, bus: EventBus | None = None,
                 difficulty: str = DEFAULT_DIFFICULTY, years: int = config.GAME_YEARS) -> None:
        if org_id not in data.organisations:
            raise KeyError(f"Organisation inconnue : {org_id}")
        if not 1 <= int(years) <= 5:
            raise ValueError("La durée du mandat doit être comprise entre 1 et 5 ans")
        self.data = data
        self.org = data.organisations[org_id]
        self.difficulty: Difficulty = get_difficulty(difficulty)
        self.years = int(years)
        self.seed = seed if seed is not None else random.SystemRandom().randrange(1, 2**31)
        self.rng = random.Random(self.seed)
        self.bus = bus or EventBus()
        self.calendar = GameCalendar(total_turns=self.years * config.WEEKS_PER_YEAR)
        self.turn = 1
        dif = self.difficulty

        self.portfolio = MeasurePortfolio(data.measures)
        for mid in self.org.mesures_initiales:
            self.portfolio.add(mid, 0, initial=True)
        impacts = {t.type: t.impact for t in data.incidents.values()}
        chains = {t.type: t.attack_chain for t in data.incidents.values()}
        self.risk = RiskEngine(self.org, data.referential, self.portfolio, impacts, chains)
        self.incidents = IncidentEngine(self.org, data.incidents, self.rng, grace_turns=dif.grace_turns,
                                        max_open=dif.max_open_incidents, cost_mult=dif.cost_mult)
        self.budget = BudgetEngine(self.org, round(self.org.budget_ssi * dif.budget_mult, -2))
        self.compliance = ComplianceEngine(self.org, self.rng, data.iso_controls)
        self.reputation = ReputationEngine(recovery=dif.reputation_recovery)
        self.events = EventEngine(self.org, data.events, self.rng)
        self.team = TeamEngine(self.org, dif, self.rng)
        self.vulns = VulnerabilityEngine(self.org, data.vulns, dif, self.rng)
        self.threat = ThreatEngine(data.campaigns, dif, self.rng)
        self.phishing = PhishingKPI(self.org.taux_clic_initial)
        self.risk.external_factor = self._context_factor

        self.news: list[NewsItem] = []
        self.decisions: list[DecisionRecord] = []
        self.mistakes: list[Mistake] = []
        self.missed_practices: list[dict[str, str]] = []
        self.pending_events: list[str] = []
        self.pending_board = False
        self.board_state: dict[str, Any] = {"rallonges_annee": 0, "recrutements_annee": 0, "history": []}
        self.timeline: list[dict[str, Any]] = []   # chronologie complète (y compris invisible)
        self.game_over_reason: str | None = None
        self.finished = False
        self.contracts_lost = 0
        self.budget_flags: dict[str, int] = {"major_incidents": 0, "contracts_lost": 0}
        self.trust = TRUST_INITIAL
        self.trust_history: list[tuple[int, float]] = []
        self.prep_until = 0
        self.objective_flags: dict[str, Any] = {}

        self.initial_risk = self.risk.average_risk(1)
        self.objectives = draw_objectives(self, random.Random(self.seed + 1))
        self._schedule_year(1)
        self._news(Severity.INFO, "organisation",
                   f"Prise de fonction comme RSSI — {self.org.nom} (difficulté {dif.nom}, mandat de "
                   f"{self.years} an{'s' if self.years > 1 else ''}). Budget SSI : {_eur(self.budget.budget_annuel_ssi)}.")
        for obj in self.objectives:
            self._news(Severity.INFO, "organisation", f"Objectif fixé par la direction : {OBJECTIVES[obj['id']].titre}.")

    # =====================================================================
    # Outils internes
    # =====================================================================
    def _news(self, severity: Severity | str, category: str, text: str) -> NewsItem:
        item = NewsItem(self.turn, category, text, severity.value if isinstance(severity, Severity) else severity)
        self.news.append(item)
        self.bus.publish("news.added", item=item)
        return item

    def _mistake(self, title: str, explanation: str, reference: str, weight: float = 1.0) -> None:
        self.mistakes.append(Mistake(self.turn, title, explanation, reference, weight))

    def _timeline(self, kind: str, text: str, visible: bool = True, **extra: Any) -> None:
        self.timeline.append({"turn": self.turn, "kind": kind, "text": text, "visible": visible, **extra})

    def _trust(self, delta: float, reason: str = "") -> None:
        if delta < 0:
            delta *= self.difficulty.trust_loss_mult
        before = self.trust
        self.trust = max(0.0, min(100.0, self.trust + delta))
        if reason and abs(self.trust - before) >= 3:
            sev = Severity.SUCCESS if delta > 0 else Severity.WARNING
            self._news(sev, "direction", f"Confiance de la direction {'+' if delta > 0 else ''}{self.trust - before:.0f} : {reason}")

    def _context_factor(self, incident_type: str, turn: int) -> float:
        """Difficulté × niveau de menace × vulnérabilités ouvertes × vigilance du personnel."""
        f = self.difficulty.incident_mult * self.threat.factor(incident_type, turn) * self.vulns.factor(incident_type)
        if incident_type in PHISHING_TYPES:
            f *= self.phishing.factor()
        return f

    @property
    def year(self) -> int:
        return self.calendar.year_of(self.turn)

    @property
    def active_measure_ids(self) -> set[str]:
        return set(self.portfolio.active_ids(self.turn))

    @property
    def in_crisis(self) -> bool:
        return bool(self.active_crises())

    def measure_controls(self) -> set[str]:
        return {c for m in self.portfolio.active(self.turn) for c in m.controle_iso}

    def _require_capacity(self, jh: float, label: str) -> None:
        if not self.team.reserve(jh, self.turn, self.in_crisis):
            avail = self.team.available(self.turn, self.in_crisis)
            raise GameRuleError(f"Équipe SSI surchargée : « {label} » demande {jh:g} j·h, "
                                f"{avail:g} j·h disponibles cette semaine.")

    # =====================================================================
    # Mesures et budget
    # =====================================================================
    def has_insurance(self) -> bool:
        return any(m.assurance for m in self.portfolio.active(self.turn))

    def insurance_premium(self) -> float:
        prereq = all(p in self.active_measure_ids for p in INSURANCE_PREREQUISITES)
        rate = insurance_rate(self.risk.hygiene_coverage(self.turn), prereq)
        return round(self.org.plafond_assurance * rate, -2)

    def measure_costs(self, measure: Measure) -> tuple[float, float]:
        """(coût de déploiement, coût annuel récurrent) pour l'organisation jouée."""
        if measure.assurance:
            premium = self.insurance_premium()
            return premium, premium
        return measure.deployment_cost(self.org), measure.annual_cost(self.org)

    def measure_availability(self, measure_id: str) -> tuple[bool, str]:
        m = self.data.measures[measure_id]
        if self.portfolio.has(measure_id):
            st = self.portfolio.items[measure_id]
            if st.is_active(self.turn):
                return False, "Déjà en place"
            return False, f"Déploiement en cours (opérationnelle en semaine {st.ready_turn})"
        missing = [p for p in m.prerequis if p not in self.portfolio.items or self.portfolio.items[p].suspended]
        if missing:
            names = ", ".join(self.data.measures[p].nom for p in missing if p in self.data.measures)
            return False, f"Prérequis : {names}"
        if measure_id == "M38":
            progress = self.compliance.iso_progress(self.measure_controls())
            if progress < 0.6:
                return False, f"Couverture ISO insuffisante ({progress:.0%} < 60 %) pour l'audit de certification"
        cost, _ = self.measure_costs(m)
        if not self.budget.can_afford(cost):
            return False, f"Budget insuffisant ({_eur(cost)})"
        return True, ""

    def buy_measure(self, measure_id: str) -> Measure:
        if measure_id not in self.data.measures:
            raise GameRuleError(f"Mesure inconnue : {measure_id}")
        ok, reason = self.measure_availability(measure_id)
        if not ok:
            raise GameRuleError(reason)
        m = self.data.measures[measure_id]
        cost, _ = self.measure_costs(m)
        try:
            self.budget.spend(cost, m.categorie, m.nom, self.turn)
        except BudgetExceededError as exc:
            raise GameRuleError(str(exc)) from exc
        if measure_id in self.portfolio.items and self.portfolio.items[measure_id].suspended:
            self.portfolio.resume(measure_id, self.turn)
            status = self.portfolio.items[measure_id]
        else:
            status = self.portfolio.add(measure_id, self.turn)
        self._news(Severity.INFO, "mesure",
                   f"Mesure commandée : {m.nom} — opérationnelle en semaine {status.ready_turn}.")
        self._timeline("mesure", f"Commande : {m.nom}")
        self.bus.publish("measure.ordered", measure_id=measure_id)
        return m

    def expected_incident_costs(self) -> dict[str, float]:
        out = {}
        for t in self.incidents.templates.values():
            out[t.type] = (t.cout_min + (t.cout_max - t.cout_min) * self.org.facteur_cout) * self.difficulty.cost_mult
        return out

    def measure_roi(self, measure_id: str) -> dict[str, Any]:
        m = self.data.measures[measure_id]
        deploy, annual = self.measure_costs(m)
        freqs = {t: self.risk.annual_probability(t, self.turn) for t in self.risk.applicable_types()}
        result = self.budget.measure_roi(m, deploy, annual, freqs, self.expected_incident_costs())
        result["risk_before"] = self.risk.risk_matrix(self.turn)
        result["risk_after"] = self.risk.risk_matrix(self.turn, self.portfolio.active(self.turn) + [m])
        return result

    def deployment_load(self) -> float:
        return sum(measure_weekly_load(self.data.measures[st.measure_id].categorie)
                   for st in self.portfolio.in_progress(self.turn))

    # =====================================================================
    # Opérations : équipe, vulnérabilités, hameçonnage
    # =====================================================================
    def vuln_action(self, uid: str, action: str) -> None:
        if action not in VULN_ACTIONS:
            raise GameRuleError(f"Action inconnue : {action}")
        try:
            v = self.vulns.get(uid)
        except KeyError as exc:
            raise GameRuleError("Vulnérabilité inconnue") from exc
        if not v.is_open or not v.visible or v.status == "planifiee":
            raise GameRuleError("Cette vulnérabilité ne peut plus être traitée")
        if (action, v.status) in (("accepter", "acceptee"), ("contourner", "contournee")):
            raise GameRuleError("Action déjà appliquée")
        d = self.vulns.definition(v)
        jh = self.vulns.action_cost(uid, action)
        if jh:
            self._require_capacity(jh, VULN_ACTIONS[action])
        self.vulns.apply_action(uid, action, self.turn)
        if action == "urgence" and d.arret:
            self.reputation.apply({"utilisateurs": -1})
        quality = "bonne"
        if action == "accepter":
            quality = "mauvaise" if d.gravite == "critique" and d.exposition == "internet" else "moyenne"
        elif action == "contourner":
            quality = "moyenne"
        elif action == "planifier" and d.exploitee and d.exposition == "internet":
            quality = "moyenne"
        self.decisions.append(DecisionRecord(
            self.turn, v.uid, f"{d.id} — {d.produit}", d.titre, VULN_ACTIONS[action], quality,
            "Une vulnérabilité critique exploitée et exposée sur Internet se corrige en urgence (ou se contourne "
            "immédiatement) : l'exploitation suit souvent la divulgation de quelques heures."
            if quality != "bonne" else "Traitement adapté à la gravité et à l'exposition de la vulnérabilité.",
            "Guide d'hygiène informatique ANSSI, mesure 34 ; avis et alertes CERT-FR", 0.0, ["vulnerabilite"]))
        self._news(Severity.INFO, "operations", f"{d.id} ({d.produit}) : {VULN_ACTIONS[action].lower()}.")

    def run_phishing_campaign(self) -> float:
        if not self.budget.can_afford(PHISHING_CAMPAIGN_COST):
            raise GameRuleError("Budget insuffisant pour la campagne")
        self._require_capacity(PHISHING_CAMPAIGN_JH, "campagne de faux hameçonnage")
        self.budget.spend(PHISHING_CAMPAIGN_COST, "formation", "Campagne de faux hameçonnage", self.turn)
        rate = self.phishing.run_campaign(self.turn, self.rng)
        self._news(Severity.INFO, "operations", f"Campagne de faux hameçonnage : {rate:.1%} du personnel a cliqué.")
        return rate

    def hire_reinforcement(self) -> None:
        cost = self.team.reinforcement_cost()
        if not self.budget.can_afford(cost):
            raise GameRuleError(f"Budget insuffisant ({_eur(cost)})")
        self.budget.spend(cost, "externalisation", "Renfort SSI en régie (8 semaines)", self.turn)
        self.team.add_reinforcement(self.turn)
        self._news(Severity.INFO, "operations", "Renfort d'un consultant SSI pour 8 semaines.")

    # =====================================================================
    # Conformité : actions du joueur
    # =====================================================================
    def compliance_action(self, key: str) -> None:
        p = PERMANENT.get(key)
        if p is None:
            raise GameRuleError(f"Obligation inconnue : {key}")
        if p.measure is not None:
            self.buy_measure(p.measure)
            return
        if key == "nis2_analyse_risques":
            raise GameRuleError("Réalisez les 5 ateliers EBIOS RM depuis le tableau de bord.")
        if p.cost > 0 and not self.budget.can_afford(p.cost):
            raise GameRuleError("Budget insuffisant")
        self._require_capacity(ACTION_JH.get(key, 1.0), p.action)
        if p.cost > 0:
            self.budget.spend(p.cost, p.category, p.action, self.turn)
        self.compliance.mark_done(key, self.turn)
        self._news(Severity.SUCCESS, "conformite", f"Conformité : {p.label}.")
        self.reputation.apply({"regulateurs": 1})

    def iso_smsi_step(self) -> list[str]:
        if not self.budget.can_afford(ISO_SMSI_STEP_COST):
            raise GameRuleError("Budget insuffisant pour les travaux SMSI")
        self._require_capacity(SMSI_STEP_JH, "travaux SMSI")
        self.budget.spend(ISO_SMSI_STEP_COST, "audit", "Travaux documentaires SMSI", self.turn)
        added = self.compliance.iso_smsi_step(self.measure_controls())
        self._news(Severity.INFO, "conformite", f"SMSI : {len(added)} contrôles ISO documentés.")
        return added

    def notify_obligation(self, incident_uid: str, kind: str) -> Deadline:
        inc = self.incidents.get(incident_uid)
        hour = self.hours_since_detection(inc)
        d = self.compliance.notify(incident_uid, kind, hour)
        o = OBLIGATIONS[kind]
        if d.status == "on_time":
            self.reputation.apply({"regulateurs": 2})
            self._news(Severity.SUCCESS, "conformite", f"{o.label} : transmis à H+{hour}.")
        else:
            self._news(Severity.WARNING, "conformite", f"{o.label} : transmis hors délai (H+{hour}).")
        self._timeline("notification", f"{o.label} (H+{hour})", incident=incident_uid)
        return d

    def hours_since_detection(self, inc: ActiveIncident) -> int:
        if inc.in_crisis:
            return inc.crisis_hour
        return max(inc.crisis_hour, (self.turn - inc.detection_turn) * 168)

    def _apply_deadline_penalty(self, deadline: Deadline, inc: ActiveIncident) -> None:
        if deadline.penalized:
            return
        deadline.penalized = True
        t = self.incidents.template(inc)
        severity = severity_from_dict(t.impact)
        sensitive = self.org.secteur == "sante" and t.donnees_personnelles
        fine, rep = self.compliance.penalty_for(deadline, severity, sensitive)
        fine = round(fine * self.difficulty.fine_mult, -3)
        o = OBLIGATIONS[deadline.kind]
        if fine:
            self.budget.record_fine(fine, self.turn, o.label)
            sanctioned = self.objective_flags.setdefault("sanctioned_incidents", [])
            if inc.uid not in sanctioned:   # la direction réagit à l'incident, pas à chaque courrier
                sanctioned.append(inc.uid)
                self._trust(-5, f"sanction ({o.authority})")
        self.reputation.apply(rep)
        msg = f"Délai dépassé : {o.label}"
        if fine:
            msg += f" — sanction {_eur(fine)}"
        self._news(Severity.DANGER, "conformite", msg + ".")
        self._mistake(
            f"{o.label} non réalisée dans le délai",
            f"Lors de l'incident « {t.title} », l'obligation « {o.label} » (délai {o.hours} h après "
            f"détection) n'a pas été respectée. Préparez des modèles de notification et intégrez "
            f"l'étape au plan de gestion de crise.",
            o.reference, 1.5 if fine else 1.0,
        )
        self._timeline("sanction", msg, incident=inc.uid)

    def _check_incident_deadlines(self, inc: ActiveIncident) -> None:
        for d in self.compliance.check_deadlines(inc.uid, self.hours_since_detection(inc)):
            self._apply_deadline_penalty(d, inc)

    # =====================================================================
    # Incidents : salle de crise
    # =====================================================================
    def active_crises(self) -> list[ActiveIncident]:
        return self.incidents.crises()

    def decision_hint(self, incident_uid: str) -> str | None:
        """Conseil « réflexe ANSSI » (niveau Découverte uniquement)."""
        if not self.difficulty.show_hints:
            return None
        inc = self.incidents.get(incident_uid)
        d = self.incidents.pending_decision(inc)
        if d is None:
            return None
        best = next((c for c in d.choix if c.qualite == "bonne"), None)
        return f"Réflexe recommandé : {best.texte}" if best else None

    def crisis_decide(self, incident_uid: str, decision_id: str, choice_id: str) -> dict[str, Any]:
        inc = self.incidents.get(incident_uid)
        t = self.incidents.template(inc)
        decision = self.incidents.pending_decision(inc)
        choice = self.incidents.decide(inc, decision_id, choice_id)
        effects = choice.effets
        self.reputation.apply(effects.get("reputation") or {})
        for mod in effects.get("risque", []) or []:
            self.risk.add_modifier(mod["type"], float(mod["facteur"]), self.turn + int(mod.get("semaines", 52)),
                                   t.id)
        new_obligations = self.compliance.applicable_obligations(
            list(effects.get("declenche", []) or []), self.has_insurance(), True)
        self.compliance.open_deadlines(inc.uid, new_obligations)
        record = DecisionRecord(
            turn=self.turn, source=inc.uid, source_title=t.title, question=decision.texte if decision else "",
            choice=choice.texte, quality=choice.qualite, feedback=choice.feedback, reference=choice.reference,
            impact_eur=float(effects.get("cout_fixe", 0.0)), tags=[t.type],
        )
        self.decisions.append(record)
        self._timeline("decision", f"H+{decision.heure if decision else '?'} — {choice.texte}", incident=inc.uid,
                       quality=choice.qualite)
        if choice.qualite == "mauvaise":
            self._mistake(f"Décision de crise inadaptée — {t.title}",
                          f"« {choice.texte} » : {choice.feedback}",
                          choice.reference or "Guide ANSSI de gestion de crise cyber", 1.0)
        self._check_incident_deadlines(inc)
        self.bus.publish("incident.decision", incident=inc.uid, choice=choice.id)
        return {"choice": choice, "record": record, "next": self.incidents.pending_decision(inc)}

    def crisis_close(self, incident_uid: str) -> dict[str, Any]:
        inc = self.incidents.get(incident_uid)
        t = self.incidents.template(inc)
        cost = self.incidents.end_crisis(inc, self.turn)
        if self.turn < self.prep_until:
            cost = round(cost * 0.9, -2)   # comité entraîné lors d'un exercice de crise
            inc.final_cost = cost
        self._check_incident_deadlines(inc)
        insured = self.has_insurance()
        plainte = next((d for d in self.compliance.deadlines_for(inc.uid) if d.kind == "plainte_72h"), None)
        condition = plainte is None or plainte.status == "on_time"
        result = self.budget.record_incident_cost(cost, self.turn, insured, condition)
        if insured and not condition:
            self._mistake("Prise en charge assurance refusée",
                          "Sans dépôt de plainte dans les 72 h, l'assureur peut refuser l'indemnisation "
                          "des pertes liées à l'attaque.", OBLIGATIONS["plainte_72h"].reference, 1.0)
        quality = self.incidents.decision_quality(inc)
        severity = severity_from_dict(t.impact)
        if severity >= MAJOR_SEVERITY:
            self.budget_flags["major_incidents"] += 1
        if quality >= 0.75:
            self.reputation.apply({"partenaires": 3, "presse": 2})
            self._trust(4, "gestion de crise maîtrisée")
        elif quality < 0.4:
            self._trust(-8 if severity >= MAJOR_SEVERITY else -5, "gestion de crise défaillante")
        else:
            self._trust(-2)
        self.compliance.schedule_anssi_ex_post(self.turn)
        msg = (f"Fin de crise « {t.title} » — coût {_eur(result['brut'])}"
               + (f", dont {_eur(result['rembourse'])} pris en charge par l'assurance" if result["rembourse"] else "")
               + f". Reprise complète prévue semaine {inc.recovery_end_turn}.")
        self._news(Severity.WARNING, "incident", msg)
        self._timeline("crise_close", msg, incident=inc.uid)
        self.bus.publish("incident.crisis_closed", incident=inc.uid)
        return {"cost": result, "quality": quality, "recovery_end": inc.recovery_end_turn}

    def _on_detected(self, inc: ActiveIncident) -> None:
        t = self.incidents.template(inc)
        severity = severity_from_dict(t.impact)
        self.reputation.apply(t.impact_reputation or {"utilisateurs": -severity, "partenaires": -severity // 2,
                                                      "presse": -severity})
        kinds = self.compliance.applicable_obligations(t.obligations_declenchees, self.has_insurance(),
                                                       t.donnees_personnelles)
        self.compliance.open_deadlines(inc.uid, kinds)
        weeks = inc.undetected_weeks
        self._news(Severity.DANGER, "incident",
                   f"INCIDENT DÉTECTÉ : {t.title}" + (f" (compromission initiale il y a {weeks} sem.)" if weeks else ""))
        self._timeline("detection", f"Détection : {t.title}", incident=inc.uid)
        if t.type in self.risk.accepted_high_risk_types():
            self._mistake(f"Risque élevé accepté sans traitement — {INCIDENT_TYPE_LABELS[t.type]}",
                          "L'étude EBIOS RM avait identifié ce scénario à un niveau élevé ou critique ; "
                          "il a été accepté sans mesure de réduction ni transfert.",
                          "EBIOS Risk Manager, atelier 5 — stratégie de traitement du risque", 1.5)
        if weeks >= 12 and self.risk.detection_factor(self.turn) > 0.7:
            self._mistake("Détection tardive de la compromission",
                          f"L'attaquant est resté {weeks} semaines dans le SI sans être détecté. "
                          "Sans journalisation centralisée ni supervision, le temps de présence s'allonge.",
                          "Guide d'hygiène informatique ANSSI, mesure 36 ; NIS2 art. 21 §2 b)", 1.0)
        self.bus.publish("incident.detected", incident=inc.uid, template=t.id)

    def _on_closed(self, inc: ActiveIncident) -> None:
        t = self.incidents.template(inc)
        self._news(Severity.INFO, "incident", f"Retour d'expérience publié : {t.title}. Incident clos.")
        self._timeline("rex", f"REX et clôture : {t.title}", incident=inc.uid)
        missing = [m for m in t.mesures_cles if m in self.data.measures and m not in self.active_measure_ids]
        for mid in missing:
            m = self.data.measures[mid]
            entry = {"incident": t.title, "mesure": m.nom, "reference": m.guide_anssi, "id": mid}
            if entry not in self.missed_practices:
                self.missed_practices.append(entry)
        for d in self.compliance.deadlines_for(inc.uid):
            if d.status == "pending":
                d.status = "missed"
                self.compliance.state.missed += 1
                self._apply_deadline_penalty(d, inc)

    # =====================================================================
    # Événements
    # =====================================================================
    def event_choice_available(self, event_id: str, choice_id: str) -> tuple[bool, str]:
        c = self.data.events[event_id].choice(choice_id)
        cost = float(c.effets.get("cout", 0))
        if cost > 0 and not self.budget.can_afford(cost):
            return False, "Budget insuffisant"
        return True, ""

    def resolve_event(self, event_id: str, choice_id: str) -> dict[str, Any]:
        if event_id not in self.pending_events:
            raise GameRuleError("Événement non en attente")
        ev = self.data.events[event_id]
        c = ev.choice(choice_id)
        ok, reason = self.event_choice_available(event_id, choice_id)
        if not ok:
            raise GameRuleError(reason)
        e = c.effets
        if e.get("cout"):
            self.budget.spend(float(e["cout"]), e.get("categorie", "divers"), ev.titre, self.turn)
        if e.get("budget_rallonge"):
            self.budget.adjust_budget(float(e["budget_rallonge"]), e.get("categorie", "divers"))
        if e.get("cout_incident"):
            self.budget.record_incident_cost(float(e["cout_incident"]) * self.difficulty.cost_mult, self.turn)
        if e.get("amende"):
            self.budget.record_fine(float(e["amende"]) * self.difficulty.fine_mult, self.turn, ev.titre)
        self.reputation.apply(e.get("reputation") or {})
        for mod in e.get("risque", []) or []:
            self.risk.add_modifier(mod["type"], float(mod["facteur"]), self.turn + int(mod.get("semaines", 26)), ev.id)
        for key in e.get("conformite", []) or []:
            if key in PERMANENT:
                self.compliance.mark_done(key, self.turn)
        offered = e.get("mesure_offerte")
        if offered and offered in self.data.measures and not self.portfolio.has(offered):
            self.portfolio.add(offered, self.turn)
        if e.get("budget_annuel"):
            self.budget_flags["bonus_pct"] = self.budget_flags.get("bonus_pct", 0) + int(100 * float(e["budget_annuel"]))
        tid = e.get("incident")
        if tid and tid in self.incidents.templates and self.incidents.can_open(self.incidents.templates[tid].type):
            self._start_incident(tid)
        self.pending_events.remove(event_id)
        self.decisions.append(DecisionRecord(self.turn, ev.id, ev.titre, ev.description, c.texte, c.qualite,
                                             c.feedback, c.reference, float(e.get("cout", 0)), [ev.categorie]))
        if c.qualite == "mauvaise":
            self._mistake(f"Choix risqué — {ev.titre}", f"« {c.texte} » : {c.feedback}", c.reference, 0.75)
        self._news(Severity.INFO, "evenement", f"{ev.titre} → {c.texte}")
        return {"choice": c}

    # =====================================================================
    # Comité de direction
    # =====================================================================
    def board_options(self) -> list[dict[str, Any]]:
        amount = board_amount(self)
        opts = []
        for key, label in BOARD_OPTIONS.items():
            prob = board_probability(self, key)
            detail = ""
            available, reason = True, ""
            if key == "rallonge":
                detail = f"{_eur(amount)} supplémentaires sur l'exercice en cours"
            elif key == "recrutement":
                detail = "Un analyste SSI de plus dans 8 semaines (financé sur la masse salariale)"
            elif key == "exercice":
                detail = f"Coût {_eur(EXERCISE_COST)} — coûts des crises −10 % pendant 26 semaines"
                if not self.budget.can_afford(EXERCISE_COST):
                    available, reason = False, "Budget insuffisant"
            else:
                detail = "Renforce la confiance de la direction"
            opts.append({"id": key, "label": label, "detail": detail, "probability": prob,
                         "available": available, "reason": reason})
        return opts

    def board_summary(self) -> str:
        level, cat = self.global_risk()
        crit = len(self.vulns.critical_exposed())
        incidents = sum(1 for i in self.incidents.incidents if i.detected and self.turn - i.detection_turn <= 13)
        return (f"Indicateurs du trimestre : risque global {level}/16, {incidents} incident(s) détecté(s), "
                f"{crit} vulnérabilité(s) critique(s) exposée(s), budget consommé "
                f"{self.budget.spent / max(1, self.budget.budget_annuel_ssi):.0%}, réputation "
                f"{self.reputation.global_score():.0f}/100. Confiance de la direction : {self.trust:.0f}/100.")

    def resolve_board(self, option: str) -> dict[str, Any]:
        if not self.pending_board:
            raise GameRuleError("Aucun comité de direction en cours")
        if option not in BOARD_OPTIONS:
            raise GameRuleError(f"Option inconnue : {option}")
        prob = board_probability(self, option)
        success = self.rng.random() < prob
        if option == "rallonge":
            if success:
                amount = board_amount(self)
                self.budget.adjust_budget(amount, "divers")
                self.board_state["rallonges_annee"] = self.board_state.get("rallonges_annee", 0) + 1
                self.board_state["rallonges_montant"] = self.board_state.get("rallonges_montant", 0.0) + amount
                msg = f"Rallonge accordée : {_eur(amount)}."
                self._trust(1)
            else:
                msg = "Rallonge refusée : la direction attend des résultats avant d'investir davantage."
                self._trust(-3)
        elif option == "recrutement":
            if success:
                arrival = self.team.recruit(self.turn)
                self.board_state["recrutements_annee"] = self.board_state.get("recrutements_annee", 0) + 1
                msg = f"Recrutement validé : un analyste SSI arrivera vers la semaine {arrival}."
            else:
                msg = "Recrutement refusé pour cette année."
                self._trust(-2)
        elif option == "exercice":
            if not self.budget.can_afford(EXERCISE_COST):
                raise GameRuleError("Budget insuffisant")
            self.budget.spend(EXERCISE_COST, "formation", "Exercice de crise avec le comité de direction", self.turn)
            self.prep_until = self.turn + 26
            success = True
            msg = "Exercice de crise organisé : la direction connaît désormais son rôle en cas d'attaque."
            self._trust(6, "exercice de crise avec le comité")
        else:
            success = True
            msg = "Bilan présenté : la direction apprécie la transparence."
            self._trust(4, "bilan trimestriel transparent")
        self.board_state.setdefault("history", []).append({"turn": self.turn, "option": option, "success": success})
        self.pending_board = False
        self._news(Severity.SUCCESS if success else Severity.WARNING, "direction", f"Comité de direction : {msg}")
        return {"success": success, "message": msg, "probability": prob}

    # =====================================================================
    # EBIOS RM
    # =====================================================================
    def complete_workshop(self, n: int) -> float:
        r = self.risk
        if n not in range(1, 6):
            raise ValueError(n)
        if not r.study.unlocked(n):
            raise ValueError(f"L'atelier {n} n'est pas encore accessible")
        if not self.team.available(self.turn, self.in_crisis) >= EBIOS_WORKSHOP_JH - 1e-6:
            raise GameRuleError(f"Équipe SSI surchargée : un atelier EBIOS demande {EBIOS_WORKSHOP_JH:g} j·h.")
        if n == 1:
            score = r.complete_workshop1()
        elif n == 2:
            score = r.complete_workshop2()
        elif n == 3:
            score = r.complete_workshop3()
        elif n == 4:
            score = r.complete_workshop4(self.turn)
        else:
            score = r.complete_workshop5(self.turn, self.has_insurance())
            refused = sum(1 for v in r.study.treatments.values() if v == Treatment.REFUSER.value)
            if refused:
                self.reputation.apply({"utilisateurs": -2 * refused})
            self.reputation.apply({"regulateurs": 4, "partenaires": 2})
            self._trust(3, "analyse de risques présentée à la direction")
            self._news(Severity.SUCCESS, "ebios",
                       "Étude EBIOS RM finalisée : analyse de risques à jour (NIS2 art. 21).")
            self._timeline("ebios", "Étude EBIOS RM finalisée")
        self.team.reserve(EBIOS_WORKSHOP_JH, self.turn, self.in_crisis)
        self._news(Severity.INFO, "ebios", f"EBIOS RM — atelier {n} validé (qualité {score:.0%}).")
        return score

    # =====================================================================
    # Avancement du temps
    # =====================================================================
    def blocking_reasons(self) -> list[str]:
        reasons = []
        for inc in self.active_crises():
            reasons.append(f"Crise en cours : {self.incidents.template(inc).title}")
        for eid in self.pending_events:
            reasons.append(f"Décision attendue : {self.data.events[eid].titre}")
        if self.pending_board:
            reasons.append("Comité de direction en attente de votre présentation")
        return reasons

    def can_advance(self) -> bool:
        return not self.finished and not self.blocking_reasons()

    def _start_incident(self, template_id: str) -> ActiveIncident:
        t = self.incidents.templates[template_id]
        inc = self.incidents.start(
            template_id, self.turn,
            detection_factor=self.risk.detection_factor(self.turn),
            impact_reduction=self.risk.impact_reduction(t.type, self.turn),
        )
        self._timeline("compromission", f"Compromission initiale (invisible) : {t.initial_vector or t.title}",
                       visible=False, incident=inc.uid)
        if inc.detection_turn <= self.turn:
            inc.phase = Phase.DETECTION
            self._on_detected(inc)
        return inc

    def _close_week(self) -> None:
        """Fin de la semaine écoulée : charge de l'équipe, retards de déploiement, épuisement."""
        load = self.deployment_load()
        cap = self.team.capacity(self.turn, self.in_crisis)
        free = cap - self.team.state.used
        if load > free + 1e-6:
            delayed = 0
            for st in sorted(self.portfolio.in_progress(self.turn), key=lambda s: -s.ordered_turn):
                if load <= free + 1e-6:
                    break
                st.ready_turn += 1
                load -= measure_weekly_load(self.data.measures[st.measure_id].categorie)
                delayed += 1
            if delayed:
                self._news(Severity.WARNING, "operations",
                           f"Équipe SSI saturée : {delayed} déploiement(s) retardé(s) d'une semaine.")
        result = self.team.end_week(self.turn, self.deployment_load(), self.in_crisis)
        if result["departure"]:
            self._news(Severity.DANGER, "operations",
                       "Épuisement : un membre de l'équipe SSI quitte l'organisation après des semaines de surcharge.")
            self._mistake("Équipe SSI épuisée",
                          "Une surcharge prolongée a provoqué le départ d'un collaborateur. Priorisez les chantiers, "
                          "demandez des renforts ou externalisez une partie du run.",
                          "ANSSI, Guide d'hygiène informatique, mesure 1 ; NIS2 art. 20 (moyens alloués)", 1.0)
            self._trust(-4, "départ d'un membre de l'équipe SSI")
        if result["arrivals"]:
            self._news(Severity.SUCCESS, "operations", "Un nouvel analyste SSI rejoint l'équipe.")

    def _weekly_operations(self, report: TurnReport) -> None:
        active = self.active_measure_ids
        res = self.vulns.weekly(self.turn, active, exploit_allowed=self.turn > self.difficulty.grace_turns)
        for v in res["patched"]:
            d = self.vulns.definition(v)
            self._news(Severity.SUCCESS, "operations", f"Correctif appliqué : {d.id} ({d.produit}).")
        for v in res["exploited"]:
            d = self.vulns.definition(v)
            tmpl = self.incidents.template_for_type(d.type)
            self._timeline("exploitation", f"Exploitation silencieuse de {d.id}", visible=False)
            if v.status == "acceptee":
                self._mistake(f"Vulnérabilité acceptée puis exploitée — {d.id}",
                              f"La vulnérabilité « {d.titre} » ({d.produit}) avait été acceptée alors qu'elle était "
                              "exploitée activement et exposée sur Internet.",
                              "Avis et alertes CERT-FR ; Guide d'hygiène informatique ANSSI, mesure 34", 1.5)
            if tmpl is not None and self.incidents.can_open(d.type):
                inc = self._start_incident(tmpl.id)
                if inc.detected:
                    report.detected.append(inc.uid)
        new = self.vulns.spawn(self.turn, active)
        if new is not None and new.visible:
            d = self.vulns.definition(new)
            sev = Severity.DANGER if d.gravite == "critique" and d.exposition == "internet" else Severity.WARNING
            self._news(sev, "operations", f"CERT-FR : {d.id} — {d.produit}. {d.titre}"
                                          + (" Exploitation active signalée." if d.exploitee else ""))
        crit = self.vulns.critical_exposed()
        if any(self.turn - v.discovered > 4 for v in crit):
            self.objective_flags["vuln_breach"] = True
        if self.difficulty.deadline_reminders:
            for v in crit:
                if v.visible and self.turn - v.discovered == 3:
                    self._news(Severity.WARNING, "operations",
                               f"Rappel : {self.vulns.definition(v).id} est exposée sans correctif depuis 3 semaines.")
        camp = self.threat.weekly(self.turn)
        if camp is not None:
            self._news(Severity.WARNING, "menace", f"Bulletin de veille : {camp.titre}. {camp.texte}")
        if self.turn % BOARD_PERIOD == 0:
            self.phishing.quarterly("M01" in active, "M21" in active)
            if self.turn < self.calendar.total_turns:
                self.pending_board = True
                report.board = True
                self._news(Severity.INFO, "direction", "Comité de direction trimestriel : présentez votre bilan.")

    def _update_objectives(self) -> None:
        level, _ = self.global_risk()
        if level <= 9:
            self.objective_flags["risk_reached"] = True
        for obj in self.objectives:
            if obj["status"] != "en_cours":
                continue
            status = OBJECTIVES[obj["id"]].evaluate(self, obj["params"])
            if status != "en_cours":
                obj["status"], obj["turn"] = status, self.turn
                title = OBJECTIVES[obj["id"]].titre
                if status == "reussi":
                    self._news(Severity.SUCCESS, "direction", f"Objectif atteint : {title}.")
                    self._trust(5)
                else:
                    self._news(Severity.DANGER, "direction", f"Objectif manqué : {title}.")
                    self._trust(-4)

    def next_turn(self) -> TurnReport:
        if self.finished:
            raise GameRuleError("La partie est terminée")
        reasons = self.blocking_reasons()
        if reasons:
            raise GameRuleError(reasons[0])
        self._close_week()
        self.turn += 1
        first_news = len(self.news)
        report = TurnReport(self.turn)
        if self.calendar.is_finished(self.turn):
            self.turn = self.calendar.total_turns
            self._update_objectives_final()
            self._finish(f"Fin du mandat : {self.years} an{'s' if self.years > 1 else ''} écoulé"
                         f"{'s' if self.years > 1 else ''}.")
            report.game_over = True
            return report

        if self.calendar.is_year_start(self.turn):
            self._new_year()
        for m in self.portfolio.newly_ready(self.turn):
            self._news(Severity.SUCCESS, "mesure", f"Mesure opérationnelle : {m.nom}.")
            if m.id in ("M25", "M26"):
                revealed = self.vulns.reveal_hidden(0.8)
                if revealed:
                    self._news(Severity.WARNING, "operations",
                               f"{m.nom} : {len(revealed)} vulnérabilité(s) jusque-là ignorée(s) découverte(s).")
        self.risk.purge_modifiers(self.turn)

        progress = self.incidents.advance(self.turn)
        for inc in progress["detected"]:
            self._on_detected(inc)
            report.detected.append(inc.uid)
        for inc in progress["closed"]:
            self._on_closed(inc)

        self._weekly_operations(report)

        weekly = {t: self.risk.weekly_probability(t, self.turn) for t in self.risk.applicable_types()}
        new_tid = self.incidents.roll(self.turn, weekly)
        if new_tid:
            inc = self._start_incident(new_tid)
            if inc.detected:
                report.detected.append(inc.uid)

        for inc in self.incidents.incidents:
            if inc.detected and not inc.in_crisis and not inc.closed:
                self._check_incident_deadlines(inc)
                if self.difficulty.deadline_reminders:
                    for d in self.compliance.deadlines_for(inc.uid):
                        if d.status == "pending" and d.kind == "nis2_1mois":
                            left = OBLIGATIONS[d.kind].hours - self.hours_since_detection(inc)
                            if 0 < left <= 168:
                                self._news(Severity.WARNING, "conformite",
                                           "Rappel : le rapport final NIS2 est attendu sous une semaine.")

        self._run_inspections()

        ev = self.events.roll(self.turn, self.year)
        if ev is not None:
            self.pending_events.append(ev.id)
            report.events.append(ev.id)
            self._news(Severity.WARNING, "evenement", f"{ev.de + ' : ' if ev.de else ''}{ev.titre}")

        self.reputation.weekly_update(self.turn)
        if self.reputation.check_contract_loss():
            self.contracts_lost += 1
            self.budget_flags["contracts_lost"] += 1
            self.reputation.apply({"partenaires": -5})
            self._trust(-10, "perte d'un partenaire majeur")
            self._news(Severity.DANGER, "reputation",
                       f"Perte de confiance : {self.org.contrat_majeur} est rompu(e).")
            self._mistake("Perte d'un contrat majeur",
                          "La réputation globale est passée sous 40/100 : un partenaire majeur s'est retiré.",
                          "Guide ANSSI « Crise d'origine cyber : les clés d'une gestion opérationnelle et stratégique »", 1.5)
        self._update_objectives()
        if self.trust < TRUST_INITIAL:   # le temps apaise : la direction juge aussi la tendance
            self.trust = min(TRUST_INITIAL, self.trust + TRUST_RECOVERY / self.difficulty.trust_loss_mult)
        self.trust_history.append((self.turn, round(self.trust, 1)))
        if self.reputation.is_game_over():
            self._finish("Perte de confiance totale : la réputation globale est passée sous 20/100.")
            report.game_over = True
        elif self.trust < self.difficulty.dismissal_threshold:
            self._mistake("Licenciement par la direction",
                          "La confiance de la direction s'est effondrée (crises mal gérées, sanctions, objectifs "
                          "manqués). Rendre compte régulièrement et tenir ses engagements est une compétence clé du RSSI.",
                          "ANSSI, Guide « Crise d'origine cyber » — rôle de la direction ; NIS2 art. 20", 2.0)
            self._finish("Fin de mandat anticipée : la direction a mis fin à vos fonctions de RSSI.")
            report.game_over = True
        report.news = self.news[first_news:]
        self.bus.publish("turn.advanced", turn=self.turn)
        return report

    def _update_objectives_final(self) -> None:
        self.finished = True
        try:
            self._update_objectives()
        finally:
            self.finished = False

    def _schedule_year(self, year: int) -> None:
        certified = "M38" in self.portfolio.items
        planned = self.compliance.schedule_year(year, self.calendar.turn_for_year_month, certified)
        for insp in planned:
            if insp.kind == "iso":
                d = self.calendar.format_date(self.calendar.date_for(insp.turn))
                self._news(Severity.INFO, "conformite", f"Audit ISO 27001 planifié le {d}.")

    def _new_year(self) -> None:
        year = self.year
        bonus = BUDGET_INFLATION
        if self.budget_flags.get("major_incidents"):
            bonus += BUDGET_POST_INCIDENT_BONUS
        bonus -= BUDGET_CONTRACT_LOSS_MALUS * self.budget_flags.get("contracts_lost", 0)
        bonus += self.budget_flags.get("bonus_pct", 0) / 100.0
        base = self.org.budget_ssi * self.difficulty.budget_mult
        # la base n'intègre pas les rallonges ponctuelles de l'année écoulée
        previous = max(base, self.budget.budget_annuel_ssi - self.board_state.get("rallonges_montant", 0.0))
        new_budget = round(previous * (1 + bonus), -2)
        new_budget = max(new_budget, 0.6 * base)
        maintenance = []
        for mid in self.portfolio.paid_ids():
            m = self.data.measures[mid]
            _, annual = self.measure_costs(m)
            maintenance.append((mid, m.nom, annual, m.categorie))
        unfunded = self.budget.new_year(new_budget, maintenance, self.turn)
        for mid in unfunded:
            self.portfolio.suspend(mid)
            self._news(Severity.DANGER, "budget",
                       f"Maintenance non financée : {self.data.measures[mid].nom} est suspendue.")
        self._news(Severity.INFO, "budget", f"Année {year} — budget SSI voté : {_eur(new_budget)} ({bonus:+.0%}).")
        self.budget_flags = {"major_incidents": 0, "contracts_lost": 0}
        self.board_state["rallonges_annee"] = 0
        self.board_state["rallonges_montant"] = 0.0
        self.board_state["recrutements_annee"] = 0
        if "M25" in self.active_measure_ids:
            revealed = self.vulns.reveal_hidden(0.8)
            if revealed:
                self._news(Severity.WARNING, "operations",
                           f"Test d'intrusion annuel : {len(revealed)} vulnérabilité(s) ignorée(s) découverte(s).")
        self._schedule_year(year)

    def _run_inspections(self) -> None:
        mishandled = any(
            inc.recovery_end_turn is not None
            for inc in self.incidents.incidents
            if inc.decisions_taken and self.incidents.decision_quality(inc) < 0.5
            and severity_from_dict(self.incidents.template(inc).impact) >= MAJOR_SEVERITY
            and self.turn - inc.detection_turn <= 52
        )
        for insp in self.compliance.due_inspections(self.turn):
            result = self.compliance.run_inspection(
                insp, self.turn, self.active_measure_ids, self.risk.study.completed_turn,
                self.risk.hygiene_coverage(self.turn), self.measure_controls(), mishandled)
            labels = {"cnil": "Contrôle CNIL", "anssi": "Contrôle ANSSI", "iso": "Audit de surveillance ISO 27001"}
            self.reputation.apply(result["reputation"])
            if result["fine"]:
                self.budget.record_fine(round(result["fine"] * self.difficulty.fine_mult, -3), self.turn,
                                        labels[insp.kind])
            if result["gaps"]:
                gaps = " ; ".join(result["gaps"])
                self._news(Severity.DANGER, "conformite", f"{labels[insp.kind]} : non-conformités — {gaps}.")
                self._mistake(f"{labels[insp.kind]} défavorable", gaps,
                              "RGPD art. 30-39" if insp.kind == "cnil" else
                              "NIS2 art. 20-21" if insp.kind == "anssi" else "ISO/IEC 27001:2022 § 9.2", 1.0)
                self._trust(-3)
            else:
                self._news(Severity.SUCCESS, "conformite", f"{labels[insp.kind]} : aucune non-conformité.")
                self._trust(2)
            self._timeline("controle", f"{labels[insp.kind]} : {insp.result}")

    def _finish(self, reason: str) -> None:
        self.finished = True
        self.game_over_reason = reason
        self._news(Severity.INFO, "organisation", reason)
        self.bus.publish("game.over", reason=reason)

    def abandon(self) -> None:
        if not self.finished:
            self._finish("Partie arrêtée par le joueur.")

    # =====================================================================
    # Indicateurs pour l'interface
    # =====================================================================
    def current_date_label(self) -> str:
        return self.calendar.format_date(self.calendar.date_for(self.turn))

    def global_risk(self) -> tuple[int, str]:
        return self.risk.global_risk(self.turn)

    def phase_label(self, inc: ActiveIncident) -> str:
        return PHASE_LABELS[Phase(inc.phase)]

    def visible_incidents(self) -> list[ActiveIncident]:
        return [i for i in self.incidents.incidents if i.detected]

    def compromised_assets_hint(self) -> int:
        """Nombre d'incidents en cours de crise ou de reprise (pour la carte du SI)."""
        return sum(1 for i in self.incidents.incidents if i.detected and not i.closed)

    # =====================================================================
    # Sérialisation
    # =====================================================================
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SAVE_VERSION, "org_id": self.org.id, "seed": self.seed, "turn": self.turn,
            "difficulty": self.difficulty.id, "years": self.years,
            "rng": _rng_to_json(self.rng.getstate()),
            "portfolio": self.portfolio.to_dict(), "risk": self.risk.to_dict(),
            "incidents": self.incidents.to_dict(), "budget": self.budget.to_dict(),
            "compliance": self.compliance.to_dict(), "reputation": self.reputation.to_dict(),
            "events": self.events.to_dict(),
            "team": self.team.to_dict(), "vulns": self.vulns.to_dict(), "threat": self.threat.to_dict(),
            "phishing": self.phishing.to_dict(),
            "news": [n.to_dict() for n in self.news[-300:]],
            "decisions": [d.to_dict() for d in self.decisions],
            "mistakes": [m.to_dict() for m in self.mistakes],
            "missed_practices": list(self.missed_practices),
            "pending_events": list(self.pending_events),
            "pending_board": self.pending_board, "board_state": dict(self.board_state),
            "timeline": list(self.timeline),
            "game_over_reason": self.game_over_reason, "finished": self.finished,
            "contracts_lost": self.contracts_lost, "budget_flags": dict(self.budget_flags),
            "initial_risk": self.initial_risk,
            "trust": self.trust, "trust_history": [list(t) for t in self.trust_history],
            "prep_until": self.prep_until, "objectives": [dict(o) for o in self.objectives],
            "objective_flags": dict(self.objective_flags),
        }

    @classmethod
    def from_dict(cls, data: GameData, d: dict[str, Any], bus: EventBus | None = None) -> "Simulation":
        version = int(d.get("version", 0))
        if version not in (1, SAVE_VERSION):
            raise ValueError("Version de sauvegarde incompatible")
        sim = cls(data, d["org_id"], seed=int(d["seed"]), bus=bus,
                  difficulty=d.get("difficulty", DEFAULT_DIFFICULTY), years=int(d.get("years", config.GAME_YEARS)))
        sim.turn = int(d["turn"])
        sim.rng.setstate(_rng_from_json(d["rng"]))
        sim.portfolio.load_dict(d["portfolio"])
        sim.risk.load_dict(d["risk"])
        sim.incidents.load_dict(d["incidents"])
        sim.budget.load_dict(d["budget"])
        sim.compliance.load_dict(d["compliance"])
        sim.reputation.load_dict(d["reputation"])
        sim.events.load_dict(d["events"])
        if version >= 2:   # sauvegardes v1 : nouvelles mécaniques initialisées par défaut
            sim.team.load_dict(d["team"])
            sim.vulns.load_dict(d["vulns"])
            sim.threat.load_dict(d["threat"])
            sim.phishing.load_dict(d["phishing"])
            sim.pending_board = bool(d.get("pending_board", False))
            sim.board_state = dict(d.get("board_state", sim.board_state))
            sim.trust = float(d.get("trust", TRUST_INITIAL))
            sim.trust_history = [(int(t), float(v)) for t, v in d.get("trust_history", [])]
            sim.prep_until = int(d.get("prep_until", 0))
            sim.objectives = [o for o in d.get("objectives", []) if o.get("id") in OBJECTIVES]
            sim.objective_flags = dict(d.get("objective_flags", {}))
        sim.news = [NewsItem.from_dict(n) for n in d.get("news", [])]
        sim.decisions = [DecisionRecord.from_dict(x) for x in d.get("decisions", [])]
        sim.mistakes = [Mistake.from_dict(x) for x in d.get("mistakes", [])]
        sim.missed_practices = list(d.get("missed_practices", []))
        sim.pending_events = [e for e in d.get("pending_events", []) if e in data.events]
        sim.timeline = list(d.get("timeline", []))
        sim.game_over_reason = d.get("game_over_reason")
        sim.finished = bool(d.get("finished", False))
        sim.contracts_lost = int(d.get("contracts_lost", 0))
        sim.budget_flags = dict(d.get("budget_flags", {}))
        sim.initial_risk = float(d.get("initial_risk", sim.initial_risk))
        return sim


def _rng_to_json(state: tuple) -> list:
    version, internal, gauss = state
    return [version, list(internal), gauss]


def _rng_from_json(data: list) -> tuple:
    version, internal, gauss = data
    return (version, tuple(internal), gauss)


def new_game(org_id: str, seed: int | None = None, data: GameData | None = None,
             bus: EventBus | None = None, difficulty: str = DEFAULT_DIFFICULTY,
             years: int = config.GAME_YEARS) -> Simulation:
    from game.data_loader import get_data
    return Simulation(data or get_data(), org_id, seed=seed, bus=bus, difficulty=difficulty, years=years)
