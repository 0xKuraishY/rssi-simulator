"""Configuration centrale de RSSI Simulator.

Toutes les constantes partagées (chemins, affichage, thème, règles de jeu,
délais réglementaires) sont définies ici. Aucun module ne doit coder en dur
un chemin ou une valeur métier transverse.

Licence : GNU GPL v3.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
APP_NAME = "RSSI Simulator"
APP_TITLE = "RSSI Simulator"
APP_SLUG = "rssi-simulator"
LEGACY_SLUG = "cyber-rssi"  # ancien nom du jeu : dossier de données repris au premier lancement
VERSION = "0.1.1"
DEFAULT_LANG = "fr"
SUPPORTED_LANGS = ("fr",)

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------


def _resource_root() -> Path:
    """Racine des ressources embarquées (compatible PyInstaller --onefile)."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root)
    return Path(__file__).resolve().parent


def user_data_dir() -> Path:
    """Dossier de données utilisateur, seul emplacement d'écriture du jeu.

    - Windows : %APPDATA%/rssi-simulator
    - Linux   : $XDG_DATA_HOME/rssi-simulator, sinon ~/.local/share/rssi-simulator
    - macOS   : ~/Library/Application Support/rssi-simulator (non officiellement supporté)

    La variable RSSI_SIMULATOR_DATA_DIR permet de surcharger (tests, mode portable).
    """
    override = os.environ.get("RSSI_SIMULATOR_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / APP_SLUG
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_SLUG
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / APP_SLUG


ROOT_DIR = _resource_root()
SCENARIOS_DIR = ROOT_DIR / "scenarios"
ORGANISATIONS_DIR = SCENARIOS_DIR / "organisations"
INCIDENTS_DIR = SCENARIOS_DIR / "incidents"
EVENTS_DIR = SCENARIOS_DIR / "events"
DATA_DIR = ROOT_DIR / "data"
THREATS_DIR = DATA_DIR / "threats"
MEASURES_DIR = DATA_DIR / "measures"
REGULATIONS_DIR = DATA_DIR / "regulations"
ASSETS_DIR = ROOT_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
IMAGES_DIR = ASSETS_DIR / "images"
SOUNDS_DIR = ASSETS_DIR / "sounds"


@dataclass(frozen=True)
class UserPaths:
    """Chemins d'écriture, résolus à l'exécution (dépendent de l'environnement)."""

    root: Path

    @property
    def saves_db(self) -> Path:
        return self.root / "saves.sqlite3"

    @property
    def reports_dir(self) -> Path:
        return self.root / "rapports"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.yaml"

    @property
    def log_file(self) -> Path:
        return self.root / "rssi-simulator.log"

    def ensure(self) -> "UserPaths":
        legacy = self.root.with_name(LEGACY_SLUG)
        if self.root.name == APP_SLUG and not self.root.exists() and legacy.is_dir():
            legacy.rename(self.root)
            old_log = self.root / f"{LEGACY_SLUG}.log"
            if old_log.exists():
                old_log.rename(self.log_file)
        for directory in (self.root, self.reports_dir, self.models_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def user_paths() -> UserPaths:
    return UserPaths(user_data_dir())


# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------
MIN_RESOLUTION = (1280, 720)
DEFAULT_RESOLUTION = (1920, 1080)
FPS = 60
HEADLESS_ENV = "SDL_VIDEODRIVER"
HEADLESS_DRIVER = "offscreen"

# Thème sombre, sobre et professionnel. Couleurs RGB.
THEME = {
    "bg": (14, 17, 23),
    "panel": (22, 27, 34),
    "panel_alt": (30, 36, 45),
    "border": (48, 56, 68),
    "text": (230, 233, 237),
    "text_muted": (139, 148, 158),
    "accent": (56, 139, 253),
    "accent_hover": (88, 166, 255),
    "success": (63, 185, 80),
    "warning": (210, 153, 34),
    "danger": (248, 81, 73),
    "critical": (190, 30, 45),
}

# Couleurs de la matrice de risque EBIOS RM 4×4, par niveau (V×G : 1..16).
RISK_COLORS = {
    "faible": (63, 185, 80),       # 1-3
    "modere": (210, 153, 34),      # 4-6
    "eleve": (230, 100, 40),       # 8-9
    "critique": (190, 30, 45),     # 12-16
}

FONT_FAMILY = "DejaVuSans"  # Fichier TTF embarqué dans assets/fonts (fallback police système)
FONT_SIZES = {"small": 14, "body": 17, "h3": 21, "h2": 26, "h1": 36, "title": 56}

# ---------------------------------------------------------------------------
# Règles de jeu
# ---------------------------------------------------------------------------
WEEKS_PER_YEAR = 52
GAME_YEARS = 3
TOTAL_TURNS = WEEKS_PER_YEAR * GAME_YEARS  # 156 tours, 1 tour = 1 semaine
START_DATE = date(2026, 1, 5)  # Lundi de la semaine 1

# Échelles EBIOS RM
LIKELIHOOD_SCALE = (1, 2, 3, 4)  # V1 Peu vraisemblable → V4 Quasi certain
SEVERITY_SCALE = (1, 2, 3, 4)    # G1 Mineure → G4 Critique
DICT_CRITERIA = ("D", "I", "C", "T")

# Réputation : 4 dimensions, valeurs initiales et pondération du score global.
REPUTATION_INITIAL = {
    "utilisateurs": 75,
    "partenaires": 80,
    "regulateurs": 70,
    "presse": 65,
}
REPUTATION_WEIGHTS = {
    "utilisateurs": 0.30,
    "partenaires": 0.25,
    "regulateurs": 0.25,
    "presse": 0.20,
}
REPUTATION_GAME_OVER = 20      # score global < 20 → fin de partie
REPUTATION_CONTRACT_LOSS = 40  # score global < 40 → perte d'un contrat majeur

# Postes budgétaires SSI
BUDGET_CATEGORIES = (
    "outils",
    "formation",
    "audit",
    "assurance",
    "externalisation",
    "divers",
)

# Grille d'évaluation finale (borne basse incluse)
SCORE_GRADES = (
    (0, "Insuffisant"),
    (40, "Moyen"),
    (65, "Bon"),
    (85, "Expert"),
)

# ---------------------------------------------------------------------------
# Délais réglementaires (en heures, à compter de la détection)
# ---------------------------------------------------------------------------
DEADLINES_HOURS = {
    "cnil_notification": 72,          # RGPD Art. 33
    "nis2_alerte_precoce": 24,        # NIS2 Art. 23 §4 a)
    "nis2_notification": 72,          # NIS2 Art. 23 §4 b)
    "nis2_rapport_final": 24 * 30,    # NIS2 Art. 23 §4 d) — un mois
    "lpm_oiv_declaration": 24,        # Opérateur télécom / OIV
}
# Seuil d'alerte visuelle (clignotement rouge) avant échéance
DEADLINE_WARNING_RATIO = 0.25  # dernier quart du délai

# RGPD : seuil employés pour la désignation obligatoire d'un DPO (règle du jeu)
DPO_EMPLOYEE_THRESHOLD = 250

# ---------------------------------------------------------------------------
# IA narrative (optionnelle, 100 % locale)
# ---------------------------------------------------------------------------
AI_ENABLED_ENV = "RSSI_SIMULATOR_AI"           # "0" pour forcer le mode statique
AI_MODEL_ENV = "RSSI_SIMULATOR_MODEL"          # chemin explicite d'un modèle GGUF
AI_CONTEXT_SIZE = 4096
AI_MAX_TOKENS = 256
AI_TEMPERATURE = 0.7


def is_headless() -> bool:
    return os.environ.get(HEADLESS_ENV) == HEADLESS_DRIVER


def enable_headless() -> None:
    """À appeler AVANT pygame.init() (CI/CD, tests)."""
    os.environ[HEADLESS_ENV] = HEADLESS_DRIVER
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
