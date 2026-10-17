"""Boîtes de dialogue modales (information, choix, tutoriel paginé)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pygame

from engine import renderer as R
from ui.components.widgets import UI


@dataclass
class DialogButton:
    label: str
    action: Callable[[], None] | None = None
    style: str = "secondary"
    enabled: bool = True
    tooltip: str | None = None
    closes: bool = True


@dataclass
class DialogBox:
    title: str
    body: str
    buttons: list[DialogButton] = field(default_factory=lambda: [DialogButton("Fermer", style="primary")])
    subtitle: str = ""
    accent: tuple[int, int, int] = (56, 139, 253)
    width: int = 760
    vertical_buttons: bool = False
    closed: bool = False

    def draw(self, ui: UI) -> None:
        surf = ui.surface
        sw, sh = surf.get_size()
        veil = pygame.Surface((sw, sh), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 170))
        surf.blit(veil, (0, 0))
        width = min(self.width, sw - 32)
        body_w = width - 48
        body_h = R.measure_wrapped(self.body, body_w, "body")
        if self.vertical_buttons:
            btn_h = len(self.buttons) * 52
        else:
            btn_h = 56
        height = min(sh - 40, 110 + body_h + btn_h + (24 if self.subtitle else 0))
        rect = pygame.Rect(0, 0, width, height)
        rect.center = (sw // 2, sh // 2)
        R.panel(surf, rect, "panel", "border", radius=10)
        pygame.draw.rect(surf, self.accent, (rect.x, rect.y, rect.width, 5), border_top_left_radius=10,
                         border_top_right_radius=10)
        y = rect.y + 22
        R.draw_text(surf, self.title, (rect.x + 24, y), "h2", "text", "bold")
        y += 40
        if self.subtitle:
            R.draw_text(surf, self.subtitle, (rect.x + 24, y), "small", "text_muted")
            y += 24
        body_rect = pygame.Rect(rect.x + 24, y, body_w, rect.bottom - btn_h - 24 - y)
        R.draw_wrapped(surf, self.body, body_rect, "body", "text")
        if self.vertical_buttons:
            by = rect.bottom - btn_h - 8
            for b in self.buttons:
                r = pygame.Rect(rect.x + 24, by, width - 48, 44)
                self._button(ui, r, b)
                by += 52
        else:
            bw = min(240, (width - 48 - 12 * (len(self.buttons) - 1)) // max(1, len(self.buttons)))
            x = rect.right - 24 - len(self.buttons) * bw - 12 * (len(self.buttons) - 1)
            for b in self.buttons:
                r = pygame.Rect(x, rect.bottom - 64, bw, 44)
                self._button(ui, r, b)
                x += bw + 12

    def _button(self, ui: UI, rect: pygame.Rect, b: DialogButton) -> None:
        if ui.button(rect, b.label, b.style, b.enabled, b.tooltip, size="body"):
            if b.action:
                b.action()
            if b.closes:
                self.closed = True


class DialogStack:
    """File de dialogues modaux : seul le premier est affiché et interactif."""

    def __init__(self) -> None:
        self.items: list[DialogBox] = []

    def push(self, dialog: DialogBox) -> DialogBox:
        self.items.append(dialog)
        return dialog

    def info(self, title: str, body: str, severity: str = "info") -> DialogBox:
        colors = {"info": (56, 139, 253), "success": (63, 185, 80), "warning": (210, 153, 34),
                  "danger": (248, 81, 73)}
        return self.push(DialogBox(title, body, accent=colors.get(severity, (56, 139, 253))))

    @property
    def active(self) -> bool:
        return bool(self.items)

    def draw(self, ui: UI) -> None:
        self.items = [d for d in self.items if not d.closed]
        if self.items:
            self.items[0].draw(ui)
            self.items = [d for d in self.items if not d.closed]


TUTORIAL_PAGES = [
    ("Bienvenue, RSSI",
     "Vous venez de prendre vos fonctions de responsable de la sécurité des systèmes d'information. "
     "Votre mandat dure 3 ans (156 semaines). Chaque tour représente une semaine.\n\n"
     "Objectif : protéger l'organisation, respecter la réglementation et préserver la confiance de "
     "tous — usagers, partenaires, régulateurs et presse."),
    ("Le tableau de bord",
     "En haut, le bandeau rappelle la date, le budget SSI restant, la réputation globale et la semaine.\n\n"
     "À gauche : vos indicateurs (4 jauges de réputation, niveau de risque). Au centre : le fil "
     "d'actualité. À droite : vos actions. « Passer à la semaine suivante » fait avancer le temps."),
    ("Analyser avant d'agir",
     "L'atelier EBIOS Risk Manager (méthode de l'ANSSI) vous guide en 5 étapes : cadrage et socle "
     "d'hygiène, sources de risque, scénarios stratégiques, scénarios opérationnels (MITRE ATT&CK) "
     "et traitement du risque.\n\nUne analyse de risques à jour est exigée par NIS2 (art. 21)."),
    ("Budget et mesures",
     "Votre budget SSI annuel est limité. Chaque mesure a un coût de déploiement, une maintenance "
     "annuelle et un délai avant d'être opérationnelle. Le simulateur de ROI compare le coût d'une "
     "mesure aux pertes qu'elle permet d'éviter."),
    ("Votre équipe et vos journées",
     "Votre équipe SSI dispose d'une capacité limitée (jours-homme par semaine) : déployer des mesures, corriger "
     "des vulnérabilités, mener les ateliers EBIOS ou les démarches de conformité la consomme. Une équipe "
     "surchargée retarde les chantiers et finit par s'épuiser.\n\nL'écran « Opérations SSI » regroupe les "
     "vulnérabilités publiées par le CERT-FR, la charge de l'équipe, la vigilance du personnel et la veille."),
    ("La direction vous observe",
     "Chaque trimestre, vous présentez votre bilan au comité de direction : demandez une rallonge, un "
     "recrutement, un exercice de crise… La direction vous a fixé 3 objectifs de mandat.\n\nSi sa confiance "
     "s'effondre (crises mal gérées, sanctions, objectifs manqués), elle peut mettre fin à vos fonctions."),
    ("Les incidents",
     "Certaines compromissions restent invisibles des semaines durant. Lorsqu'un incident est "
     "détecté, la salle de crise s'ouvre : prenez les décisions de confinement, d'éradication et de "
     "reprise.\n\nSurveillez les délais réglementaires : alerte ANSSI sous 24 h (NIS2), notification "
     "CNIL sous 72 h (RGPD art. 33), plainte sous 72 h pour être indemnisé par l'assureur."),
    ("Fin de partie",
     "La partie s'arrête au bout de 3 ans ou si la réputation globale passe sous 20/100. Sous 40, "
     "un partenaire majeur se retire.\n\nUn rapport HTML détaillé (décisions, erreurs, références "
     "officielles) peut être généré pour votre dossier de formation. Bonne prise de poste !"),
]


def tutorial_dialogs(on_finish: Callable[[], None]) -> list[DialogBox]:
    """Tutoriel obligatoire : pages enchaînées, sans possibilité de passer."""
    dialogs = []
    n = len(TUTORIAL_PAGES)
    for i, (title, body) in enumerate(TUTORIAL_PAGES):
        last = i == n - 1
        dialogs.append(DialogBox(
            title, body, subtitle=f"Tutoriel — étape {i + 1}/{n}",
            buttons=[DialogButton("Commencer le mandat" if last else "Suivant", on_finish if last else None,
                                  style="primary")],
        ))
    return dialogs
