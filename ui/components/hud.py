"""Bandeau supérieur permanent : date | budget | réputation globale | semaine/156."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import config
from engine import renderer as R
from game.risk_engine import RISK_LABELS

if TYPE_CHECKING:
    from game.simulation import Simulation
    from ui.components.widgets import UI

HUD_HEIGHT = 56


def reputation_color(score: float) -> tuple[int, int, int]:
    if score < config.REPUTATION_GAME_OVER:
        return config.THEME["critical"]
    if score < config.REPUTATION_CONTRACT_LOSS:
        return config.THEME["danger"]
    if score < 60:
        return config.THEME["warning"]
    return config.THEME["success"]


def draw_hud(ui: "UI", sim: "Simulation", title: str = "") -> tuple[pygame.Rect, pygame.Rect, bool]:
    surf = ui.surface
    w = surf.get_width()
    rect = pygame.Rect(0, 0, w, HUD_HEIGHT)
    pygame.draw.rect(surf, (10, 13, 18), rect)
    pygame.draw.line(surf, config.THEME["border"], (0, HUD_HEIGHT - 1), (w, HUD_HEIGHT - 1))
    mark = R.logo(30)
    name_x = 16
    if mark is not None:
        surf.blit(mark, (14, (HUD_HEIGHT - 30) // 2))
        name_x = 52
    name_rect = R.draw_text(surf, config.APP_NAME, (name_x, 16), "h3", "accent", "bold")
    help_rect = pygame.Rect(name_rect.right + 14, 12, 86, 32)
    help_clicked = ui.button(help_rect, "? Aide", "secondary", size="small",
                             tooltip="But du jeu et fonctionnement (F1)")
    R.draw_text(surf, title or sim.org.nom, (help_rect.right + 12, 19), "body", "text_muted")

    rep = sim.reputation.global_score()
    level, cat = sim.global_risk()
    items = [
        ("Date", sim.current_date_label(), config.THEME["text"]),
        ("Budget SSI restant", R.format_eur(sim.budget.remaining),
         config.THEME["danger"] if sim.budget.remaining < 0.1 * sim.budget.budget_annuel_ssi else config.THEME["text"]),
        ("Réputation", f"{rep:.0f}/100", reputation_color(rep)),
        ("Risque", f"{RISK_LABELS[cat]} ({level})", config.RISK_COLORS[cat]),
        ("Semaine", f"{sim.turn}/{sim.calendar.total_turns}", config.THEME["text"]),
    ]
    x = w - 16
    for label, value, col in reversed(items):
        vw = max(R.font("body", "bold").size(value)[0], R.font("small").size(label)[0])
        R.draw_text(surf, label, (x, 6), "small", "text_muted", anchor="topright")
        R.draw_text(surf, value, (x, 26), "body", col, "bold", anchor="topright")
        x -= vw + 32
    return rect, help_rect, help_clicked
