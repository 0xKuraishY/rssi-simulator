"""Frise chronologique d'un incident (7 phases) et de ses événements horodatés."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import config
from engine import renderer as R
from game.incident_engine import PHASE_LABELS, Phase

if TYPE_CHECKING:
    from ui.components.widgets import UI

SHORT = {
    Phase.COMPROMISSION: "1 Compromission", Phase.LATENCE: "2 Latence", Phase.DETECTION: "3 Détection",
    Phase.CONFINEMENT: "4 Confinement", Phase.ERADICATION: "5 Éradication", Phase.REPRISE: "6 Reprise",
    Phase.REX: "7 REX",
}


def draw_phase_timeline(ui: "UI", rect: pygame.Rect, current: int, markers: list[tuple[int, str, str]] | None = None,
                        max_hour: int = 168) -> None:
    """``markers`` : liste (heure, libellé court, qualité/état) placés sur l'axe horaire."""
    surf = ui.surface
    phases = [p for p in Phase if p != Phase.CLOS]
    seg_w = rect.width // len(phases)
    for i, p in enumerate(phases):
        r = pygame.Rect(rect.x + i * seg_w, rect.y, seg_w - 4, 30)
        if p < current or current == Phase.CLOS:
            col = R.blend(config.THEME["accent"], config.THEME["panel"], 0.5)
        elif p == current:
            col = config.THEME["accent"]
        else:
            col = config.THEME["panel_alt"]
        if p <= Phase.LATENCE:
            col = R.blend(col, (90, 90, 90), 0.4)
        pygame.draw.rect(surf, col, r, border_radius=5)
        R.draw_text(surf, SHORT[p], r.center, "small", "text", "bold" if p == current else "regular", anchor="center")
        ui.tooltip(r, PHASE_LABELS[p] + (" (invisible pour l'organisation)" if p <= Phase.LATENCE else ""))
    axis_y = rect.y + 56
    x0 = rect.x + 2 * seg_w
    x1 = rect.right - 8
    pygame.draw.line(surf, config.THEME["border"], (x0, axis_y), (x1, axis_y), 2)
    for h in (0, 24, 72, 168):
        if h > max_hour:
            continue
        x = x0 + (x1 - x0) * h / max_hour
        pygame.draw.line(surf, config.THEME["text_muted"], (x, axis_y - 4), (x, axis_y + 4))
        R.draw_text(surf, f"H+{h}", (x, axis_y + 8), 11, "text_muted", anchor="midtop")
    colors = {"bonne": config.THEME["success"], "moyenne": config.THEME["warning"],
              "mauvaise": config.THEME["danger"], "notif": config.THEME["accent"]}
    for hour, label, kind in markers or []:
        x = x0 + (x1 - x0) * min(hour, max_hour) / max_hour
        pygame.draw.circle(surf, colors.get(kind, config.THEME["text"]), (int(x), axis_y), 6)
        ui.tooltip(pygame.Rect(x - 7, axis_y - 7, 14, 14), f"H+{hour} — {label}")
