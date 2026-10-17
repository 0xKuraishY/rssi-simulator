"""Tableau de bord : indicateurs, carte du SI, fil d'actualité, objectifs, actions."""
from __future__ import annotations

import math

import pygame

import config
from engine import renderer as R
from game.governance import OBJECTIVE_STATUS_LABELS, OBJECTIVES, objective_text
from game.organisation import INCIDENT_TYPE_LABELS
from game.reputation_engine import DIMENSION_LABELS
from game.risk_engine import RISK_LABELS
from game.simulation import GameRuleError
from game.state import GameScreen
from ui.components.dialog_box import DialogBox, DialogButton
from ui.components.hud import reputation_color
from ui.components.iso_map import IsoMap
from ui.components.risk_matrix import MatrixItem, draw_matrix
from ui.components.widgets import UI, section, severity_color, split_h, split_v
from ui.screens.base import Screen

SHORT_TYPES = {
    "ransomware": "RAN", "phishing": "PHI", "fuite_donnees": "FUI", "supply_chain": "SUP", "vpn_exploit": "VPN",
    "ddos": "DDS", "initie": "INI", "double_extorsion": "DBX", "compromission_cloud": "CLD", "ot_iot": "OT",
}
CATEGORY_LABELS = {
    "incident": "Incident", "budget": "Budget", "conformite": "Conformité", "reputation": "Réputation",
    "evenement": "Événement", "mesure": "Mesure", "ebios": "EBIOS RM", "organisation": "Organisation",
    "operations": "Opérations", "menace": "Veille", "direction": "Direction",
}
THREAT_COLORS = {"Modéré": config.THEME["success"], "Élevé": config.THEME["warning"],
                 "Très élevé": config.THEME["danger"]}
OBJ_COLORS = {"en_cours": config.THEME["accent"], "reussi": config.THEME["success"], "echoue": config.THEME["danger"]}
SAVE_SLOTS = ("slot1", "slot2", "slot3")


class DashboardScreen(Screen):
    name = GameScreen.DASHBOARD.value

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.t = 0.0
        self._event_dialog_for: str | None = None
        self._board_open = False
        self.map_view = "3d"
        self.center_tab = "objectifs"
        self.iso = IsoMap()

    def on_enter(self, **kwargs: object) -> None:
        self._board_open = False

    def update(self, dt: float) -> None:
        self.t += dt
        sim = self.app.sim
        if sim is None:
            return
        if sim.finished:
            self.app.switch(GameScreen.GAME_OVER)
            return
        net = self.app.net
        if net is not None and net.waiting_for is not None and net.waiting_for == sim.turn:
            if net.may_advance(sim.turn):
                net.waiting_for = None
                self._next_week()
                return
        if self.app.dialogs.active or self.app.overlay_active:
            return
        if sim.pending_events and self._event_dialog_for != sim.pending_events[0]:
            self._open_event(sim.pending_events[0])
        elif sim.pending_board and not sim.pending_events and not self._board_open:
            self._open_board()

    # -- dialogues -------------------------------------------------------------------
    def _open_event(self, event_id: str) -> None:
        sim = self.sim
        ev = sim.data.events[event_id]
        self._event_dialog_for = event_id
        buttons = []
        for c in ev.choix:
            ok, reason = sim.event_choice_available(event_id, c.id)
            cost = c.effets.get("cout")
            label = c.texte + (f"  ({R.format_eur(float(cost))})" if cost else "")

            def act(cid: str = c.id) -> None:
                try:
                    res = sim.resolve_event(event_id, cid)
                except GameRuleError as exc:
                    self.app.toast(str(exc), "danger")
                    self._event_dialog_for = None
                    return
                ch = res["choice"]
                sev = {"bonne": "success", "moyenne": "warning", "mauvaise": "danger"}[ch.qualite]
                body = ch.feedback + (f"\n\nRéférence : {ch.reference}" if ch.reference else "")
                self.app.dialogs.info(f"Décision {ch.qualite}", body, sev)
                self.app.autosave()
                self._event_dialog_for = None
            buttons.append(DialogButton(label, act, "secondary", ok, reason or None))
        self.app.dialogs.push(DialogBox(ev.titre, ev.description, buttons, subtitle=ev.de or ev.categorie.capitalize(),
                                        accent=config.THEME["warning"], width=860, vertical_buttons=True))

    def _open_board(self) -> None:
        sim = self.sim
        self._board_open = True
        buttons = []
        for opt in sim.board_options():
            label = opt["label"]
            if opt["id"] in ("rallonge", "recrutement") and sim.difficulty.show_probabilities:
                label += f"  (chances : {opt['probability']:.0%})"

            def act(oid: str = opt["id"]) -> None:
                try:
                    res = sim.resolve_board(oid)
                except GameRuleError as exc:
                    self.app.toast(str(exc), "danger")
                    self._board_open = False
                    return
                self.app.dialogs.info("Décision du comité", res["message"], "success" if res["success"] else "warning")
                self.app.autosave()
                self._board_open = False
            buttons.append(DialogButton(label, act, "secondary", opt["available"], opt["detail"]))
        self.app.dialogs.push(DialogBox(
            "Comité de direction trimestriel", sim.board_summary() + "\n\nQue présentez-vous au comité ?",
            buttons, subtitle=f"Semaine {sim.turn} — {sim.org.nom}", accent=config.THEME["accent"], width=860,
            vertical_buttons=True))

    def _open_save(self) -> None:
        infos = {s.slot: s for s in self.app.saves.list_saves()}
        buttons = []
        for i, slot in enumerate(SAVE_SLOTS, 1):
            info = infos.get(slot)
            label = f"Emplacement {i} — " + (info.label if info else "libre")

            def act(sl: str = slot, n: int = i) -> None:
                self.app.autosave(sl)
                self.app.toast(f"Partie sauvegardée dans l'emplacement {n}", "success")
            buttons.append(DialogButton(label, act, "secondary"))
        buttons.append(DialogButton("Annuler", None, "ghost"))
        self.app.dialogs.push(DialogBox("Sauvegarder la partie",
                                        "La sauvegarde automatique est faite à chaque semaine. Vous pouvez aussi "
                                        "conserver la partie dans un emplacement dédié.", buttons, width=760,
                                        vertical_buttons=True))

    # -- action principale -----------------------------------------------------------
    def _request_next_week(self) -> None:
        net = self.app.net
        if net is not None and net.synchronized and not net.disconnected:
            net.ready(self.sim.turn)
            if not net.may_advance(self.sim.turn):
                self.app.toast("Prêt : en attente des autres joueurs", "info")
                return
            net.waiting_for = None
        self._next_week()

    def _next_week(self) -> None:
        sim = self.sim
        try:
            report = sim.next_turn()
        except GameRuleError as exc:
            self.app.toast(str(exc), "warning")
            return
        self.app.autosave()
        if report.game_over:
            self.app.switch(GameScreen.GAME_OVER)
            return
        if report.detected:
            self.app.toast("Incident détecté : ouverture de la salle de crise", "danger")
            self.app.switch(GameScreen.INCIDENT, incident=report.detected[0])
            return
        if sim.calendar.is_year_start(sim.turn):
            self.app.dialogs.info(f"Nouvel exercice — année {sim.year}",
                                  f"Le budget SSI de l'année est de {R.format_eur(sim.budget.budget_annuel_ssi)}. "
                                  "Les maintenances des mesures en place ont été imputées.", "info")

    # -- dessin ------------------------------------------------------------------------
    def draw_content(self, ui: UI) -> None:
        sim = self.sim
        left, center, right = split_h(self.content_rect(), [0.29, 0.43, 0.28], gap=14)
        self._indicators(ui, left)
        self._center(ui, center)
        self._actions(ui, right)
        waiting = self.app.net is not None and self.app.net.waiting_for is not None
        if ui.key(pygame.K_SPACE, pygame.K_RETURN) and not self.app.dialogs.active and sim.can_advance() \
                and not waiting:
            self._request_next_week()

    def _indicators(self, ui: UI, rect: pygame.Rect) -> None:
        sim = self.sim
        surf = ui.surface
        top, bottom = split_v(rect, [0.56, 0.44], gap=12)
        self.regions["indicators"] = top
        self.regions["map"] = bottom
        c = section(surf, top, "Indicateurs", sim.current_date_label())
        y = c.y
        b = sim.budget
        R.draw_text(surf, "Budget SSI restant", (c.x, y), "small", "text_muted")
        R.draw_text(surf, f"{R.format_eur(b.remaining)} / {R.format_eur(b.budget_annuel_ssi)}", (c.right, y), "small",
                    "text", "bold", anchor="topright")
        ui.progress(pygame.Rect(c.x, y + 20, c.width, 8), b.remaining / max(1, b.budget_annuel_ssi),
                    config.THEME["success"] if b.remaining > 0.2 * b.budget_annuel_ssi else config.THEME["warning"])
        y += 36
        gauges = [(label, sim.reputation.values[dim]) for dim, label in DIMENSION_LABELS.items()]
        gauges.append(("Confiance de la direction", sim.trust))
        row_h = max(26, min(34, (c.bottom - y - 50) // len(gauges)))
        for label, v in gauges:
            R.draw_text(surf, label, (c.x, y), "small", "text_muted")
            R.draw_text(surf, f"{v:.0f}", (c.right, y), "small", reputation_color(v), "bold", anchor="topright")
            ui.progress(pygame.Rect(c.x, y + 18, c.width, 6), v / 100, reputation_color(v))
            y += row_h
        ui.tooltip(pygame.Rect(c.x, y - row_h, c.width, row_h),
                   f"Sous {sim.difficulty.dismissal_threshold:.0f}/100, la direction met fin à vos fonctions.")
        g = sim.reputation.global_score()
        R.draw_text(surf, "Réputation globale", (c.x, y + 2), "body", "text", "bold")
        R.draw_text(surf, f"{g:.0f}/100", (c.right, y + 2), "body", reputation_color(g), "bold", anchor="topright")
        y += 28
        intensity, level = sim.threat.level(sim.turn)
        badge = pygame.Rect(c.x, y, c.width, 22)
        R.draw_text(surf, "Niveau de menace :", (c.x, y + 2), "small", "text_muted")
        R.draw_text(surf, level, (c.right, y + 2), "small", THREAT_COLORS[level], "bold", anchor="topright")
        camps = sim.threat.active_campaigns(sim.turn)
        ui.tooltip(badge, " · ".join(cp.titre for cp in camps) or "Aucune campagne particulière signalée.")

        level_r, cat = sim.global_risk()
        title = "Carte du SI" if self.map_view == "3d" else "Matrice des risques"
        c2 = section(surf, bottom, title)
        pygame.draw.rect(surf, config.RISK_COLORS[cat], (bottom.x, bottom.y, 6, bottom.height), border_radius=3)
        toggle = pygame.Rect(bottom.right - 112, bottom.y + 10, 100, 26)
        R.draw_text(surf, f"Risque global : {RISK_LABELS[cat].lower()} ({level_r}/16)", (c2.x + 2, c2.y - 6), 11,
                    config.RISK_COLORS[cat], "bold")
        c2 = pygame.Rect(c2.x, c2.y + 12, c2.width, c2.height - 12)
        if self.map_view == "3d":
            self.iso.draw(ui, pygame.Rect(c2.x, c2.y, c2.width, c2.height - 4), sim, self.t)
        else:
            items = []
            for t, (v, gg) in sim.risk.risk_matrix(sim.turn).items():
                tip = f"{INCIDENT_TYPE_LABELS[t]} — vraisemblance V{v}, gravité G{gg}"
                if sim.difficulty.show_probabilities:
                    tip += f", probabilité annuelle estimée {sim.risk.annual_probability(t, sim.turn):.0%}"
                items.append(MatrixItem(t, SHORT_TYPES[t], v, gg, tip))
            draw_matrix(ui, pygame.Rect(c2.x, c2.y, c2.width, c2.height - 4), items, compact=True)
        if ui.button(toggle, "Matrice" if self.map_view == "3d" else "Carte 3D", "ghost", size="small"):
            self.map_view = "matrice" if self.map_view == "3d" else "3d"

    def _center(self, ui: UI, rect: pygame.Rect) -> None:
        news_r, low = split_v(rect, [0.60, 0.40], gap=12)
        self.regions["news"] = news_r
        self.regions["objectives"] = low
        self._news(ui, news_r)
        surf = ui.surface
        tabs = ["objectifs"] + (["classement"] if self.app.net is not None else [])
        title = "Objectifs de mandat" if self.center_tab == "objectifs" else "Classement de la session"
        c = section(surf, low, title)
        if len(tabs) > 1:
            x = low.right - 12
            for tab in reversed(tabs):
                r = pygame.Rect(x - 110, low.y + 8, 104, 28)
                if ui.button(r, tab.capitalize(), "selected" if tab == self.center_tab else "ghost", size="small"):
                    self.center_tab = tab
                x -= 112
        if self.center_tab == "classement" and self.app.net is not None:
            self._leaderboard(ui, c)
        else:
            self._objectives(ui, c)

    def _objectives(self, ui: UI, c: pygame.Rect) -> None:
        surf = ui.surface
        y = c.y
        row_h = max(30, (c.height - 4) // max(1, len(self.sim.objectives)))
        for obj in self.sim.objectives:
            d = OBJECTIVES[obj["id"]]
            col = OBJ_COLORS[obj["status"]]
            pygame.draw.rect(surf, col, (c.x, y + 2, 4, row_h - 8), border_radius=2)
            R.draw_text_fit(surf, d.titre, (c.x + 12, y), c.width - 120, "body", "text", "bold")
            R.draw_text(surf, OBJECTIVE_STATUS_LABELS[obj["status"]], (c.right, y + 2), "small", col, "bold",
                        anchor="topright")
            R.draw_wrapped(surf, objective_text(obj), pygame.Rect(c.x + 12, y + 22, c.width - 12, row_h - 24),
                           "small", "text_muted", line_spacing=1)
            y += row_h

    def _leaderboard(self, ui: UI, c: pygame.Rect) -> None:
        surf = ui.surface
        net = self.app.net
        me = net.my_id()
        y = c.y
        for rank, p in enumerate(net.leaderboard()[:8], 1):
            mine = p.player_id == me
            col = "accent" if mine else ("text" if p.connected else "text_muted")
            R.draw_text(surf, f"{rank}.", (c.x, y), "body", col, "bold")
            R.draw_text_fit(surf, p.name + ("" if p.connected else " (déconnecté)"), (c.x + 34, y), c.width * 0.45,
                            "body", col, "bold" if mine else "regular")
            R.draw_text(surf, f"sem. {p.turn}" + (" ✓" if p.finished else ""), (c.x + c.width * 0.58, y), "small",
                        "text_muted")
            R.draw_text(surf, f"{p.score:.0f}", (c.right, y), "body", col, "bold", anchor="topright")
            y += 26
        if net.synchronized:
            R.draw_text(surf, "Mode synchronisé : la semaine avance quand tous sont prêts.", (c.x, c.bottom - 18),
                        11, "text_muted")

    def _news(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        c = section(surf, rect, "Fil d'actualité", f"{len(self.sim.news)} événements")
        off = ui.begin_scroll("news", c)
        y = c.y + off
        for item in reversed(self.sim.news[-120:]):
            text_rect = pygame.Rect(c.x + 14, y + 20, c.width - 26, 200)
            h = R.measure_wrapped(item.text, text_rect.width, "body", line_spacing=2)
            if y + h + 34 >= c.y and y <= c.bottom:   # ne dessine que la partie visible
                pygame.draw.rect(surf, severity_color(item.severity), (c.x, y + 2, 4, h + 18), border_radius=2)
                R.draw_text(surf, f"Semaine {item.turn} · {CATEGORY_LABELS.get(item.category, item.category)}",
                            (c.x + 14, y), "small", "text_muted")
                R.draw_wrapped(surf, item.text, pygame.Rect(text_rect.x, text_rect.y, text_rect.width, h + 4), "body",
                               line_spacing=2)
            y += h + 34
        ui.end_scroll("news", c, y - (c.y + off))

    def _actions(self, ui: UI, rect: pygame.Rect) -> None:
        sim = self.sim
        surf = ui.surface
        c = section(surf, rect, "Actions", sim.difficulty.nom)
        x, y, w = c.x, c.y, c.width
        crises = sim.active_crises()
        if crises:
            pulse = 0.5 + 0.5 * math.sin(self.t * 6)
            r = pygame.Rect(x, y, w, 50)
            pygame.draw.rect(surf, R.blend((120, 20, 30), (248, 81, 73), pulse), r.inflate(6, 6), border_radius=8)
            if ui.button(r, f"SALLE DE CRISE ({len(crises)})", "danger"):
                self.app.switch(GameScreen.INCIDENT, incident=crises[0].uid)
            y += 60
        if sim.pending_events or sim.pending_board:
            if ui.button(pygame.Rect(x, y, w, 40), "Décision en attente", "danger"):
                self._event_dialog_for = None
                self._board_open = False
            y += 48
        crit = len([v for v in sim.vulns.critical_exposed() if v.visible])
        actions = [
            ("Analyser les risques (EBIOS RM)", GameScreen.EBIOS, "Méthode EBIOS Risk Manager de l'ANSSI, 5 ateliers"),
            ("Gérer le budget", GameScreen.BUDGET, "Répartition, catalogue de mesures, simulateur de ROI"),
            ("Vérifier la conformité", GameScreen.AUDIT, "RGPD, NIS2, ISO 27001, contrôles à venir"),
            ("Opérations SSI" + (f"  ({crit} critique{'s' if crit > 1 else ''})" if crit else ""),
             GameScreen.OPERATIONS, "Vulnérabilités, équipe SSI, hameçonnage, veille sur la menace"),
        ]
        bh = 42 if c.height < 600 else 46
        self.regions["actions"] = pygame.Rect(x - 4, y - 4, w + 8, len(actions) * (bh + 8) + 4)
        for label, target, tip in actions:
            style = "danger" if target == GameScreen.OPERATIONS and crit else "secondary"
            if ui.button(pygame.Rect(x, y, w, bh), label, style, tooltip=tip):
                self.app.switch(target)
            y += bh + 8
        blocking = sim.blocking_reasons()
        net = self.app.net
        waiting = net is not None and net.waiting_for is not None
        label = "En attente des autres joueurs…" if waiting else "Passer à la semaine suivante  ▶"
        self.regions["next"] = pygame.Rect(x, y, w, 52)
        if ui.button(pygame.Rect(x, y, w, 52), label, "primary", enabled=not blocking and not waiting,
                     tooltip=blocking[0] if blocking else "Raccourci : Espace"):
            self._request_next_week()
        y += 64

        team = sim.team
        self.regions["team"] = pygame.Rect(x - 4, y - 4, w + 8, 34)
        cap = team.capacity(sim.turn, sim.in_crisis)
        used = team.state.used + sim.deployment_load()
        R.draw_text(surf, f"Équipe SSI : {team.state.members} pers. · charge {used:.1f}/{cap:.1f} j·h", (x, y), "small",
                    "text_muted")
        ui.progress(pygame.Rect(x, y + 18, w, 6), used / max(0.1, cap),
                    config.THEME["danger"] if used > cap else config.THEME["accent"])
        y += 32
        R.draw_text(surf, "Mesures en déploiement", (x, y), "small", "text", "bold")
        y += 20
        in_progress = sim.portfolio.in_progress(sim.turn)
        if not in_progress:
            R.draw_text(surf, "Aucune", (x, y), "small", "text_muted")
            y += 20
        for st in in_progress[:4]:
            if y > rect.bottom - 120:
                break
            m = sim.data.measures[st.measure_id]
            total = max(1, st.ready_turn - st.ordered_turn)
            R.draw_text_fit(surf, m.nom, (x, y), w, "small", "text")
            ui.progress(pygame.Rect(x, y + 17, w, 5), (sim.turn - st.ordered_turn) / total)
            y += 28
        upcoming = [i for i in sim.compliance.upcoming_inspections(sim.turn) if i.kind == "iso" or i.turn - sim.turn <= 4]
        labels = {"cnil": "Contrôle CNIL", "anssi": "Contrôle ANSSI", "iso": "Audit ISO 27001"}
        for insp in upcoming[:2]:
            if y > rect.bottom - 100:
                break
            d = sim.calendar.format_date(sim.calendar.date_for(insp.turn))
            R.draw_text_fit(surf, f"{labels[insp.kind]} — {d}", (x, y), w, "small", "warning")
            y += 20

        half = (w - 8) // 2
        if ui.button(pygame.Rect(x, rect.bottom - 54, half, 40), "Sauvegarder", "ghost"):
            self._open_save()
        if ui.button(pygame.Rect(x + half + 8, rect.bottom - 54, half, 40), "Menu", "ghost"):
            self.app.autosave()
            self.app.switch(GameScreen.MENU)
