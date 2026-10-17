"""Initialisation de l'affichage (GPU → CPU → headless) et primitives de dessin.

Ordre de tentative :
1. GPU : ``DOUBLEBUF | HWSURFACE`` et vérification ``pygame.display.Info().hw``
2. CPU : ``DOUBLEBUF | SWSURFACE``
3. Headless (CI/CD) : ``SDL_VIDEODRIVER=offscreen`` positionné avant l'init
"""
from __future__ import annotations

import logging
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


def init_display(
    size: tuple[int, int] = config.DEFAULT_RESOLUTION,
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
    w = max(size[0], config.MIN_RESOLUTION[0])
    h = max(size[1], config.MIN_RESOLUTION[1])
    extra = pygame.FULLSCREEN if fullscreen and not config.is_headless() else 0
    driver = pygame.display.get_driver()

    if config.is_headless():
        surface = pygame.display.set_mode((w, h))
        return surface, DisplayInfo("headless", (w, h), driver)

    try:
        surface = pygame.display.set_mode((w, h), pygame.DOUBLEBUF | pygame.HWSURFACE | extra)
        if pygame.display.Info().hw == 1:
            log.info("Rendu GPU actif (%s)", driver)
            return surface, DisplayInfo("gpu", surface.get_size(), driver)
        log.info("Accélération matérielle indisponible, bascule en rendu CPU")
    except pygame.error as exc:
        log.warning("Échec du mode GPU : %s", exc)

    surface = pygame.display.set_mode((w, h), pygame.DOUBLEBUF | pygame.SWSURFACE | extra)
    return surface, DisplayInfo("cpu", surface.get_size(), driver)


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
