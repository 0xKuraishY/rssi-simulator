"""Classe de base des écrans."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import config
from engine import renderer as R
from ui.components.hud import HUD_HEIGHT, draw_hud
from ui.components.widgets import UI

if TYPE_CHECKING:
    from engine.game_loop import GameApp
    from game.simulation import Simulation

MARGIN = 16


class Screen:
    name = "screen"
    show_hud = True

    def __init__(self, app: "GameApp") -> None:
        self.app = app
        self.regions: dict[str, pygame.Rect] = {}   # zones nommées, mises en lumière par la visite guidée

    # -- accès rapides ---------------------------------------------------------
    @property
    def sim(self) -> "Simulation":
        assert self.app.sim is not None
        return self.app.sim

    @property
    def size(self) -> tuple[int, int]:
        return self.app.surface.get_size()

    def content_rect(self) -> pygame.Rect:
        w, h = self.size
        top = HUD_HEIGHT + MARGIN if self.show_hud else MARGIN
        return pygame.Rect(MARGIN, top, w - 2 * MARGIN, h - top - MARGIN)

    # -- cycle de vie -------------------------------------------------------------
    def on_enter(self, **kwargs: object) -> None:
        pass

    def on_exit(self) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def draw(self, ui: UI) -> None:
        ui.surface.fill(config.THEME["bg"])
        if self.show_hud and self.app.sim is not None:
            hud, help_rect, help_clicked = draw_hud(ui, self.sim)
            self.regions["hud"] = hud
            self.regions["help"] = help_rect
            if help_clicked:
                self.app.help.toggle()
        self.draw_content(ui)

    def draw_content(self, ui: UI) -> None:
        raise NotImplementedError

    # -- utilitaires -----------------------------------------------------------------
    def back_button(self, ui: UI, target: str = "DASHBOARD", label: str = "← Tableau de bord") -> None:
        r = pygame.Rect(self.size[0] - 230, HUD_HEIGHT + 8, 214, 36)
        if ui.button(r, label, "ghost") or ui.key(pygame.K_ESCAPE):
            self.app.switch(target)

    def title(self, ui: UI, text: str, subtitle: str = "") -> int:
        y = HUD_HEIGHT + 14 if self.show_hud else 20
        R.draw_text(ui.surface, text, (MARGIN, y), "h1", "text", "bold")
        if subtitle:
            R.draw_text(ui.surface, subtitle, (MARGIN, y + 44), "body", "text_muted")
            return y + 74
        return y + 52
