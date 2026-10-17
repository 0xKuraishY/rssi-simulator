"""Opérations SSI : vulnérabilités, équipe, hameçonnage et veille sur la menace."""
from __future__ import annotations

import pygame

import config
from engine import renderer as R
from game.operations import PHISHING_CAMPAIGN_COST, VULN_ACTIONS
from game.organisation import INCIDENT_TYPE_LABELS
from game.simulation import PHISHING_CAMPAIGN_JH, GameRuleError
from game.state import GameScreen
from ui.components.widgets import UI, section, split_h, split_v
from ui.screens.base import Screen

STATUS_LABELS = {"ouverte": "Ouverte", "planifiee": "Correctif planifié", "contournee": "Contournée",
                 "corrigee": "Corrigée", "acceptee": "Risque accepté"}
FILTERS = [("ouvertes", "À traiter"), ("toutes", "Historique")]
ACTION_SHORT = {"urgence": "Urgence", "planifier": "Planifier", "contourner": "Contourner", "accepter": "Accepter"}


class OperationsScreen(Screen):
    name = GameScreen.OPERATIONS.value

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.filter = "ouvertes"

    def _do(self, func, *args, ok: str = "") -> None:  # type: ignore[no-untyped-def]
        try:
            func(*args)
            if ok:
                self.app.toast(ok, "success")
            self.app.audio.play("click")
            self.app.autosave()
        except GameRuleError as exc:
            self.app.toast(str(exc), "warning")

    def draw_content(self, ui: UI) -> None:
        sim = self.sim
        y = self.title(ui, "Opérations SSI", "Le quotidien de l'équipe : correctifs, charge de travail, vigilance")
        self.back_button(ui)
        area = pygame.Rect(16, y, self.size[0] - 32, self.size[1] - y - 16)
        left, right = split_h(area, [0.6, 0.4], gap=14)
        self._vulns(ui, left)
        team_r, phish_r, threat_r = split_v(right, [0.42, 0.28, 0.30], gap=12)
        self.regions.update(vulns=left, team=team_r, phishing=phish_r, threat=threat_r)
        self._team(ui, team_r)
        self._phishing(ui, phish_r)
        self._threat(ui, threat_r)

    # -- vulnérabilités ------------------------------------------------------------------
    def _vulns(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        visible_open = sim.vulns.open_items(visible_only=True)
        c = section(surf, rect, "Vulnérabilités (veille CERT-FR)", f"{len(visible_open)} non corrigée(s)")
        x = c.x
        for key, label in FILTERS:
            if ui.button(pygame.Rect(x, c.y, 140, 30), label, "selected" if self.filter == key else "ghost",
                         size="small"):
                self.filter = key
            x += 148
        mttp = sim.vulns.mean_time_to_patch()
        R.draw_text(surf, "Délai moyen de correction : " + (f"{mttp:.1f} sem." if mttp is not None else "—"),
                    (c.right, c.y + 6), "small", "text_muted", anchor="topright")
        items = [v for v in sim.vulns.items if v.visible and (self.filter == "toutes" or v.status in
                                                                ("ouverte", "acceptee", "contournee"))]
        items.sort(key=lambda v: (v.status != "ouverte", sim.vulns.definition(v).gravite != "critique",
                                  sim.vulns.definition(v).exposition != "internet", v.discovered))
        list_r = pygame.Rect(c.x, c.y + 40, c.width, c.height - 66)
        off = ui.begin_scroll("vulns", list_r)
        yy = list_r.y + off
        if not items:
            R.draw_wrapped(surf, "Aucune vulnérabilité connue à traiter. Sans scan de vulnérabilités (M26) ni "
                                 "cartographie (M40), certaines failles restent invisibles jusqu'à leur exploitation.",
                           pygame.Rect(list_r.x, yy, list_r.width - 12, 80), "body", "text_muted")
            yy += 80
        for v in items:
            d = sim.vulns.definition(v)
            box = pygame.Rect(list_r.x, yy, list_r.width - 12, 104)
            critical = d.gravite == "critique"
            col = config.THEME["danger"] if critical and d.exposition == "internet" else (
                config.THEME["warning"] if critical else config.THEME["accent"])
            R.panel(surf, box, "panel_alt", None)
            pygame.draw.rect(surf, col, (box.x, box.y, 5, box.height), border_radius=2)
            R.draw_text(surf, d.id, (box.x + 14, box.y + 6), "body", "text", "bold")
            tags = [("CRITIQUE" if critical else "ÉLEVÉE", col),
                    ("Exposée Internet" if d.exposition == "internet" else "Réseau interne", config.THEME["text_muted"])]
            if d.exploitee:
                tags.append(("Exploitée activement", config.THEME["danger"]))
            tx = box.x + 14 + R.font("body", "bold").size(d.id)[0] + 12
            for label, tcol in tags:
                tw = R.font(11, "bold").size(label)[0] + 14
                pygame.draw.rect(surf, tcol, (tx, box.y + 8, tw, 18), 1, border_radius=9)
                R.draw_text(surf, label, (tx + tw // 2, box.y + 17), 11, tcol, "bold", anchor="center")
                tx += tw + 6
            age = sim.turn - v.discovered
            R.draw_text(surf, f"{STATUS_LABELS[v.status]} · {age} sem.", (box.right - 10, box.y + 8), "small",
                        "text_muted", anchor="topright")
            R.draw_text_fit(surf, f"{d.produit} — {d.titre}", (box.x + 14, box.y + 32), box.width - 28, "small", "text")
            R.draw_text(surf, f"Menace associée : {INCIDENT_TYPE_LABELS[d.type]} · correction {d.charge_jh:g} j·h"
                              + (" · interruption de service" if d.arret else ""), (box.x + 14, box.y + 52), 11,
                        "text_muted")
            if v.status in ("ouverte", "acceptee", "contournee"):
                bx = box.x + 14
                bw = (box.width - 28 - 18) // 4
                for action in VULN_ACTIONS:
                    if (action, v.status) in (("accepter", "acceptee"), ("contourner", "contournee")):
                        continue
                    jh = sim.vulns.action_cost(v.uid, action)
                    style = "danger" if action == "urgence" and critical and d.exposition == "internet" else "ghost"
                    tip = VULN_ACTIONS[action] + (f" — {jh:g} j·h" if jh else " — aucune charge, risque conservé")
                    if ui.button(pygame.Rect(bx, box.y + 70, bw, 28), ACTION_SHORT[action], style, size="small",
                                 tooltip=tip):
                        self._do(sim.vuln_action, v.uid, action)
                    bx += bw + 6
            elif v.due_turn:
                R.draw_text(surf, f"Correctif prévu en semaine {v.due_turn}", (box.x + 14, box.y + 76), "small",
                            "accent")
            yy += 112
        ui.end_scroll("vulns", list_r, yy - (list_r.y + off))
        hidden = len([v for v in sim.vulns.open_items() if not v.visible])
        R.draw_text(surf, "Vulnérabilités non détectées : inconnues (un audit ou un scan peut en révéler)"
                    if hidden else "Visibilité : bonne", (c.x, c.bottom - 18), 11, "text_muted")

    # -- équipe -------------------------------------------------------------------------------
    def _team(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        team = sim.team
        c = section(surf, rect, "Équipe SSI", f"{team.state.members} personne(s)")
        cap = team.capacity(sim.turn, sim.in_crisis)
        used = team.state.used
        load = sim.deployment_load()
        y = c.y
        R.draw_text(surf, f"Capacité cette semaine : {cap:.1f} j·h" + (" (crise en cours : −40 %)" if sim.in_crisis else ""),
                    (c.x, y), "small", "text")
        y += 22
        total = used + load
        ui.progress(pygame.Rect(c.x, y, c.width, 10), total / max(0.1, cap),
                    config.THEME["danger"] if total > cap else config.THEME["accent"])
        y += 16
        R.draw_text(surf, f"Actions : {used:.1f} j·h · déploiements en cours : {load:.1f} j·h", (c.x, y), 11,
                    "text_muted")
        y += 20
        if team.state.overload_weeks:
            R.draw_text(surf, f"Surcharge depuis {team.state.overload_weeks} semaine(s) — risque d'épuisement",
                        (c.x, y), "small", "danger", "bold")
            y += 22
        if sim.turn < team.state.reinforcement_until:
            R.draw_text(surf, f"Renfort en régie jusqu'à la semaine {team.state.reinforcement_until}", (c.x, y),
                        "small", "success")
            y += 22
        for arrival in team.state.pending_recruits:
            R.draw_text(surf, f"Recrutement : arrivée prévue semaine {arrival}", (c.x, y), "small", "success")
            y += 22
        cost = team.reinforcement_cost()
        if ui.button(pygame.Rect(c.x, c.bottom - 40, c.width, 38),
                     f"Renfort consultant 8 semaines ({R.format_eur(cost)})", "secondary",
                     enabled=sim.budget.can_afford(cost) and sim.turn >= team.state.reinforcement_until,
                     tooltip="+2 j·h par semaine pendant 8 semaines. Un recrutement se demande au comité de direction."):
            self._do(sim.hire_reinforcement, ok="Renfort engagé")

    # -- hameçonnage ----------------------------------------------------------------------------
    def _phishing(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        c = section(surf, rect, "Vigilance du personnel")
        last = sim.phishing.last_measure()
        y = c.y
        if last:
            t, rate = last
            col = config.THEME["success"] if rate < 0.08 else (config.THEME["warning"] if rate < 0.15 else
                                                               config.THEME["danger"])
            R.draw_text(surf, f"{rate:.1%}", (c.x, y), "h1", col, "bold")
            R.draw_text(surf, f"taux de clic mesuré en semaine {t}", (c.x + 130, y + 14), "small", "text_muted")
        else:
            R.draw_text(surf, "Taux de clic inconnu", (c.x, y + 6), "h3", "text_muted", "bold")
        y += 46
        help_text = ("La sensibilisation (M01) réduit le taux chaque trimestre ; une campagne de faux hameçonnage "
                     "le mesure et entraîne le personnel.")
        if c.bottom - 42 - y >= 28:
            R.draw_wrapped(surf, help_text, pygame.Rect(c.x, y, c.width, c.bottom - 42 - y), 11, "text_muted")
        if ui.button(pygame.Rect(c.x, c.bottom - 38, c.width, 36),
                     f"Lancer une campagne ({R.format_eur(PHISHING_CAMPAIGN_COST)}, {PHISHING_CAMPAIGN_JH:g} j·h)",
                     "secondary", enabled=sim.budget.can_afford(PHISHING_CAMPAIGN_COST), tooltip=help_text):
            self._do(sim.run_phishing_campaign)

    # -- menace -----------------------------------------------------------------------------------
    def _threat(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        intensity, level = sim.threat.level(sim.turn)
        c = section(surf, rect, "Veille sur la menace", f"niveau {level.lower()}")
        camps = sim.threat.active_campaigns(sim.turn)
        y = c.y
        if not camps:
            R.draw_wrapped(surf, "Aucune campagne particulière ne vise votre secteur actuellement.",
                           pygame.Rect(c.x, y, c.width, 40), "small", "text_muted")
        for cp in camps:
            until = next(a["until"] for a in sim.threat.active if a["id"] == cp.id)
            R.draw_text_fit(surf, cp.titre, (c.x, y), c.width, "small", "warning", "bold")
            y += 20
            y += R.draw_wrapped(surf, f"{cp.texte} (jusqu'à la semaine {until})", pygame.Rect(c.x, y, c.width, 60),
                                11, "text_muted", line_spacing=1) + 8
