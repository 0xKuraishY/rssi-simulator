"""Menu principal : Nouvelle partie | Reprendre | Options | Crédits & Sources | Quitter."""
from __future__ import annotations

import math

import pygame

import config
from engine import renderer as R
from game.state import GameScreen
from ui.components.iso_map import draw_background_city
from ui.components.widgets import UI
from ui.screens.base import Screen

SOURCES = [
    ("Méthodes et référentiels", [
        "ANSSI — EBIOS Risk Manager, guide méthodologique (2018, v1.5 2024)",
        "ANSSI — Guide d'hygiène informatique en 42 mesures (2017)",
        "ANSSI — Crise d'origine cyber : les clés d'une gestion opérationnelle et stratégique (2021)",
        "ANSSI / Ministère de la Justice — Attaques par rançongiciels, tous concernés (2020)",
        "ANSSI — Panoramas de la cybermenace (CERT-FR)",
        "MITRE ATT&CK® Enterprise et ICS — attack.mitre.org",
        "ISO/IEC 27001:2022 et ISO/IEC 27002:2022",
    ]),
    ("Textes réglementaires", [
        "Règlement (UE) 2016/679 (RGPD), art. 30, 33, 34, 37-39, 83",
        "Directive (UE) 2022/2555 (NIS2), art. 20, 21, 23, 34",
        "Code de la défense, art. L.1332-6-1 et suivants (OIV)",
        "Code de la santé publique, art. L.1111-8 et L.1111-8-2",
        "Code des assurances, art. L.12-10-1 (loi LOPMI 2023)",
    ]),
    ("Données de marché et de coûts", [
        "Fourchettes de coûts issues du cahier des charges (Hiscox, CESIN 2024), à titre pédagogique",
        "Cybermalveillance.gouv.fr — fiches réflexes et rapports d'activité",
        "AMRAE — Rapport LUCY sur l'assurance cyber",
    ]),
    ("Licences", [
        "Code source : GNU General Public License v3",
        "Contenus pédagogiques (scénarios, données) : Creative Commons BY-SA 4.0",
        "Police DejaVu : licence libre Bitstream Vera / domaine public (voir assets/fonts)",
        "Publications ANSSI réutilisées selon la Licence Ouverte d'Etalab",
        "© The MITRE Corporation. ATT&CK® est reproduit et distribué avec la permission de The MITRE Corporation.",
        "Intitulés ISO/IEC 27001 : traductions libres et résumées, la norme reste la propriété de l'ISO",
        "Développé avec Claude Code (Anthropic)",
        "Ce jeu est un outil de formation : il ne constitue ni un conseil juridique ni un barème officiel.",
    ]),
]


class MainMenuScreen(Screen):
    name = GameScreen.MENU.value
    show_hud = False

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.mode = "main"
        self.t = 0.0

    def on_enter(self, **kwargs: object) -> None:
        self.mode = "main"

    def update(self, dt: float) -> None:
        self.t += dt

    def _background(self, surf: pygame.Surface) -> None:
        draw_background_city(surf, self.t)
        w, h = surf.get_size()
        for i in range(0, w, 48):
            pygame.draw.line(surf, (18, 22, 30), (i, 0), (i, h))
        for j in range(0, h, 48):
            pygame.draw.line(surf, (18, 22, 30), (0, j), (w, j))
        # quelques nœuds « réseau » animés, très discrets
        for k in range(14):
            x = (k * 173 + 60) % w
            y = (k * 97 + 120) % h
            r = 3 + 2 * math.sin(self.t * 1.3 + k)
            pygame.draw.circle(surf, (30, 60, 110), (x, y), max(1, int(r)))

    def _logo(self, surf: pygame.Surface, center: tuple[int, int]) -> None:
        img = R.logo(104)
        if img is not None:
            surf.blit(img, img.get_rect(center=center))
            return
        cx, cy = center
        shield = [(cx, cy - 46), (cx + 38, cy - 32), (cx + 34, cy + 14), (cx, cy + 44), (cx - 34, cy + 14),
                  (cx - 38, cy - 32)]
        pygame.draw.polygon(surf, (23, 63, 128), shield)
        pygame.draw.polygon(surf, config.THEME["accent"], shield, 3)
        pygame.draw.lines(surf, (255, 255, 255), False, [(cx - 14, cy), (cx - 3, cy + 12), (cx + 17, cy - 12)], 5)

    def draw_content(self, ui: UI) -> None:
        surf = ui.surface
        w, h = surf.get_size()
        self._background(surf)
        if self.mode == "options":
            self._options(ui)
            return
        if self.mode == "credits":
            self._credits(ui)
            return
        if self.mode == "load":
            self._load(ui)
            return
        top = max(64, h // 2 - 320)
        self._logo(surf, (w // 2, top))
        R.draw_text(surf, "RSSI Simulator", (w // 2, top + 60), "title", "text", "bold", anchor="midtop")
        R.draw_text(surf, "Simulateur de crise", (w // 2, top + 128), "h2", "text_muted", anchor="midtop")
        bw, bh = 340, 42
        x = w // 2 - bw // 2
        y = top + 176
        latest = self.app.saves.latest()
        if ui.button(pygame.Rect(x, y, bw, bh), "Nouvelle partie", "primary"):
            self.app.leave_network()
            self.app.switch(GameScreen.ORG_SELECT)
        y += bh + 12
        label = "Reprendre" + (f" — semaine {latest.turn}" if latest else "")
        if ui.button(pygame.Rect(x, y, bw, bh), label, "secondary", enabled=latest is not None,
                     tooltip="Reprend la dernière partie sauvegardée"):
            self.app.resume_game(latest.slot if latest else "auto")
        y += bh + 12
        if ui.button(pygame.Rect(x, y, bw, bh), "Charger une partie", "secondary", enabled=latest is not None):
            self.mode = "load"
        y += bh + 12
        if ui.button(pygame.Rect(x, y, bw, bh), "Session en réseau local", "secondary",
                     tooltip="Formation en groupe : héberger ou rejoindre une partie sur le même réseau"):
            self.app.switch(GameScreen.LOBBY)
        y += bh + 12
        if ui.button(pygame.Rect(x, y, bw, bh), "Comment jouer ?", "secondary",
                     tooltip="But du jeu et fonctionnement (F1)"):
            self.app.help.toggle(0)
        y += bh + 12
        if ui.button(pygame.Rect(x, y, bw, bh), "Options"):
            self.mode = "options"
        y += bh + 12
        if ui.button(pygame.Rect(x, y, bw, bh), "Crédits & Sources"):
            self.mode = "credits"
            ui.reset_scroll("credits")
        y += bh + 12
        if ui.button(pygame.Rect(x, y, bw, bh), "Quitter", "ghost") or ui.key(pygame.K_ESCAPE):
            self.app.running = False
        R.draw_text(surf, f"Version {config.VERSION} · Code GPL v3 · Contenus CC BY-SA 4.0 · 100 % hors ligne",
                    (w // 2, h - 30), "small", "text_muted", anchor="midbottom")
        R.draw_text(surf, f"Rendu : {self.app.display.mode.upper()} · Narration : {self.app.narrator.backend}",
                    (w - 16, h - 30), "small", "text_muted", anchor="bottomright")

    # -- chargement -------------------------------------------------------------------------
    def _load(self, ui: UI) -> None:
        surf = ui.surface
        w, h = surf.get_size()
        rect = pygame.Rect(w // 2 - 480, 70, 960, h - 140)
        R.panel(surf, rect)
        R.draw_text(surf, "Charger une partie", (rect.x + 24, rect.y + 18), "h1", "text", "bold")
        slot_names = {"auto": "Sauvegarde automatique", "reseau": "Dernière partie en réseau",
                      "slot1": "Emplacement 1", "slot2": "Emplacement 2", "slot3": "Emplacement 3"}
        y = rect.y + 80
        for info in self.app.saves.list_saves():
            row = pygame.Rect(rect.x + 24, y, rect.width - 48, 64)
            R.panel(surf, row, "panel_alt", None)
            org = self.app.data.organisations.get(info.org_id)
            R.draw_text(surf, slot_names.get(info.slot, info.slot), (row.x + 14, row.y + 8), "body", "text", "bold")
            R.draw_text_fit(surf, info.label or (org.nom if org else info.org_id), (row.x + 14, row.y + 34),
                            row.width - 330, "small", "text_muted")
            R.draw_text(surf, info.updated_at.astimezone().strftime("%d/%m/%Y %H:%M"), (row.right - 300, row.y + 10),
                        "small", "text_muted")
            if ui.button(pygame.Rect(row.right - 270, row.y + 12, 140, 40), "Charger", "primary"):
                self.app.resume_game(info.slot)
                return
            if ui.button(pygame.Rect(row.right - 122, row.y + 12, 110, 40), "Supprimer", "ghost"):
                self.app.saves.delete(info.slot)
            y += 72
            if y > rect.bottom - 140:
                break
        if ui.button(pygame.Rect(rect.right - 224, rect.bottom - 64, 200, 44), "Retour", "primary") \
                or ui.key(pygame.K_ESCAPE):
            self.mode = "main"

    # -- options ----------------------------------------------------------------------------
    def _options(self, ui: UI) -> None:
        surf = ui.surface
        w, h = surf.get_size()
        rect = pygame.Rect(w // 2 - 380, 80, 760, h - 160)
        R.panel(surf, rect)
        R.draw_text(surf, "Options", (rect.x + 24, rect.y + 20), "h1", "text", "bold")
        s = self.app.settings
        y = rect.y + 100
        R.draw_text(surf, f"Volume : {int(s['volume'] * 100)} %", (rect.x + 24, y + 10), "body")
        if ui.button(pygame.Rect(rect.x + 360, y, 50, 40), "−"):
            s["volume"] = max(0.0, round(s["volume"] - 0.1, 1))
            self.app.audio.set_volume(s["volume"])
        if ui.button(pygame.Rect(rect.x + 420, y, 50, 40), "+"):
            s["volume"] = min(1.0, round(s["volume"] + 0.1, 1))
            self.app.audio.set_volume(s["volume"])
            self.app.audio.play("notify")
        y += 64
        toggles = [
            ("fullscreen", "Plein écran (au prochain démarrage)"),
            ("timers", "Comptes à rebours en temps réel pour les décisions urgentes"),
            ("ai", "Narration par IA locale si un modèle est installé (au prochain démarrage)"),
            ("tour_enabled", "Visite guidée et bulles d'aide en difficulté Découverte"),
        ]
        s["tour_enabled"] = not s.get("tour_disabled", False)
        for key, label in toggles:
            if ui.checkbox(pygame.Rect(rect.x + 24, y, rect.width - 48, 36), bool(s[key]), label):
                s[key] = not s[key]
                if key == "tour_enabled":
                    s["tour_disabled"] = not s[key]
            y += 50
        y += 10
        R.draw_wrapped(surf,
                       "Le mode sans compte à rebours est recommandé pour un usage en formation accompagnée ou pour "
                       "des raisons d'accessibilité. Aucune donnée n'est envoyée sur Internet ; les sauvegardes sont "
                       f"stockées dans : {config.user_data_dir()}",
                       pygame.Rect(rect.x + 24, y, rect.width - 48, 90), "small", "text_muted")
        y += 100
        if ui.button(pygame.Rect(rect.x + 24, y, 300, 42), "Revoir le tutoriel à la prochaine partie"):
            s["tutorial_done"] = False
            self.app.toast("Le tutoriel sera affiché à la prochaine partie.")
        if ui.button(pygame.Rect(rect.right - 224, rect.bottom - 66, 200, 46), "Enregistrer", "primary") \
                or ui.key(pygame.K_ESCAPE):
            self.app.save_settings()
            self.mode = "main"

    # -- crédits ------------------------------------------------------------------------------
    def _credits(self, ui: UI) -> None:
        surf = ui.surface
        w, h = surf.get_size()
        rect = pygame.Rect(w // 2 - 480, 60, 960, h - 120)
        R.panel(surf, rect)
        R.draw_text(surf, "Crédits & Sources", (rect.x + 24, rect.y + 18), "h1", "text", "bold")
        area = pygame.Rect(rect.x + 24, rect.y + 80, rect.width - 48, rect.height - 160)
        off = ui.begin_scroll("credits", area)
        y = area.y + off
        intro = ("RSSI Simulator est un jeu sérieux de sensibilisation à la gestion des risques et des crises cyber. "
                 "Les organisations sont fictives ; les mécaniques s'appuient sur les publications officielles "
                 "ci-dessous. Les références sont citées pour permettre au formateur et à l'apprenant d'approfondir.")
        y += R.draw_wrapped(surf, intro, pygame.Rect(area.x, y, area.width - 12, 200), "body", "text_muted") + 16
        for title, lines in SOURCES:
            R.draw_text(surf, title, (area.x, y), "h3", "accent", "bold")
            y += 32
            for line in lines:
                y += R.draw_wrapped(surf, "• " + line, pygame.Rect(area.x + 8, y, area.width - 20, 80), "body") + 4
            y += 14
        ui.end_scroll("credits", area, y - (area.y + off))
        if ui.button(pygame.Rect(rect.right - 224, rect.bottom - 64, 200, 44), "Retour", "primary") \
                or ui.key(pygame.K_ESCAPE):
            self.mode = "main"
