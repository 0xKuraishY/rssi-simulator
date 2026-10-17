"""Initialisation de l'affichage (GPU → CPU → headless) et primitives de dessin.

Ordre de tentative :
1. GPU : ``DOUBLEBUF | HWSURFACE`` et vérification ``pygame.display.Info().hw``
2. CPU : ``DOUBLEBUF | SWSURFACE``
3. Headless (CI/CD) : ``SDL_VIDEODRIVER=offscreen`` positionné avant l'init

Sans résolution imposée, la fenêtre est redimensionnable et s'adapte à l'écran : elle est
agrandie (maximisée) si 1920x1080 ne tient pas dans la zone utilisable (barres du bureau).
Sur un écran trop petit pour 1280x720, l'image est rendue en 1280x720 puis réduite (SCALED).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

import pygame

import config

log = logging.getLogger(__name__)

Color = tuple[int, int, int] | tuple[int, int, int, int]


LOGO_FILE = config.IMAGES_DIR / "logo-256.png"


@lru_cache(maxsize=8)
def logo(size: int) -> pygame.Surface | None:
    """Logo du jeu (bouclier) redimensionné, ou None si l'image est introuvable."""
    try:
        img = pygame.image.load(str(LOGO_FILE))
    except (pygame.error, FileNotFoundError):
        log.warning("Logo introuvable : %s", LOGO_FILE)
        return None
    return img if size == img.get_width() else pygame.transform.smoothscale(img, (size, size))


@dataclass(frozen=True)
class DisplayInfo:
    mode: str  # "gpu" | "cpu" | "headless"
    size: tuple[int, int]
    driver: str
    flags: int = 0


DESKTOP_MARGIN = (0, 100)  # place prise par les barres du bureau et la barre de titre


def _window_plan(size: tuple[int, int] | None, fullscreen: bool) -> tuple[tuple[int, int], int, bool]:
    """Taille de fenêtre, drapeaux supplémentaires et maximisation, selon la taille du bureau."""
    desktop = pygame.display.get_desktop_sizes()[0]
    min_w, min_h = config.MIN_RESOLUTION
    if fullscreen:
        return size or desktop, 0, False
    if size is not None:
        return (max(size[0], min_w), max(size[1], min_h)), pygame.RESIZABLE, False
    free_w, free_h = desktop[0] - DESKTOP_MARGIN[0], desktop[1] - DESKTOP_MARGIN[1]
    if free_w < min_w or free_h < min_h:
        # écran trop petit : rendu à la taille minimale, mis à l'échelle par SDL (souris comprise)
        return config.MIN_RESOLUTION, pygame.SCALED | pygame.RESIZABLE, True
    w, h = config.DEFAULT_RESOLUTION
    if w <= free_w and h <= free_h:
        return (w, h), pygame.RESIZABLE, False
    return (max(min(w, free_w), min_w), max(min(h, free_h), min_h)), pygame.RESIZABLE, True


def _maximize() -> None:
    try:
        from pygame._sdl2.video import Window
        Window.from_display_module().maximize()
    except Exception as exc:  # API interne de pygame : jamais bloquant
        log.warning("Impossible d'agrandir la fenêtre : %s", exc)


def init_display(
    size: tuple[int, int] | None = None,
    fullscreen: bool = False,
    headless: bool = False,
) -> tuple[pygame.Surface, DisplayInfo]:
    if headless:
        config.enable_headless()
    _font_cached.cache_clear()  # polices éventuellement créées avant un pygame.quit()
    logo.cache_clear()
    pygame.display.init()
    icon = logo(64)
    if icon is not None:
        pygame.display.set_icon(icon)  # barre de titre et barre des tâches, avant set_mode
    pygame.font.init()
    driver = pygame.display.get_driver()

    if config.is_headless():
        size = size or config.DEFAULT_RESOLUTION
        w = max(size[0], config.MIN_RESOLUTION[0])
        h = max(size[1], config.MIN_RESOLUTION[1])
        surface = pygame.display.set_mode((w, h))
        return surface, DisplayInfo("headless", (w, h), driver)

    (w, h), extra, maximize = _window_plan(size, fullscreen)
    if fullscreen:
        extra |= pygame.FULLSCREEN
    if extra & pygame.SCALED:
        # lissage de la réduction (SDL utilise sinon le plus proche voisin, illisible pour le texte)
        os.environ.setdefault("SDL_RENDER_SCALE_QUALITY", "linear")
    surface = None
    flags = pygame.DOUBLEBUF | pygame.HWSURFACE | extra
    try:
        surface = pygame.display.set_mode((w, h), flags)
        mode = "gpu" if pygame.display.Info().hw == 1 else "cpu"
        if mode == "cpu":
            log.info("Accélération matérielle indisponible, bascule en rendu CPU")
    except pygame.error as exc:
        log.warning("Échec du mode GPU : %s", exc)
    if surface is None or mode == "cpu":
        flags = pygame.DOUBLEBUF | pygame.SWSURFACE | extra
        surface = pygame.display.set_mode((w, h), flags)
        mode = "cpu"
    else:
        log.info("Rendu GPU actif (%s)", driver)
    if maximize:
        _maximize()
    return surface, DisplayInfo(mode, surface.get_size(), driver, flags)


def enforce_min_size(info: DisplayInfo, event: pygame.event.Event) -> None:
    """Fenêtre réduite par l'utilisateur sous la taille minimale : on la ramène à cette taille
    (en dessous, les écrans se chevauchent). Sans effet en mode SCALED, où SDL met à l'échelle."""
    if event.type != pygame.VIDEORESIZE or info.flags & (pygame.SCALED | pygame.FULLSCREEN):
        return
    min_w, min_h = config.MIN_RESOLUTION
    if event.w < min_w or event.h < min_h:
        pygame.display.set_mode((max(event.w, min_w), max(event.h, min_h)), info.flags)


# ---------------------------------------------------------------------------
# Polices
# ---------------------------------------------------------------------------
_FONT_FILES = {
    "regular": "DejaVuSans.ttf",
    "bold": "DejaVuSans-Bold.ttf",
    "mono": "DejaVuSansMono.ttf",
}


def font(size: int | str = "body", weight: str = "regular") -> pygame.font.Font:
    """Police mise en cache. Le cache est vidé si pygame a été réinitialisé entre-temps
    (un objet Font utilisé après pygame.quit() provoque une erreur fatale de SDL_ttf)."""
    if not pygame.font.get_init():
        _font_cached.cache_clear()
        pygame.font.init()
    return _font_cached(size, weight)


@lru_cache(maxsize=96)
def _font_cached(size: int | str, weight: str) -> pygame.font.Font:
    px = config.FONT_SIZES[size] if isinstance(size, str) else int(size)
    path = config.FONTS_DIR / _FONT_FILES.get(weight, _FONT_FILES["regular"])
    if path.exists():
        return pygame.font.Font(str(path), px)
    return pygame.font.SysFont("dejavusans,arial,sans", px, bold=weight == "bold")


def color(name: str) -> Color:
    return config.THEME[name]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def draw_text(
    surface: pygame.Surface,
    text: str,
    pos: tuple[int, int],
    size: int | str = "body",
    col: Color | str = "text",
    weight: str = "regular",
    anchor: str = "topleft",
) -> pygame.Rect:
    c = config.THEME[col] if isinstance(col, str) else col
    img = font(size, weight).render(text, True, c)
    rect = img.get_rect(**{anchor: pos})
    surface.blit(img, rect)
    return rect


def draw_text_fit(
    surface: pygame.Surface,
    text: str,
    pos: tuple[int, int],
    max_width: int,
    size: int | str = "body",
    col: Color | str = "text",
    weight: str = "regular",
    anchor: str = "topleft",
    min_size: int = 12,
) -> pygame.Rect:
    """Comme draw_text, en réduisant la taille de police puis en tronquant pour tenir dans max_width."""
    px = config.FONT_SIZES[size] if isinstance(size, str) else int(size)
    while px > min_size and font(px, weight).size(text)[0] > max_width:
        px -= 1
    while len(text) > 2 and font(px, weight).size(text)[0] > max_width:
        text = text[:-2].rstrip() + "…"
    return draw_text(surface, text, pos, px, col, weight, anchor)


def wrap_text(text: str, fnt: pygame.font.Font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if fnt.size(candidate)[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def draw_wrapped(
    surface: pygame.Surface,
    text: str,
    rect: pygame.Rect,
    size: int | str = "body",
    col: Color | str = "text",
    weight: str = "regular",
    line_spacing: int = 4,
) -> int:
    """Dessine un texte multi-ligne dans ``rect`` ; renvoie la hauteur utilisée."""
    fnt = font(size, weight)
    c = config.THEME[col] if isinstance(col, str) else col
    y = rect.y
    for line in wrap_text(text, fnt, rect.width):
        if y + fnt.get_height() > rect.bottom:
            break
        surface.blit(fnt.render(line, True, c), (rect.x, y))
        y += fnt.get_height() + line_spacing
    return y - rect.y


def measure_wrapped(text: str, width: int, size: int | str = "body", weight: str = "regular",
                    line_spacing: int = 4) -> int:
    fnt = font(size, weight)
    return len(wrap_text(text, fnt, width)) * (fnt.get_height() + line_spacing)


def panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    bg: Color | str = "panel",
    border: Color | str | None = "border",
    radius: int = 8,
    width: int = 1,
) -> None:
    b = config.THEME[bg] if isinstance(bg, str) else bg
    pygame.draw.rect(surface, b, rect, border_radius=radius)
    if border is not None:
        bc = config.THEME[border] if isinstance(border, str) else border
        pygame.draw.rect(surface, bc, rect, width, border_radius=radius)


def blend(c1: Color, c2: Color, t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1[:3], c2[:3]))  # type: ignore[return-value]


def format_eur(amount: float) -> str:
    """Format monétaire français : 1 234 567 €."""
    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(round(amount)):,} €".replace(",", " ")
