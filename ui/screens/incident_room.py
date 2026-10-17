"""Salle de crise : messages des équipes, décisions horodatées, délais réglementaires."""
from __future__ import annotations

import math
import random

import pygame

import config
from engine import renderer as R
from game.compliance_engine import OBLIGATIONS
from game.incident_engine import PHASE_LABELS, Phase
from game.risk_engine import severity_from_dict
from game.state import GameScreen
from ui.components.timeline import draw_phase_timeline
from ui.components.widgets import UI, split_h
from ui.screens.base import MARGIN, Screen

PHASE_KEYS = {Phase.DETECTION: "detection", Phase.CONFINEMENT: "confinement", Phase.ERADICATION: "eradication",
              Phase.REPRISE: "reprise", Phase.REX: "rex"}
QUALITY_COLORS = {"bonne": config.THEME["success"], "moyenne": config.THEME["warning"],
                  "mauvaise": config.THEME["danger"]}


class IncidentRoomScreen(Screen):
    name = GameScreen.INCIDENT.value
    show_hud = False

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.uid: str | None = None
        self.t = 0.0
        self.timer: float | None = None
        self.timer_for: str | None = None
        self.feedback: dict | None = None
        self.messages: dict[str, list[dict[str, str]]] = {}
        self.rng = random.Random(7)
        self.closing_result: dict | None = None

    # -- cycle de vie ------------------------------------------------------------------
    def on_enter(self, incident: str | None = None, **kwargs: object) -> None:
        crises = self.sim.active_crises()
        self.uid = incident or (crises[0].uid if crises else None)
        self.feedback = None
        self.closing_result = None
        self.timer = None
        self.timer_for = None
        if self.uid and self.uid not in self.messages:
            self._seed_messages()

    def _incident(self):  # type: ignore[no-untyped-def]
        return self.sim.incidents.get(self.uid) if self.uid else None

    def _seed_messages(self) -> None:
        inc = self._incident()
        t = self.sim.incidents.template(inc)
        msgs = [{"de": "SOC / Supervision", "texte": f"Alerte : {t.title}.", "h": "H+0"}]
        for m in t.messages.get("detection", []):
            msgs.append({**m, "h": "H+0"})
        for d in inc.decisions_taken:
            msgs.append({"de": "RSSI (vous)", "texte": self._choice_text(inc, d), "h": f"H+{d['hour']}", "me": "1"})
        self.messages[inc.uid] = msgs

    def _choice_text(self, inc, d) -> str:  # type: ignore[no-untyped-def]
        t = self.sim.incidents.template(inc)
        for dec in t.decisions:
            if dec.id == d["decision_id"]:
                return dec.choice(d["choice_id"]).texte
        return ""

    def _add_phase_messages(self, phase: Phase, hour: int) -> None:
        inc = self._incident()
        t = self.sim.incidents.template(inc)
        pool = t.messages.get(PHASE_KEYS.get(phase, ""), [])
        if not pool:
            return
        context = {"organisation": self.sim.org.nom, "secteur": self.sim.org.secteur, "incident": t.title,
                   "phase": PHASE_LABELS[phase], "heure": hour, "emetteur": pool[0].get("de", "Équipe")}
        msg = self.app.narrator.team_message(context, pool)
        self.messages[inc.uid].append({**msg, "h": f"H+{hour}"})

    # -- décisions --------------------------------------------------------------------------
    def _decide(self, decision_id: str, choice_id: str, auto: bool = False) -> None:
        inc = self._incident()
        result = self.sim.crisis_decide(inc.uid, decision_id, choice_id)
        ch = result["choice"]
        self.messages[inc.uid].append({"de": "RSSI (vous)", "texte": ch.texte, "h": f"H+{inc.crisis_hour}", "me": "1"})
        self.feedback = {"choice": ch, "auto": auto}
        self.app.audio.play({"bonne": "success", "moyenne": "notify", "mauvaise": "fail"}[ch.qualite])
        nxt = result["next"]
        if nxt is not None:
            self._add_phase_messages(nxt.phase, nxt.heure)
        self.timer = None
        self.timer_for = None
        self.app.autosave()

    def update(self, dt: float) -> None:
        self.t += dt
        if self.app.sim is None or self.uid is None or self.app.overlay_active:
            return
        inc = self._incident()
        if inc is None or not inc.in_crisis:
            return
        decision = self.sim.incidents.pending_decision(inc)
        if decision is None or self.feedback is not None or self.app.dialogs.active:
            return
        if decision.urgence and self.app.settings.get("timers", True):
            if self.timer_for != decision.id:
                self.timer_for = decision.id
                self.timer = float(decision.delai_secondes) * self.sim.difficulty.timer_mult
            elif self.timer is not None:
                self.timer -= dt
                if self.timer <= 0:
                    self.app.toast("Délai écoulé : la situation a décidé pour vous.", "danger")
                    self._decide(decision.id, decision.default_choice.id, auto=True)

    # -- dessin ------------------------------------------------------------------------------
    def _background(self, surf: pygame.Surface) -> None:
        w, h = surf.get_size()
        surf.fill((8, 10, 14))
        rack_w = 70
        for i in range(0, w // rack_w + 1):
            x = i * rack_w + 6
            pygame.draw.rect(surf, (16, 19, 25), (x, 60, rack_w - 12, h - 60))
            for j in range(12):
                y = 80 + j * ((h - 100) // 12)
                pygame.draw.rect(surf, (22, 26, 33), (x + 6, y, rack_w - 24, 18))
                on = math.sin(self.t * (2 + (i * 7 + j) % 5) + i + j) > 0.3
                col = (190, 30, 45) if (i + j) % 7 == 0 else (30, 120, 60)
                pygame.draw.circle(surf, col if on else (30, 34, 40), (x + rack_w - 24, y + 9), 3)
        veil = pygame.Surface((w, h), pygame.SRCALPHA)
        veil.fill((8, 10, 14, 205))
        surf.blit(veil, (0, 0))

    def draw(self, ui: UI) -> None:
        self._background(ui.surface)
        if self.app.sim is None or self.uid is None:
            self._empty(ui)
            return
        self.draw_content(ui)

    def _empty(self, ui: UI) -> None:
        w, h = self.size
        R.draw_text(ui.surface, "Aucune crise en cours", (w // 2, h // 2 - 40), "h1", "text", "bold", anchor="center")
        if ui.button(pygame.Rect(w // 2 - 150, h // 2 + 10, 300, 48), "Retour au tableau de bord", "primary") \
                or ui.key(pygame.K_ESCAPE):
            self.app.switch(GameScreen.DASHBOARD)

    def draw_content(self, ui: UI) -> None:
        surf = ui.surface
        w, h = self.size
        inc = self._incident()
        t = self.sim.incidents.template(inc)
        severity = severity_from_dict(t.impact)
        pending = self.sim.compliance.deadlines_for(inc.uid)
        urgent = self.sim.difficulty.deadline_reminders and any(d.done_hour is None and d.status == "pending" and
                     self.sim.compliance.time_left(d, inc.crisis_hour) <= OBLIGATIONS[d.kind].hours * config.DEADLINE_WARNING_RATIO
                     for d in pending) or any(d.status == "missed" and d.done_hour is None for d in pending)

        # en-tête ---------------------------------------------------------------------------
        header = pygame.Rect(0, 0, w, 64)
        pygame.draw.rect(surf, (40, 10, 14), header)
        blink = 0.5 + 0.5 * math.sin(self.t * (8 if urgent else 3))
        pygame.draw.circle(surf, R.blend((90, 20, 25), (255, 60, 60), blink), (30, 32), 11)
        R.draw_text(surf, "SALLE DE CRISE", (52, 8), "small", (255, 140, 140), "bold")
        R.draw_text_fit(surf, t.title, (52, 28), w - 560, "h3", "text", "bold")
        R.draw_text(surf, f"H+{inc.crisis_hour}", (w - 20, 8), "h1", (255, 200, 200), "bold", anchor="topright")
        if ui.button(pygame.Rect(w - 350, h - 90, 100, 44), "? Aide", "ghost",
                     tooltip="Fonctionnement de la salle de crise (F1)"):
            self.app.help.toggle(3)
        R.draw_text(surf, f"{PHASE_LABELS[Phase(inc.phase)]} · gravité G{severity} · {self.sim.current_date_label()}",
                    (w - 140, 22), "small", "text_muted", anchor="topright")
        crises = self.sim.active_crises()
        if len(crises) > 1:
            x = 560
            for c in crises:
                lab = self.sim.incidents.template(c).id
                if ui.button(pygame.Rect(x, 14, 110, 36), lab, "selected" if c.uid == inc.uid else "ghost"):
                    self.on_enter(incident=c.uid)
                x += 118

        body = pygame.Rect(MARGIN, 76, w - 2 * MARGIN, h - 76 - 110)
        left, center, right = split_h(body, [0.30, 0.40, 0.30], gap=14)
        self.regions.update(chat=left, decision=center, obligations=right)
        self._chat(ui, left, inc)
        self._decision(ui, center, inc, t)
        self._obligations(ui, right, inc, t)

        # frise -------------------------------------------------------------------------------
        tl = pygame.Rect(MARGIN, h - 100, w - 2 * MARGIN - 370, 90)
        markers = []
        for d in inc.decisions_taken:
            markers.append((d["hour"], self._choice_text(inc, d), d["quality"]))
        for dl in pending:
            if dl.done_hour is not None:
                markers.append((dl.done_hour, OBLIGATIONS[dl.kind].label, "notif"))
        draw_phase_timeline(ui, tl, inc.phase, markers)
        if ui.button(pygame.Rect(w - 240, h - 90, 224, 44), "← Tableau de bord", "ghost") or ui.key(pygame.K_ESCAPE):
            self.app.switch(GameScreen.DASHBOARD)

    def _chat(self, ui: UI, rect: pygame.Rect, inc) -> None:  # type: ignore[no-untyped-def]
        surf = ui.surface
        R.panel(surf, rect, (16, 20, 27), "border")
        R.draw_text(surf, "Messages entrants", (rect.x + 12, rect.y + 10), "h3", "text", "bold")
        area = pygame.Rect(rect.x + 10, rect.y + 44, rect.width - 20, rect.height - 54)
        off = ui.begin_scroll(f"chat:{inc.uid}", area)
        msgs = self.messages.get(inc.uid, [])
        heights = [R.measure_wrapped(m["texte"], area.width - 34, "small", line_spacing=2) + 36 for m in msgs]
        total = sum(heights) + 8 * len(msgs)
        # défilement automatique vers le bas pour les nouveaux messages
        if total > area.height and off == 0:
            ui.scroll[f"chat:{inc.uid}"] = off = area.height - total
        y = area.y + off
        for m, hh in zip(msgs, heights):
            mine = m.get("me") == "1"
            bubble = pygame.Rect(area.x + (24 if mine else 0), y, area.width - 30, hh)
            R.panel(surf, bubble, (23, 63, 128) if mine else (30, 36, 45), None, radius=8)
            R.draw_text(surf, m.get("de", ""), (bubble.x + 10, bubble.y + 6), "small", "accent" if not mine else "text",
                        "bold")
            R.draw_text(surf, m.get("h", ""), (bubble.right - 10, bubble.y + 6), "small", "text_muted",
                        anchor="topright")
            R.draw_wrapped(surf, m["texte"], pygame.Rect(bubble.x + 10, bubble.y + 26, bubble.width - 20, hh), "small",
                           line_spacing=2)
            y += hh + 8
        ui.end_scroll(f"chat:{inc.uid}", area, total)

    def _decision(self, ui: UI, rect: pygame.Rect, inc, t) -> None:  # type: ignore[no-untyped-def]
        surf = ui.surface
        R.panel(surf, rect, (18, 22, 30), "border")
        x, w = rect.x + 18, rect.width - 36
        y = rect.y + 14
        if self.feedback is not None:
            ch = self.feedback["choice"]
            col = QUALITY_COLORS[ch.qualite]
            R.draw_text(surf, "Analyse de votre décision", (x, y), "small", "text_muted")
            y += 22
            label = {"bonne": "Bonne décision", "moyenne": "Décision perfectible", "mauvaise": "Décision inadaptée"}
            R.draw_text(surf, label[ch.qualite] + (" (par défaut)" if self.feedback["auto"] else ""), (x, y), "h2", col,
                        "bold")
            y += 44
            y += R.draw_wrapped(surf, ch.texte, pygame.Rect(x, y, w, 120), "body", "text", "bold") + 12
            y += R.draw_wrapped(surf, ch.feedback, pygame.Rect(x, y, w, 220), "body", "text") + 12
            if ch.reference:
                y += R.draw_wrapped(surf, "Référence : " + ch.reference, pygame.Rect(x, y, w, 80), "small", "accent")
            if ui.button(pygame.Rect(rect.centerx - 130, rect.bottom - 64, 260, 46), "Continuer", "primary") \
                    or ui.key(pygame.K_RETURN):
                self.feedback = None
            return

        decision = self.sim.incidents.pending_decision(inc)
        if decision is None:
            self._rex(ui, rect, inc, t)
            return
        hint_w = 190 if self.sim.difficulty.show_hints else 0
        R.draw_text_fit(surf, f"{decision.de} · H+{decision.heure} · {PHASE_LABELS[decision.phase]}", (x, y),
                        w - hint_w, "small", "text_muted")
        y += 24
        y += R.draw_wrapped(surf, decision.texte, pygame.Rect(x, y, w, 160), "h3", "text", "bold") + 14
        if self.timer is not None and decision.urgence:
            frac = max(0.0, self.timer / max(1, decision.delai_secondes * self.sim.difficulty.timer_mult))
            col = config.THEME["danger"] if frac < 0.3 else config.THEME["warning"]
            R.draw_text(surf, f"Décision urgente : {int(self.timer) + 1} s", (x, y), "small", col, "bold")
            ui.progress(pygame.Rect(x, y + 20, w, 8), frac, col)
            y += 40
        hint = self.sim.decision_hint(inc.uid)
        if hint:
            hr = pygame.Rect(rect.right - 190, rect.y + 10, 172, 28)
            if ui.button(hr, "Conseil ANSSI", "ghost", size="small", tooltip=hint):
                self.app.toast(hint, "info")
        n = len(decision.choix)
        bh = min(84, (rect.bottom - y - 20) // max(1, n) - 10)
        for c in decision.choix:
            r = pygame.Rect(x, y, w, bh)
            hover = ui.hovered(r)
            R.panel(surf, r, (38, 46, 58) if hover else (28, 34, 43), "accent" if hover else "border")
            R.draw_wrapped(surf, c.texte, pygame.Rect(r.x + 14, r.y + 10, r.width - 28, r.height - 14), "body")
            if ui.clicked(r):
                self._decide(decision.id, c.id)
                return
            y += bh + 10

    def _rex(self, ui: UI, rect: pygame.Rect, inc, t) -> None:  # type: ignore[no-untyped-def]
        surf = ui.surface
        x, w = rect.x + 18, rect.width - 36
        y = rect.y + 14
        R.draw_text(surf, "Retour d'expérience à chaud", (x, y), "h2", "text", "bold")
        y += 44
        q = self.sim.incidents.decision_quality(inc)
        R.draw_text(surf, f"Qualité des décisions : {q:.0%}", (x, y), "body",
                    QUALITY_COLORS["bonne" if q >= 0.75 else "moyenne" if q >= 0.4 else "mauvaise"], "bold")
        y += 30
        context = {"organisation": self.sim.org.nom, "incident": t.title,
                   "decisions": [self._choice_text(inc, d) for d in inc.decisions_taken]}
        text = getattr(self, "_rex_cache", {}).get(inc.uid)
        if text is None:
            text = self.app.narrator.rex_summary(context, t.rex)
            self._rex_cache = {**getattr(self, "_rex_cache", {}), inc.uid: text}
        y += R.draw_wrapped(surf, text, pygame.Rect(x, y, w, rect.bottom - y - 150), "body") + 10
        if t.references:
            R.draw_text(surf, "Pour aller plus loin", (x, y), "small", "accent", "bold")
            y += 20
            for ref in t.references[:3]:
                y += R.draw_wrapped(surf, "• " + ref, pygame.Rect(x, y, w, 60), "small", "text_muted",
                                    line_spacing=1) + 2
        open_dl = [d for d in self.sim.compliance.deadlines_for(inc.uid) if d.done_hour is None and d.status == "pending"
                   and OBLIGATIONS[d.kind].hours <= 72]
        tip = ("Des notifications à 72 h ou moins sont encore en attente : lever la cellule fera avancer l'horloge "
               "d'une semaine et elles seront hors délai." if open_dl else "La reprise se poursuivra en arrière-plan.")
        if ui.button(pygame.Rect(rect.centerx - 160, rect.bottom - 64, 320, 48), "Lever la cellule de crise",
                     "danger" if open_dl else "success", tooltip=tip):
            result = self.sim.crisis_close(inc.uid)
            self.app.autosave()
            c = result["cost"]
            body = (f"Coût total de l'incident : {R.format_eur(c['brut'])}"
                    + (f" (dont {R.format_eur(c['rembourse'])} pris en charge par l'assureur)" if c["rembourse"] else "")
                    + f".\nReprise complète prévue en semaine {result['recovery_end']}.")
            self.app.dialogs.info("Cellule de crise levée", body, "info")
            remaining = self.sim.active_crises()
            if remaining:
                self.on_enter(incident=remaining[0].uid)
            else:
                self.app.switch(GameScreen.DASHBOARD)

    def _obligations(self, ui: UI, rect: pygame.Rect, inc, t) -> None:  # type: ignore[no-untyped-def]
        surf = ui.surface
        R.panel(surf, rect, (16, 20, 27), "border")
        R.draw_text(surf, "Obligations réglementaires", (rect.x + 12, rect.y + 10), "h3", "text", "bold")
        area = pygame.Rect(rect.x + 10, rect.y + 44, rect.width - 20, rect.height - 54)
        off = ui.begin_scroll(f"oblig:{inc.uid}", area)
        x, w = area.x, area.width - 10
        y = area.y + off
        deadlines = self.sim.compliance.deadlines_for(inc.uid)
        if not deadlines:
            y += R.draw_wrapped(surf, "Aucune notification réglementaire n'est requise pour cet incident.",
                                pygame.Rect(x, y, w, 60), "small", "text_muted") + 10
        for d in deadlines:
            o = OBLIGATIONS[d.kind]
            left = self.sim.compliance.time_left(d, inc.crisis_hour)
            box = pygame.Rect(x, y, w, 62)
            if d.done_hour is not None:
                col = config.THEME["success"] if d.status == "on_time" else config.THEME["warning"]
                status = f"Transmis à H+{d.done_hour}" + ("" if d.status == "on_time" else " (hors délai)")
            elif d.status == "missed" or left < 0:
                col = config.THEME["critical"]
                status = "DÉLAI DÉPASSÉ"
            else:
                warn = left <= o.hours * config.DEADLINE_WARNING_RATIO
                blink = warn and self.sim.difficulty.deadline_reminders and math.sin(self.t * 10) > 0
                col = config.THEME["danger"] if blink else (config.THEME["warning"] if warn else config.THEME["accent"])
                status = f"Reste {left} h (H+{o.hours})"
            R.panel(surf, box, (24, 29, 37), col, width=2)
            R.draw_text_fit(surf, o.label, (box.x + 10, box.y + 6), box.width - 20, "small", "text", "bold")
            btn_w = 124 if d.done_hour is None else 0
            R.draw_text_fit(surf, status, (box.x + 10, box.y + 34), box.width - 30 - btn_w, "small", col, "bold")
            ui.tooltip(pygame.Rect(box.x, box.y, box.width - btn_w, box.height), f"{o.authority} — {o.reference}")
            if d.done_hour is None:
                if ui.button(pygame.Rect(box.right - btn_w - 6, box.y + 28, btn_w, 28), "Transmettre", "primary",
                             size="small"):
                    self.sim.notify_obligation(inc.uid, d.kind)
                    self.app.audio.play("notify")
            y += 70
        y += 6
        R.draw_text(surf, "Fiche technique", (x, y), "body", "text", "bold")
        y += 26
        cves = ", ".join(c.get("id", "") for c in t.cve_references) or "aucune CVE spécifique"
        info = [f"Vecteur initial : {t.initial_vector}", f"CVE : {cves}",
                f"Compromission initiale : semaine {inc.start_turn} (détectée en semaine {inc.detection_turn})"]
        for line in info:
            y += R.draw_wrapped(surf, line, pygame.Rect(x, y, w, 80), "small", "text_muted", line_spacing=1) + 4
        y += 4
        R.draw_text(surf, "Chaîne d'attaque (MITRE ATT&CK)", (x, y), "small", "accent", "bold")
        y += 20
        cx = x
        for tid in t.attack_chain:
            tech = self.sim.data.mitre.get(tid, {})
            lw = R.font(11).size(tid)[0] + 14
            if cx + lw > x + w:
                cx = x
                y += 24
            chip = pygame.Rect(cx, y, lw, 20)
            pygame.draw.rect(surf, (30, 36, 45), chip, border_radius=4)
            R.draw_text(surf, tid, chip.center, 11, "text", anchor="center")
            ui.tooltip(chip, f"{tid} — {tech.get('nom', '?')} ({tech.get('tactique', '')})")
            cx += lw + 6
        y += 30
        ui.end_scroll(f"oblig:{inc.uid}", area, y - (area.y + off))
