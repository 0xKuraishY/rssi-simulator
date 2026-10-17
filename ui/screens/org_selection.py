"""Sélection de l'organisation : 5 cartes + tutoriel obligatoire à la première partie."""
from __future__ import annotations

import pygame

import config
from engine import renderer as R
from game.difficulty import DIFFICULTIES, DURATIONS
from game.state import GameScreen
from ui.components.dialog_box import tutorial_dialogs
from ui.components.widgets import UI, split_h
from ui.screens.base import Screen

DIFF_COLORS = {1: (63, 185, 80), 2: (120, 190, 60), 3: (210, 153, 34), 4: (230, 100, 40), 5: (248, 81, 73)}


class OrgSelectionScreen(Screen):
    name = GameScreen.ORG_SELECT.value
    show_hud = False

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.selected: str | None = None

    def on_enter(self, **kwargs: object) -> None:
        self.selected = None

    def _start(self) -> None:
        org_id = self.selected
        if org_id is None:
            return
        self.app.save_settings()
        if not self.app.settings.get("tutorial_done"):
            def finish() -> None:
                self.app.settings["tutorial_done"] = True
                self.app.save_settings()
                self.app.start_game(org_id)
            for d in tutorial_dialogs(finish):
                self.app.dialogs.push(d)
        else:
            self.app.start_game(org_id)

    def draw_content(self, ui: UI) -> None:
        surf = ui.surface
        w, h = surf.get_size()
        R.draw_text(surf, "Choisissez votre organisation", (24, 20), "h1", "text", "bold")
        R.draw_text(surf, "Vous y prenez vos fonctions de RSSI pour un mandat de 3 ans.", (24, 66), "body",
                    "text_muted")
        orgs = list(self.app.data.organisations.values())
        area = pygame.Rect(24, 110, w - 48, h - 290)
        cards = split_h(area, [1] * len(orgs), gap=14)
        for org, rect in zip(orgs, cards):
            selected = org.id == self.selected
            R.panel(surf, rect, "panel_alt" if selected else "panel", "accent" if selected else "border",
                    width=2 if selected else 1)
            if ui.clicked(rect):
                self.selected = org.id
                self.app.audio.play("click")
            x, y, cw = rect.x + 14, rect.y + 14, rect.width - 28
            dc = DIFF_COLORS[org.difficulte]
            pygame.draw.rect(surf, dc, (rect.x, rect.y, rect.width, 5), border_top_left_radius=8,
                             border_top_right_radius=8)
            R.draw_text_fit(surf, org.type_label, (x, y), cw, "h3", "text", "bold")
            y += 30
            R.draw_text(surf, org.nom, (x, y), "small", "text_muted")
            y += 26
            for i in range(5):
                pygame.draw.circle(surf, dc if i < org.difficulte else config.THEME["border"], (x + 7 + i * 18, y + 8), 6)
            R.draw_text(surf, org.difficulty_label, (x + 100, y), "small", dc, "bold")
            y += 28
            facts = [
                ("Effectif", f"{org.taille_employes:,}".replace(",", " ") + " personnes"),
                ("Budget IT", R.format_eur(org.budget_it)),
                ("Budget SSI", R.format_eur(org.budget_ssi)),
                ("SSI / IT", f"{org.budget_ssi / org.budget_it:.1%}"),
            ]
            for label, value in facts:
                R.draw_text(surf, label, (x, y), "small", "text_muted")
                R.draw_text(surf, value, (rect.right - 14, y), "small", "text", "bold", anchor="topright")
                y += 22
            y += 6
            R.draw_text(surf, "Réglementation", (x, y), "small", "accent", "bold")
            y += 20
            for reg in org.regimes.labels:
                R.draw_text(surf, "• " + reg, (x, y), "small", "text")
                y += 19
            y += 8
            R.draw_text(surf, "Enjeux", (x, y), "small", "accent", "bold")
            y += 20
            text_rect = pygame.Rect(x, y, cw, rect.bottom - y - 10)
            enjeux = "\n".join("• " + e for e in org.enjeux[:3])
            R.draw_wrapped(surf, enjeux, text_rect, "small", "text_muted", line_spacing=2)
            ui.tooltip(pygame.Rect(rect.x, rect.y, rect.width, 120), org.description)

        self._options_bar(ui, pygame.Rect(24, h - 168, w - 48, 86))
        bar_y = h - 70
        if ui.button(pygame.Rect(24, bar_y, 200, 48), "← Retour", "ghost") or ui.key(pygame.K_ESCAPE):
            self.app.switch(GameScreen.MENU)
        if ui.button(pygame.Rect(w - 470, bar_y, 110, 48), "? Aide", "ghost",
                     tooltip="But du jeu, organisations et difficultés (F1)"):
            self.app.help.toggle(9)
        label = "Prendre mes fonctions" if self.selected else "Sélectionnez une organisation"
        if ui.button(pygame.Rect(w - 344, bar_y, 320, 48), label, "primary", enabled=self.selected is not None):
            self._start()
        if self.selected:
            org = self.app.data.organisations[self.selected]
            R.draw_wrapped(surf, org.description, pygame.Rect(250, bar_y - 4, w - 740, 60), "small", "text_muted")

    def _options_bar(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        settings = self.app.settings
        R.panel(surf, rect, "panel", "border")
        R.draw_text(surf, "Difficulté", (rect.x + 14, rect.y + 8), "small", "accent", "bold")
        x = rect.x + 14
        bw = min(170, (rect.width * 0.62 - 20) // len(DIFFICULTIES))
        for d in DIFFICULTIES.values():
            sel = settings.get("difficulty", "standard") == d.id
            if ui.button(pygame.Rect(x, rect.y + 30, bw - 8, 40), d.nom, "selected" if sel else "ghost",
                         tooltip=d.description):
                settings["difficulty"] = d.id
            x += bw
        x0 = rect.x + int(rect.width * 0.64)
        R.draw_text(surf, "Durée du mandat", (x0, rect.y + 8), "small", "accent", "bold")
        x = x0
        dw = (rect.right - 14 - x0) // len(DURATIONS)
        for years, label in DURATIONS.items():
            sel = int(settings.get("years", 3)) == years
            if ui.button(pygame.Rect(x, rect.y + 30, dw - 8, 40), f"{years} an{'s' if years > 1 else ''}",
                         "selected" if sel else "ghost", tooltip=label + f" — {years * 52} semaines"):
                settings["years"] = years
            x += dw
