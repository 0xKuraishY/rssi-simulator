"""Matrice de risque EBIOS RM 4×4 (Vraisemblance × Gravité), interactive."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

import config
from engine import renderer as R
from game.risk_engine import LIKELIHOOD_LABELS, SEVERITY_LABELS, risk_category

if TYPE_CHECKING:
    from ui.components.widgets import UI


@dataclass
class MatrixItem:
    key: str
    label: str
    likelihood: int
    severity: int
    tooltip: str = ""
    ghost: bool = False  # position « avant » affichée en transparence


def cell_color(v: int, g: int, alpha: int = 255) -> tuple[int, ...]:
    base = config.RISK_COLORS[risk_category(v * g)]
    dark = R.blend(base, config.THEME["panel"], 0.55)
    return (*dark, alpha) if alpha < 255 else dark


def draw_matrix(ui: "UI", rect: pygame.Rect, items: list[MatrixItem], draggable: bool = False,
                title: str = "", compact: bool = False) -> tuple[str, int, int] | None:
    """Dessine la matrice. Si ``draggable``, renvoie (clé, V, G) quand un élément est déposé."""
    surf = ui.surface
    label_w = 0 if compact else 110
    top = 26 if title else 0
    axis_h = 0 if compact else 34
    grid = pygame.Rect(rect.x + label_w, rect.y + top, rect.width - label_w, rect.height - top - axis_h)
    cw, ch = grid.width // 4, grid.height // 4
    if title:
        R.draw_text(surf, title, (rect.x, rect.y), "body", "text", "bold")
    cells: dict[tuple[int, int], pygame.Rect] = {}
    for v in range(1, 5):
        for g in range(1, 5):
            r = pygame.Rect(grid.x + (g - 1) * cw, grid.bottom - v * ch, cw - 2, ch - 2)
            cells[(v, g)] = r
            pygame.draw.rect(surf, cell_color(v, g), r, border_radius=4)
            if not compact:
                R.draw_text(surf, str(v * g), (r.right - 6, r.y + 4), "small", (255, 255, 255, 120), anchor="topright")
    if not compact:
        for v in range(1, 5):
            r = cells[(v, 1)]
            R.draw_text(surf, f"V{v}", (rect.x + 4, r.centery - 9), "small", "text", "bold")
            R.draw_text(surf, LIKELIHOOD_LABELS[v][:16], (rect.x + 4, r.centery + 7), 11, "text_muted")
        for g in range(1, 5):
            r = cells[(1, g)]
            R.draw_text(surf, f"G{g} {SEVERITY_LABELS[g]}", (r.centerx, grid.bottom + 8), "small", "text_muted",
                        anchor="midtop")
        R.draw_text(surf, "Vraisemblance ↑   Gravité →", (rect.x + 4, grid.bottom + 8), 11, "text_muted")

    # placement des éléments par cellule
    by_cell: dict[tuple[int, int], list[MatrixItem]] = {}
    for it in items:
        by_cell.setdefault((it.likelihood, it.severity), []).append(it)
    chip_h = 18 if compact else 22
    for (v, g), its in by_cell.items():
        r = cells.get((v, g))
        if r is None:
            continue
        per_row = max(1, (r.width - 8) // (40 if compact else 66))
        for i, it in enumerate(its[: per_row * max(1, (r.height - 8) // (chip_h + 3))]):
            cx = r.x + 4 + (i % per_row) * ((r.width - 8) // per_row)
            cy = r.y + 4 + (i // per_row) * (chip_h + 3)
            chip = pygame.Rect(cx, cy, (r.width - 8) // per_row - 3, chip_h)
            if it.ghost:
                pygame.draw.rect(surf, (230, 233, 237), chip, 1, border_radius=4)
                R.draw_text(surf, it.label, chip.center, 11, "text_muted", anchor="center")
            else:
                pygame.draw.rect(surf, (13, 17, 23), chip, border_radius=4)
                pygame.draw.rect(surf, (230, 233, 237), chip, 1, border_radius=4)
                R.draw_text(surf, it.label, chip.center, 11 if compact else "small", "text", "bold", anchor="center")
            if it.tooltip:
                ui.tooltip(chip, it.tooltip)
            if draggable and not it.ghost:
                ui.draggable(chip, f"matrix:{it.key}", it.key, it.label)
    if draggable:
        for (v, g), r in cells.items():
            dropped = ui.drop_target(r)
            if dropped is not None and str(dropped.key).startswith("matrix:"):
                return dropped.payload, v, g
    return None
