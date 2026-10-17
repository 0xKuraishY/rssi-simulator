"""Carte 3D isométrique du système d'information (rendu logiciel, sans dépendance).

Chaque bien support est un volume dont la hauteur traduit la criticité et la
couleur l'état : sain, vulnérable (faille critique exposée), en reprise ou
compromis (crise en cours, pulsation rouge). La scène tourne lentement ; des
paquets circulent sur les liens, rouges pendant une crise.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

from engine import renderer as R

if TYPE_CHECKING:
    from game.simulation import Simulation
    from ui.components.widgets import UI

Vec = tuple[float, float]

STATE_COLORS = {
    "ok": (46, 160, 67),
    "vuln": (210, 153, 34),
    "recovery": (230, 120, 40),
    "crisis": (218, 54, 51),
    "internet": (56, 139, 253),
}
STATE_LABELS = {"ok": "sain", "vuln": "vulnérabilité critique exposée", "recovery": "en reprise après incident",
                "crisis": "compromis — crise en cours"}
EXPOSED_TYPES = {"Service", "Réseau"}
WIDE_IMPACT = {"ransomware", "double_extorsion", "ot_iot", "supply_chain"}


@dataclass
class Node:
    key: str
    label: str
    gx: float
    gy: float
    height: float
    kind: str        # asset | internet
    primary: bool
    exposed: bool


def _layout(sim: "Simulation") -> list[Node]:
    assets = sim.org.assets_critiques
    prim = [a for a in assets if a.criticite == "primaire"]
    sec = [a for a in assets if a.criticite != "primaire"]
    nodes = [Node("internet", "Internet", 0.0, 0.0, 10, "internet", False, True)]

    def ring(items, radius: float, offset: float) -> None:
        n = max(1, len(items))
        for i, a in enumerate(items):
            ang = offset + 2 * math.pi * i / n
            nodes.append(Node(a.id, a.nom, radius * math.cos(ang), radius * math.sin(ang),
                              38 if a.criticite == "primaire" else 22, "asset", a.criticite == "primaire",
                              a.type in EXPOSED_TYPES))
    ring(prim, 1.35, 0.3)
    ring(sec, 2.55, 0.0)
    return nodes


def asset_states(sim: "Simulation", nodes: list[Node]) -> dict[str, str]:
    states = {n.key: "ok" for n in nodes if n.kind == "asset"}
    asset_keys = [n.key for n in nodes if n.kind == "asset"]
    if sim.vulns.critical_exposed():
        for n in nodes:
            if n.kind == "asset" and n.exposed:
                states[n.key] = "vuln"
    for inc in sim.incidents.incidents:
        if not inc.detected or inc.closed:
            continue
        t = sim.incidents.template(inc)
        state = "crisis" if inc.in_crisis else "recovery"
        if t.type in WIDE_IMPACT:
            hit = [n.key for n in nodes if n.kind == "asset" and n.primary]
        else:
            h = sum(ord(c) for c in inc.uid)
            hit = [asset_keys[h % len(asset_keys)], asset_keys[(h * 7) % len(asset_keys)]] if asset_keys else []
        for k in hit:
            if state == "crisis" or states.get(k) != "crisis":
                states[k] = state
    return states


class IsoMap:
    def __init__(self) -> None:
        self._org: str | None = None
        self.nodes: list[Node] = []

    def _ensure(self, sim: "Simulation") -> None:
        if self._org != sim.org.id:
            self._org = sim.org.id
            self.nodes = _layout(sim)

    def draw(self, ui: "UI", rect: pygame.Rect, sim: "Simulation", t: float, rotate: bool = True) -> None:
        self._ensure(sim)
        surf = ui.surface
        prev_clip = surf.get_clip()
        surf.set_clip(rect.clip(prev_clip) if prev_clip else rect)
        cx, cy = rect.centerx, rect.centery + 10
        scale = min(rect.width / 7.6, rect.height / 5.2)
        angle = t * 0.12 if rotate else 0.6

        def proj(gx: float, gy: float, z: float = 0.0) -> Vec:
            rx = gx * math.cos(angle) - gy * math.sin(angle)
            ry = gx * math.sin(angle) + gy * math.cos(angle)
            return cx + (rx - ry) * scale * 0.9, cy + (rx + ry) * scale * 0.45 - z * scale / 40

        def depth(gx: float, gy: float) -> float:
            rx = gx * math.cos(angle) - gy * math.sin(angle)
            ry = gx * math.sin(angle) + gy * math.cos(angle)
            return rx + ry

        # sol : plateau losange et cercles de protection
        floor = [proj(x, y) for x, y in ((-3.3, -3.3), (3.3, -3.3), (3.3, 3.3), (-3.3, 3.3))]
        pygame.draw.polygon(surf, (17, 21, 28), floor)
        pygame.draw.polygon(surf, (36, 42, 52), floor, 1)
        for i in range(-3, 4):
            pygame.draw.aaline(surf, (24, 29, 37), proj(i, -3.3), proj(i, 3.3))
            pygame.draw.aaline(surf, (24, 29, 37), proj(-3.3, i), proj(3.3, i))
        coverage = sim.risk.hygiene_coverage(sim.turn)
        ring_col = R.blend((30, 40, 60), (56, 139, 253), coverage)
        for radius in (1.35, 2.55):
            pts = [proj(radius * math.cos(a / 24 * 2 * math.pi), radius * math.sin(a / 24 * 2 * math.pi))
                   for a in range(25)]
            pygame.draw.aalines(surf, ring_col, False, pts)

        states = asset_states(sim, self.nodes)
        crisis = any(s == "crisis" for s in states.values())

        # liens et paquets
        by_key = {n.key: n for n in self.nodes}
        links = [("internet", n.key) for n in self.nodes if n.kind == "asset" and n.exposed]
        core = next((n.key for n in self.nodes if n.key == "ad"), None) or \
            next((n.key for n in self.nodes if n.kind == "asset" and n.primary), None)
        if core:
            links += [(core, n.key) for n in self.nodes if n.kind == "asset" and n.key != core]
        for i, (a, b) in enumerate(links):
            na, nb = by_key[a], by_key[b]
            pa, pb = proj(na.gx, na.gy, 4), proj(nb.gx, nb.gy, 4)
            pygame.draw.aaline(surf, (48, 58, 74), pa, pb)
            phase = (t * 0.35 + i * 0.37) % 1.0
            px = pa[0] + (pb[0] - pa[0]) * phase
            py = pa[1] + (pb[1] - pa[1]) * phase
            hot = crisis and (states.get(b) == "crisis" or states.get(a) == "crisis")
            pygame.draw.circle(surf, (255, 90, 90) if hot else (120, 180, 255), (int(px), int(py)), 3 if hot else 2)

        # volumes, du plus lointain au plus proche
        for n in sorted(self.nodes, key=lambda n: depth(n.gx, n.gy)):
            if n.kind == "internet":
                self._cloud(surf, proj(n.gx, n.gy, 60), scale, t)
                continue
            state = states.get(n.key, "ok")
            base = STATE_COLORS[state]
            if state == "crisis":
                base = R.blend(base, (255, 200, 200), 0.5 + 0.5 * math.sin(t * 6))
            top_rect = self._box(surf, proj, n.gx, n.gy, 0.24 if n.primary else 0.2, n.height, base, angle)
            ui.tooltip(top_rect, f"{n.label} — {'bien support primaire' if n.primary else 'bien support secondaire'}"
                                 f", {STATE_LABELS[state]}")
        legend = [("ok", "Sain"), ("vuln", "Vulnérable"), ("recovery", "Reprise"), ("crisis", "Crise")]
        x = rect.x + 6
        for key, label in legend:
            pygame.draw.rect(surf, STATE_COLORS[key], (x, rect.bottom - 18, 10, 10), border_radius=2)
            R.draw_text(surf, label, (x + 14, rect.bottom - 21), 11, "text_muted")
            x += 22 + R.font(11).size(label)[0]
        surf.set_clip(prev_clip)

    @staticmethod
    def _box(surf: pygame.Surface, proj, gx: float, gy: float, half: float, h: float,  # type: ignore[no-untyped-def]
             color: tuple[int, int, int], angle: float) -> pygame.Rect:
        corners = [(gx - half, gy - half), (gx + half, gy - half), (gx + half, gy + half), (gx - half, gy + half)]
        bottom = [proj(x, y, 0) for x, y in corners]
        top = [proj(x, y, h) for x, y in corners]
        # faces latérales visibles : normale orientée vers l'observateur (direction +x+y après rotation)
        normals = [(0, -1), (1, 0), (0, 1), (-1, 0)]
        faces = []
        for i, (nx, ny) in enumerate(normals):
            rnx = nx * math.cos(angle) - ny * math.sin(angle)
            rny = nx * math.sin(angle) + ny * math.cos(angle)
            facing = rnx + rny
            if facing > 0:
                j = (i + 1) % 4
                shade = 0.55 + 0.25 * (rnx - rny + 1.4) / 2.8
                faces.append((facing, [bottom[i], bottom[j], top[j], top[i]], shade))
        for _, poly, shade in sorted(faces, key=lambda f: f[0]):
            col = tuple(int(c * shade) for c in color)
            pygame.draw.polygon(surf, col, poly)
            pygame.draw.polygon(surf, (12, 14, 18), poly, 1)
        pygame.draw.polygon(surf, R.blend(color, (255, 255, 255), 0.15), top)
        pygame.draw.polygon(surf, R.blend(color, (255, 255, 255), 0.45), top, 1)
        xs = [p[0] for p in top]
        ys = [p[1] for p in top]
        return pygame.Rect(min(xs), min(ys), max(xs) - min(xs), max(p[1] for p in bottom) - min(ys))

    @staticmethod
    def _cloud(surf: pygame.Surface, pos: Vec, scale: float, t: float) -> None:
        x, y = pos
        r = max(8, int(scale * 0.22))
        bob = math.sin(t * 1.5) * 3
        for dx, dy, k in ((-r, 2, 0.8), (r, 2, 0.8), (0, -r * 0.5, 1.0), (0, 4, 1.0)):
            pygame.draw.circle(surf, (35, 70, 130), (int(x + dx), int(y + dy + bob)), int(r * k))
        R.draw_text(surf, "Internet", (x, y + bob + r + 4), 11, "text_muted", anchor="midtop")


def draw_background_city(surf: pygame.Surface, t: float) -> None:
    """Décor animé du menu : quartier isométrique de « datacenters », très sobre."""
    w, h = surf.get_size()
    tile = max(34, w // 34)
    cx, cy = w * 0.5, h * 0.80
    cells = []
    for gx in range(-9, 10):
        for gy in range(-9, 10):
            hsh = (gx * 73856093) ^ (gy * 19349663)
            if hsh % 5 not in (0, 1):
                continue
            cells.append((gx + gy, gx, gy, (hsh >> 3) % 6))
    for _, gx, gy, level in sorted(cells):
        x = cx + (gx - gy) * tile * 0.5
        y = cy + (gx + gy) * tile * 0.25 - h * 0.12
        if not (-tile < x < w + tile and -tile < y < h + tile):
            continue
        hgt = 6 + level * tile * 0.22 + 3 * math.sin(t * 0.7 + gx * 0.9 + gy * 0.6)
        q = tile * 0.42
        top = [(x, y - hgt - q * 0.5), (x + q, y - hgt), (x, y - hgt + q * 0.5), (x - q, y - hgt)]
        left = [top[3], top[2], (x, y + q * 0.5), (x - q, y)]
        right = [top[2], top[1], (x + q, y), (x, y + q * 0.5)]
        pygame.draw.polygon(surf, (15, 19, 27), left)
        pygame.draw.polygon(surf, (19, 25, 36), right)
        pygame.draw.polygon(surf, (24, 34, 52), top)
        pygame.draw.polygon(surf, (30, 44, 68), top, 1)
        if (gx * 3 + gy * 5 + int(t * 1.5)) % 11 == 0:
            pygame.draw.circle(surf, (56, 139, 253), (int(x), int(y - hgt)), 2)
