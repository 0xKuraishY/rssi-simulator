"""Boîte à outils d'interface en « mode immédiat ».

Chaque image, l'écran redessine ses éléments et interroge l'UI (``ui.button(...)``
renvoie True si le bouton vient d'être cliqué). Cette approche évite toute
synchronisation d'état entre widgets et données de jeu et rend les écrans
simples à tester en mode headless.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pygame

import config
from engine import renderer as R

Color = tuple[int, int, int]

STYLES: dict[str, dict[str, Color]] = {
    "primary": {"bg": (31, 111, 235), "hover": (56, 139, 253), "text": (255, 255, 255), "border": (56, 139, 253)},
    "secondary": {"bg": (33, 38, 45), "hover": (48, 54, 61), "text": (230, 233, 237), "border": (68, 76, 86)},
    "danger": {"bg": (166, 32, 38), "hover": (218, 54, 51), "text": (255, 255, 255), "border": (248, 81, 73)},
    "success": {"bg": (35, 134, 54), "hover": (46, 160, 67), "text": (255, 255, 255), "border": (63, 185, 80)},
    "ghost": {"bg": (14, 17, 23), "hover": (30, 36, 45), "text": (201, 209, 217), "border": (48, 56, 68)},
    "selected": {"bg": (23, 63, 128), "hover": (31, 82, 160), "text": (255, 255, 255), "border": (88, 166, 255)},
}
DISABLED: dict[str, Color] = {"bg": (28, 32, 38), "text": (90, 98, 108), "border": (40, 46, 54)}


@dataclass
class DragState:
    key: str
    payload: Any
    offset: tuple[int, int]
    label: str
    size: tuple[int, int]


@dataclass
class UI:
    surface: pygame.Surface
    mouse: tuple[int, int] = (0, 0)
    pressed_pos: tuple[int, int] | None = None
    released: bool = False
    pressed: bool = False
    wheel: int = 0
    keys_down: list[int] = field(default_factory=list)
    input_enabled: bool = True
    clip_stack: list[pygame.Rect] = field(default_factory=list)
    scroll: dict[str, int] = field(default_factory=dict)
    drag: DragState | None = None
    dropped: DragState | None = None
    tooltip_text: str | None = None
    time: float = 0.0
    click_sound: Any = None
    text_typed: str = ""
    focus: str | None = None
    targets: list[pygame.Rect] = field(default_factory=list)       # zones cliquables de l'image courante
    last_targets: list[pygame.Rect] = field(default_factory=list)  # … de l'image précédente (tests automatisés)

    # -- cycle de vie --------------------------------------------------------
    def begin_frame(self, events: list[pygame.event.Event], dt: float) -> None:
        self.time += dt
        self.last_targets, self.targets = self.targets, []
        self.released = False
        self.pressed = False
        self.wheel = 0
        self.keys_down = []
        self.text_typed = ""
        self.tooltip_text = None
        self.dropped = None
        self.mouse = pygame.mouse.get_pos()
        for ev in events:
            if ev.type == pygame.MOUSEMOTION:
                self.mouse = ev.pos
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                self.pressed_pos = ev.pos
                self.pressed = True
                self.mouse = ev.pos
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                self.released = True
                self.mouse = ev.pos
            elif ev.type == pygame.MOUSEWHEEL:
                self.wheel += ev.y
            elif ev.type == pygame.KEYDOWN:
                self.keys_down.append(ev.key)
            elif ev.type == pygame.TEXTINPUT:
                self.text_typed += ev.text

    def end_frame(self) -> None:
        if self.drag is not None:
            ghost = pygame.Rect(0, 0, *self.drag.size)
            ghost.topleft = (self.mouse[0] - self.drag.offset[0], self.mouse[1] - self.drag.offset[1])
            s = pygame.Surface(ghost.size, pygame.SRCALPHA)
            pygame.draw.rect(s, (56, 139, 253, 200), s.get_rect(), border_radius=6)
            self.surface.blit(s, ghost)
            R.draw_text(self.surface, self.drag.label, ghost.center, "small", (255, 255, 255), anchor="center")
            if self.released:
                self.dropped = self.drag
                self.drag = None
        if self.released:
            self.pressed_pos = None
        if self.tooltip_text:
            self._draw_tooltip(self.tooltip_text)

    def finish_drop(self) -> None:
        """Appelé après le dessin : un dépôt non capté est annulé."""
        self.dropped = None

    # -- état souris -------------------------------------------------------------
    def _visible(self, pos: tuple[int, int]) -> bool:
        return all(c.collidepoint(pos) for c in self.clip_stack)

    def hovered(self, rect: pygame.Rect) -> bool:
        return self.input_enabled and rect.collidepoint(self.mouse) and self._visible(self.mouse)

    def clicked(self, rect: pygame.Rect) -> bool:
        if self.input_enabled and (not self.clip_stack or self._visible(rect.center)):
            self.targets.append(rect.copy())
        if not (self.input_enabled and self.released and self.drag is None and self.pressed_pos):
            return False
        return (rect.collidepoint(self.mouse) and rect.collidepoint(self.pressed_pos)
                and self._visible(self.mouse))

    def key(self, *keys: int) -> bool:
        return self.input_enabled and any(k in self.keys_down for k in keys)

    # -- découpage --------------------------------------------------------------
    def push_clip(self, rect: pygame.Rect) -> None:
        self.clip_stack.append(rect)
        clip = rect
        for c in self.clip_stack[:-1]:
            clip = clip.clip(c)
        self.surface.set_clip(clip)

    def pop_clip(self) -> None:
        self.clip_stack.pop()
        if self.clip_stack:
            clip = self.clip_stack[0]
            for c in self.clip_stack[1:]:
                clip = clip.clip(c)
            self.surface.set_clip(clip)
        else:
            self.surface.set_clip(None)

    # -- zones défilantes ------------------------------------------------------------
    def begin_scroll(self, key: str, rect: pygame.Rect) -> int:
        """Ouvre une zone défilante ; renvoie le décalage vertical courant (≤ 0)."""
        if self.input_enabled and rect.collidepoint(self.mouse) and self.wheel:
            self.scroll[key] = self.scroll.get(key, 0) + self.wheel * 40
        self.push_clip(rect)
        return self.scroll.get(key, 0)

    def end_scroll(self, key: str, rect: pygame.Rect, content_height: int) -> None:
        self.pop_clip()
        min_off = min(0, rect.height - content_height)
        off = max(min_off, min(0, self.scroll.get(key, 0)))
        self.scroll[key] = off
        if content_height > rect.height:
            track = pygame.Rect(rect.right - 5, rect.y + 2, 4, rect.height - 4)
            pygame.draw.rect(self.surface, (40, 46, 54), track, border_radius=2)
            h = max(20, int(track.height * rect.height / content_height))
            y = track.y + int((track.height - h) * (-off) / max(1, content_height - rect.height))
            pygame.draw.rect(self.surface, (110, 118, 129), (track.x, y, 4, h), border_radius=2)

    def reset_scroll(self, key: str) -> None:
        self.scroll.pop(key, None)

    # -- widgets ----------------------------------------------------------------------
    def button(self, rect: pygame.Rect, label: str, style: str = "secondary", enabled: bool = True,
               tooltip: str | None = None, size: str | int = "body", icon: str | None = None) -> bool:
        hover = self.hovered(rect)
        if enabled:
            st = STYLES[style]
            bg = st["hover"] if hover else st["bg"]
            pygame.draw.rect(self.surface, bg, rect, border_radius=6)
            pygame.draw.rect(self.surface, st["border"], rect, 1, border_radius=6)
            col = st["text"]
        else:
            pygame.draw.rect(self.surface, DISABLED["bg"], rect, border_radius=6)
            pygame.draw.rect(self.surface, DISABLED["border"], rect, 1, border_radius=6)
            col = DISABLED["text"]
        text = f"{icon}  {label}" if icon else label
        fnt = R.font(size, "bold" if style in ("primary", "danger", "success", "selected") else "regular")
        while fnt.size(text)[0] > rect.width - 12 and len(text) > 4:
            text = text[:-2].rstrip() + "…" if not text.endswith("…") else text[:-2] + "…"
        img = fnt.render(text, True, col)
        self.surface.blit(img, img.get_rect(center=rect.center))
        if hover and tooltip:
            self.tooltip_text = tooltip
        if enabled and self.clicked(rect):
            if self.click_sound:
                self.click_sound()
            return True
        return False

    def text_input(self, rect: pygame.Rect, key: str, value: str, placeholder: str = "", max_len: int = 20,
                   allowed: str | None = None) -> str:
        """Champ de saisie mono-ligne. Renvoie la nouvelle valeur."""
        if self.clicked(rect):
            self.focus = key
        elif self.released and not rect.collidepoint(self.mouse) and self.focus == key:
            self.focus = None
        focused = self.focus == key and self.input_enabled
        pygame.draw.rect(self.surface, config.THEME["panel_alt"], rect, border_radius=6)
        pygame.draw.rect(self.surface, config.THEME["accent"] if focused else config.THEME["border"], rect,
                         2 if focused else 1, border_radius=6)
        if focused:
            for ch in self.text_typed:
                if ch.isprintable() and (allowed is None or ch in allowed) and len(value) < max_len:
                    value += ch
            if pygame.K_BACKSPACE in self.keys_down:
                value = value[:-1]
            if pygame.K_RETURN in self.keys_down or pygame.K_TAB in self.keys_down:
                self.focus = None
        shown = value if value else placeholder
        col = "text" if value else "text_muted"
        img_rect = R.draw_text_fit(self.surface, shown, (rect.x + 10, rect.centery), rect.width - 24, "body", col,
                                   anchor="midleft")
        if focused and int(self.time * 2) % 2 == 0:
            x = img_rect.right + 2 if value else rect.x + 10
            pygame.draw.line(self.surface, config.THEME["text"], (x, rect.y + 8), (x, rect.bottom - 8), 2)
        return value

    def checkbox(self, rect: pygame.Rect, checked: bool, label: str = "", enabled: bool = True) -> bool:
        """Renvoie True si l'état doit basculer."""
        box = pygame.Rect(rect.x, rect.centery - 9, 18, 18)
        pygame.draw.rect(self.surface, config.THEME["panel_alt"], box, border_radius=4)
        pygame.draw.rect(self.surface, config.THEME["accent"] if checked else config.THEME["border"], box, 2,
                         border_radius=4)
        if checked:
            pygame.draw.lines(self.surface, config.THEME["accent"], False,
                              [(box.x + 4, box.centery), (box.x + 8, box.bottom - 5), (box.right - 4, box.y + 4)], 3)
        if label:
            R.draw_text(self.surface, label, (box.right + 8, rect.centery), "body",
                        "text" if enabled else "text_muted", anchor="midleft")
        return enabled and self.clicked(rect)

    def tooltip(self, rect: pygame.Rect, text: str) -> None:
        if self.hovered(rect):
            self.tooltip_text = text

    def progress(self, rect: pygame.Rect, value: float, col: Color | None = None,
                 bg: Color | None = None) -> None:
        value = max(0.0, min(1.0, value))
        pygame.draw.rect(self.surface, bg or config.THEME["panel_alt"], rect, border_radius=rect.height // 2)
        if value > 0:
            fill = pygame.Rect(rect.x, rect.y, max(rect.height, int(rect.width * value)), rect.height)
            pygame.draw.rect(self.surface, col or config.THEME["accent"], fill, border_radius=rect.height // 2)

    # -- glisser-déposer ------------------------------------------------------------------
    def draggable(self, rect: pygame.Rect, key: str, payload: Any, label: str) -> bool:
        """Démarre un glisser si l'utilisateur appuie sur ``rect``. Renvoie True si en cours de glisser."""
        if self.drag is not None:
            return self.drag.key == key
        if self.input_enabled and self.pressed and rect.collidepoint(self.mouse) and self._visible(self.mouse):
            self.drag = DragState(key, payload, (self.mouse[0] - rect.x, self.mouse[1] - rect.y), label, rect.size)
            return True
        return False

    def drop_target(self, rect: pygame.Rect) -> DragState | None:
        """Renvoie l'élément déposé sur ``rect`` pendant cette image."""
        if self.drag is not None and rect.collidepoint(self.mouse):
            pygame.draw.rect(self.surface, config.THEME["accent"], rect, 2, border_radius=8)
        if self.released and self.drag is not None and rect.collidepoint(self.mouse):
            dropped = self.drag
            self.drag = None
            return dropped
        return None

    def _draw_tooltip(self, text: str) -> None:
        width = 360
        lines = R.wrap_text(text, R.font("small"), width - 16)
        h = len(lines) * 18 + 12
        x = min(self.mouse[0] + 16, self.surface.get_width() - width - 8)
        y = min(self.mouse[1] + 16, self.surface.get_height() - h - 8)
        rect = pygame.Rect(x, y, width, h)
        pygame.draw.rect(self.surface, (40, 46, 54), rect, border_radius=6)
        pygame.draw.rect(self.surface, (88, 96, 105), rect, 1, border_radius=6)
        for i, line in enumerate(lines):
            R.draw_text(self.surface, line, (x + 8, y + 6 + i * 18), "small", "text")


# ---------------------------------------------------------------------------
# Aides de mise en page
# ---------------------------------------------------------------------------
def split_h(rect: pygame.Rect, weights: list[float], gap: int = 12) -> list[pygame.Rect]:
    total = sum(weights)
    avail = rect.width - gap * (len(weights) - 1)
    out, x = [], rect.x
    for w in weights:
        width = int(avail * w / total)
        out.append(pygame.Rect(x, rect.y, width, rect.height))
        x += width + gap
    return out


def split_v(rect: pygame.Rect, weights: list[float], gap: int = 12) -> list[pygame.Rect]:
    total = sum(weights)
    avail = rect.height - gap * (len(weights) - 1)
    out, y = [], rect.y
    for w in weights:
        height = int(avail * w / total)
        out.append(pygame.Rect(rect.x, y, rect.width, height))
        y += height + gap
    return out


def section(surface: pygame.Surface, rect: pygame.Rect, title: str, subtitle: str = "") -> pygame.Rect:
    """Panneau titré ; renvoie la zone de contenu."""
    R.panel(surface, rect)
    R.draw_text_fit(surface, title, (rect.x + 14, rect.y + 10), rect.width - 28, "h3", "text", "bold")
    if not subtitle:
        return pygame.Rect(rect.x + 12, rect.y + 44, rect.width - 24, rect.height - 54)
    title_w = R.font("h3", "bold").size(title)[0]
    sub_w = R.font("small").size(subtitle)[0]
    if title_w + sub_w + 48 <= rect.width:
        R.draw_text(surface, subtitle, (rect.right - 14, rect.y + 14), "small", "text_muted", anchor="topright")
        return pygame.Rect(rect.x + 12, rect.y + 44, rect.width - 24, rect.height - 54)
    R.draw_text_fit(surface, subtitle, (rect.x + 14, rect.y + 38), rect.width - 28, "small", "text_muted")
    return pygame.Rect(rect.x + 12, rect.y + 64, rect.width - 24, rect.height - 74)


def severity_color(severity: str) -> Color:
    return {
        "info": config.THEME["accent"], "success": config.THEME["success"],
        "warning": config.THEME["warning"], "danger": config.THEME["danger"],
    }.get(severity, config.THEME["text_muted"])
