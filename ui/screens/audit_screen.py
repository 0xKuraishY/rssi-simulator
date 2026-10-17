"""Conformité réglementaire : obligations, notifications en attente, contrôles, ISO 27001."""
from __future__ import annotations

import pygame

import config
from engine import renderer as R
from game.compliance_engine import ISO_PASS_THRESHOLD, ISO_SMSI_STEP_COST, OBLIGATIONS
from game.simulation import GameRuleError
from game.state import GameScreen
from ui.components.widgets import UI, section, split_h, split_v
from ui.screens.base import Screen

INSPECTION_LABELS = {"cnil": "Contrôle CNIL", "anssi": "Contrôle ANSSI (NIS2 / LPM)", "iso": "Audit ISO 27001"}


class AuditScreen(Screen):
    name = GameScreen.AUDIT.value

    def draw_content(self, ui: UI) -> None:
        sim = self.sim
        y = self.title(ui, "Conformité réglementaire", " · ".join(sim.org.regimes.labels))
        self.back_button(ui)
        area = pygame.Rect(16, y, self.size[0] - 32, self.size[1] - y - 16)
        left, mid, right = split_h(area, [0.36, 0.30, 0.34], gap=14)
        self._obligations(ui, left)
        top, bottom = split_v(mid, [0.58, 0.42], gap=12)
        self.regions.update(obligations=left, notifications=top, iso=right)
        self._notifications(ui, top)
        self._inspections(ui, bottom)
        self._iso(ui, right)

    def _obligations(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        status = sim.compliance.compliance_status(sim.turn, sim.active_measure_ids, sim.risk.study.completed_turn)
        ok = sum(1 for s in status if s["ok"])
        c = section(surf, rect, "Obligations permanentes", f"{ok}/{len(status)} satisfaites")
        off = ui.begin_scroll("oblig", c)
        y = c.y + off
        for s in status:
            p = s["def"]
            box = pygame.Rect(c.x, y, c.width - 12, 76)
            col = config.THEME["success"] if s["ok"] else config.THEME["danger"]
            R.panel(surf, box, "panel_alt", None)
            pygame.draw.rect(surf, col, (box.x, box.y, 5, box.height), border_radius=2)
            R.draw_text(surf, ("✓ " if s["ok"] else "✗ ") + p.label, (box.x + 14, box.y + 6), "small", col, "bold")
            R.draw_text(surf, p.reference, (box.x + 14, box.y + 26), 11, "text_muted")
            if not s["ok"]:
                cost = f" ({R.format_eur(p.cost)})" if p.cost else ""
                if ui.button(pygame.Rect(box.x + 14, box.y + 42, box.width - 28, 28), p.action + cost, "secondary",
                             size="small"):
                    if p.key == "nis2_analyse_risques":
                        self.app.switch(GameScreen.EBIOS)
                    else:
                        try:
                            sim.compliance_action(p.key)
                            self.app.audio.play("success")
                            self.app.autosave()
                        except GameRuleError as exc:
                            self.app.toast(str(exc), "warning")
            y += 84
        ui.end_scroll("oblig", c, y - (c.y + off))

    def _notifications(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        c = section(surf, rect, "Notifications d'incident",
                    f"taux dans les délais : {sim.compliance.notification_rate():.0%}")
        pending = [d for d in sim.compliance.state.deadlines if d.done_hour is None]
        off = ui.begin_scroll("notifs", c)
        y = c.y + off
        if not pending:
            R.draw_text(surf, "Aucune notification en attente.", (c.x, y), "small", "text_muted")
            y += 24
        for d in pending:
            o = OBLIGATIONS[d.kind]
            inc = sim.incidents.get(d.incident_uid)
            hours = sim.hours_since_detection(inc)
            late = hours > o.hours
            col = config.THEME["danger"] if late else config.THEME["warning"]
            R.draw_text(surf, f"{o.label}", (c.x, y), "small", "text", "bold")
            R.draw_text(surf, f"{d.incident_uid} · H+{hours} / échéance H+{o.hours}", (c.x, y + 18), 11, col)
            if ui.button(pygame.Rect(c.right - 120, y + 4, 108, 30), "Transmettre", "primary", size="small"):
                sim.notify_obligation(d.incident_uid, d.kind)
                self.app.autosave()
            y += 46
        done = [d for d in sim.compliance.state.deadlines if d.done_hour is not None]
        if done:
            y += 6
            R.draw_text(surf, "Historique", (c.x, y), "small", "accent", "bold")
            y += 22
            for d in done[-8:]:
                txt = f"{OBLIGATIONS[d.kind].label} — H+{d.done_hour} ({'à temps' if d.status == 'on_time' else 'hors délai'})"
                R.draw_text(surf, txt[:70], (c.x, y), 11, "success" if d.status == "on_time" else "warning")
                y += 18
        ui.end_scroll("notifs", c, y - (c.y + off))

    def _inspections(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        c = section(surf, rect, "Contrôles")
        y = c.y
        upcoming = sim.compliance.upcoming_inspections(sim.turn)
        R.draw_text(surf, "Planifiés / annoncés", (c.x, y), "small", "accent", "bold")
        y += 22
        visible = [i for i in upcoming if i.kind == "iso" or i.turn - sim.turn <= 4]
        if not visible:
            R.draw_wrapped(surf, "Aucun contrôle annoncé. Les contrôles CNIL et ANSSI peuvent survenir sans long préavis.",
                           pygame.Rect(c.x, y, c.width, 40), "small", "text_muted")
            y += 44
        for insp in visible[:3]:
            d = sim.calendar.format_date(sim.calendar.date_for(insp.turn))
            R.draw_text(surf, f"{INSPECTION_LABELS[insp.kind]} — {d}", (c.x, y), "small", "warning")
            y += 20
        y += 8
        R.draw_text(surf, "Réalisés", (c.x, y), "small", "accent", "bold")
        y += 22
        for insp in [i for i in sim.compliance.state.inspections if i.done][-5:]:
            col = "success" if insp.result == "conforme" else "danger"
            R.draw_text(surf, f"Sem. {insp.turn} · {INSPECTION_LABELS[insp.kind]} : {insp.result}", (c.x, y), "small", col)
            y += 20

    def _iso(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        controls = sim.measure_controls()
        covered = sim.compliance.iso_covered(controls)
        progress = sim.compliance.iso_progress(controls)
        c = section(surf, rect, "ISO/IEC 27001:2022 — Annexe A", f"{len(covered)}/93 contrôles")
        y = c.y
        ui.progress(pygame.Rect(c.x, y, c.width, 12), progress,
                    config.THEME["success"] if progress >= ISO_PASS_THRESHOLD else config.THEME["warning"])
        y += 22
        R.draw_text(surf, f"Seuil d'audit : {ISO_PASS_THRESHOLD:.0%} · certification : "
                          f"{'active' if 'M38' in sim.active_measure_ids else 'non'}", (c.x, y), "small", "text_muted")
        y += 28
        theme = None
        cell = max(16, min(26, (c.width - 10) // 14))
        x = c.x
        for ctrl in sim.data.iso_controls:
            if ctrl["theme"] != theme:
                theme = ctrl["theme"]
                if x != c.x:
                    y += cell + 4
                R.draw_text(surf, theme, (c.x, y), 11, "text_muted", "bold")
                y += 18
                x = c.x
            if x + cell > c.right:
                x = c.x
                y += cell + 4
            r = pygame.Rect(x, y, cell, cell)
            ok = ctrl["id"] in covered
            pygame.draw.rect(surf, config.THEME["success"] if ok else config.THEME["panel_alt"], r, border_radius=3)
            pygame.draw.rect(surf, config.THEME["border"], r, 1, border_radius=3)
            ui.tooltip(r, f"{ctrl['id']} {ctrl['titre']} — {'couvert' if ok else 'non couvert'}")
            x += cell + 4
        y += cell + 16
        R.draw_wrapped(surf, "Les contrôles sont couverts par les mesures déployées et par les travaux documentaires "
                             "du SMSI (politiques, procédures, revues).", pygame.Rect(c.x, y, c.width, 50), "small",
                       "text_muted")
        if ui.button(pygame.Rect(c.x, c.bottom - 46, c.width, 44),
                     f"Travaux SMSI : +5 contrôles ({R.format_eur(ISO_SMSI_STEP_COST)})", "secondary",
                     enabled=sim.budget.can_afford(ISO_SMSI_STEP_COST) and len(covered) < 93):
            try:
                sim.iso_smsi_step()
                self.app.autosave()
            except GameRuleError as exc:
                self.app.toast(str(exc), "warning")
