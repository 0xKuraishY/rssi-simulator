"""Aide du jeu : fenêtre « Aide » à rubriques (F1) et visites guidées par bulles.

- ``HelpOverlay`` : but du jeu et fonctionnement complet, accessible partout.
- ``CoachTour`` : visite guidée qui met en lumière une zone de l'écran et l'explique
  (affichée en difficulté Découverte au lancement et à la première ouverture de chaque écran).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import pygame

import config
from engine import renderer as R
from ui.components.widgets import UI

# =============================================================================
# Contenu de l'aide
# =============================================================================
HELP_SECTIONS: list[tuple[str, str]] = [
    ("But du jeu", """\
## Votre mission
Vous êtes le RSSI (responsable de la sécurité des systèmes d'information) d'une organisation française : hôpital, mairie, PME industrielle, ESN ou opérateur télécom. Votre mandat dure 1 à 3 ans ; chaque tour représente une semaine.
## Ce qu'il faut réussir
- Protéger l'organisation contre les cyberattaques avec un budget et une équipe limités.
- Gérer les crises quand une attaque est détectée, en prenant les bonnes décisions.
- Respecter la réglementation (RGPD, NIS2, LPM, ISO 27001) et ses délais de notification.
- Garder la confiance de tous : usagers, partenaires, régulateurs, presse… et votre direction.
## Comment on perd
- Réputation globale sous 20/100 : perte de confiance totale, fin de partie.
- Confiance de la direction trop basse : vous êtes remercié(e).
- Sous 40/100 de réputation, un partenaire majeur se retire (sans fin de partie).
## Comment on gagne
Terminez le mandat avec le meilleur score possible (0 à 100) : Insuffisant, Moyen, Bon ou Expert. Un rapport HTML détaillé, avec vos meilleures décisions, vos erreurs et les références officielles, peut être généré à la fin."""),
    ("Une semaine type", """\
## Le rythme du jeu
Le temps n'avance que lorsque vous cliquez sur « Passer à la semaine suivante » (ou touche Espace). Prenez le temps de réfléchir : rien ne se passe tant que vous ne validez pas.
## Une bonne routine
- Lisez le fil d'actualité : nouvelles vulnérabilités, bulletins de veille, contrôles annoncés.
- Ouvrez « Opérations SSI » si une vulnérabilité critique apparaît (bouton rouge).
- Lancez ou poursuivez vos chantiers : analyse EBIOS RM, achat de mesures, conformité.
- Surveillez la charge de votre équipe : une équipe surchargée retarde tout et s'épuise.
- Passez à la semaine suivante.
## Ce qui peut vous interrompre
- Un événement (alerte, demande de la direction…) : choisissez une réponse.
- Le comité de direction, chaque trimestre : présentez votre bilan.
- Un incident détecté : la salle de crise s'ouvre.
Tant qu'une de ces décisions est en attente, la semaine ne peut pas avancer."""),
    ("Le tableau de bord", """\
## Bandeau du haut
Date, budget SSI restant, réputation globale, niveau de risque et semaine en cours.
## Colonne de gauche
- Indicateurs : budget, les 4 jauges de réputation, la confiance de la direction et le niveau de menace.
- Carte du SI en 3D : chaque bâtiment est un bien support (application, serveur, réseau). Vert = sain, jaune = vulnérabilité critique exposée, orange = en reprise après incident, rouge clignotant = crise en cours. Le bouton « Matrice » affiche la matrice des risques EBIOS.
## Colonne centrale
Le fil d'actualité (le plus récent en haut) et vos 3 objectifs de mandat (ou le classement en réseau).
## Colonne de droite
Vos actions : analyse de risques, budget, conformité, opérations, puis le bouton pour avancer d'une semaine. En dessous : la charge de l'équipe, les mesures en déploiement et les contrôles annoncés."""),
    ("Incidents et crises", """\
## Une attaque se déroule en 7 phases
1. Compromission initiale, 2. Latence : invisibles pour vous. Sans outils de détection (journalisation, SIEM, SOC, EDR), l'attaquant peut rester des semaines dans le SI.
3. Détection : la salle de crise s'ouvre.
4 à 6. Confinement, éradication, reprise : 3 à 5 décisions horodatées (H+1, H+4…).
7. Retour d'expérience à la clôture.
## Les délais réglementaires
- Alerte précoce ANSSI : 24 h (NIS2) ; déclaration OIV : 24 h (LPM) ; signalement ARS : 24 h (santé).
- Notification CNIL : 72 h (RGPD art. 33) ; notification ANSSI : 72 h (NIS2).
- Plainte sous 72 h : indispensable pour être indemnisé par l'assureur.
- Rapport final ANSSI : 1 mois.
Cliquez sur « Transmettre » dans le panneau de droite avant l'échéance. Un délai manqué entraîne sanctions et perte de confiance.
## Décisions urgentes
Certaines décisions ont un compte à rebours en temps réel : sans réponse, la situation décide pour vous (souvent mal). En Découverte, le bouton « Conseil ANSSI » donne le réflexe recommandé.
## Lever la cellule de crise
Une fois toutes les décisions prises, lisez le retour d'expérience puis levez la cellule : le temps avance d'une semaine, la reprise continue en arrière-plan."""),
    ("Analyse de risques (EBIOS RM)", """\
## Pourquoi
La méthode EBIOS Risk Manager de l'ANSSI vous aide à comprendre vos risques avant d'investir. Une analyse à jour est exigée par NIS2 (art. 21) et rassure la direction.
## Les 5 ateliers (dans l'ordre)
1. Cadrage et socle : glissez chaque bien support dans « primaire » (vital) ou « secondaire » ; repérez les écarts du socle d'hygiène ANSSI (42 mesures).
2. Sources de risque : cochez les couples attaquant / objectif pertinents pour votre secteur.
3. Scénarios stratégiques : associez un couple à un chemin d'attaque ; ajustez sa place dans la matrice par glisser-déposer.
4. Scénarios opérationnels : le jeu les décline en techniques d'attaque MITRE ATT&CK.
5. Traitement : pour chaque scénario, Accepter, Réduire, Transférer (assurance) ou Refuser ; sélectionnez des mesures et comparez la matrice avant / après.
## À savoir
Chaque atelier demande 1,5 jour-homme à votre équipe. Accepter un risque élevé sans le traiter sera relevé comme une erreur s'il se réalise."""),
    ("Budget et mesures", """\
## Le budget SSI
Il est annuel et réparti en 6 postes (outils, formation, audit, assurance, externalisation, divers). Les coûts des incidents et les sanctions ne sont pas pris sur ce budget, mais ils pèsent sur votre score.
## Les 40 mesures
Chaque mesure a un coût de déploiement, une maintenance annuelle (prélevée en début d'année) et un délai avant d'être opérationnelle. Elle réduit la probabilité et/ou l'impact de certaines attaques.
## Le simulateur de ROI
ROI = fréquence de l'incident × coût moyen × réduction ÷ coût annuel de la mesure. Au-dessus de 1, la mesure rapporte plus qu'elle ne coûte. Les mesures d'hygiène bon marché (correctifs, désactivation de SMBv1, double validation des virements) ont souvent un ROI très élevé.
## Conseils
Les sauvegardes hors ligne et la MFA sont des fondamentaux. Si une maintenance ne peut être payée en début d'année, la mesure est suspendue."""),
    ("Opérations SSI", """\
## L'équipe
Chaque membre apporte 4 jours-homme par semaine (moins pendant une crise). Les actions et les déploiements de mesures consomment cette capacité. En surcharge, les déploiements sont retardés ; après 6 semaines de surcharge, un membre peut partir. Solutions : renfort de consultant (8 semaines) ou recrutement demandé au comité de direction.
## Les vulnérabilités
Des failles réelles (CVE) sont publiées au fil du temps. Pour chacune :
- Corriger en urgence : rapide mais coûteux en temps, parfois avec interruption de service.
- Planifier : à la prochaine fenêtre de maintenance (toutes les 4 semaines).
- Contourner : réduit le risque à moindre coût, sans le supprimer.
- Accepter : aucun effort, mais l'attaquant peut l'exploiter.
Une faille critique, exposée sur Internet et activement exploitée doit être traitée en urgence. Sans scan de vulnérabilités, certaines failles restent invisibles.
## Vigilance et veille
Le taux de clic aux faux hameçonnages baisse avec la sensibilisation ; une campagne le mesure. La veille signale les campagnes d'attaque qui visent votre secteur."""),
    ("Conformité et contrôles", """\
## Obligations permanentes
Registre des traitements, DPO, formation RGPD, enregistrement NIS2, formation des dirigeants, analyse de risques, homologations… L'écran « Conformité » les liste avec le bouton pour s'en acquitter.
## Contrôles
La CNIL et l'ANSSI peuvent vous contrôler (parfois sans long préavis). Si vous êtes certifié ISO 27001, un audit de surveillance a lieu chaque année : il faut couvrir au moins 70 % des 93 contrôles de l'annexe A (via vos mesures et les travaux SMSI).
## Sanctions
Les montants sont des modèles pédagogiques bornés par les plafonds légaux (RGPD art. 83, NIS2 art. 34), pas un barème officiel."""),
    ("Direction et objectifs", """\
## La confiance de la direction
Elle monte quand vous gérez bien les crises, réussissez vos objectifs et présentez des bilans transparents. Elle baisse avec les crises mal gérées, les sanctions, les contrôles défavorables et les objectifs manqués. Trop basse, elle met fin à votre mandat.
## Le comité de direction (chaque trimestre)
- Demander une rallonge : plus de chances si l'analyse EBIOS est faite et si la confiance est bonne.
- Demander un recrutement : utile si l'équipe est surchargée.
- Proposer un exercice de crise : la direction sera mieux préparée (coûts des crises réduits).
- Présenter le bilan : renforce la confiance.
## Les objectifs de mandat
La direction vous fixe 3 objectifs (analyse de risques en 6 mois, zéro sanction, certification…). Ils comptent pour 15 % du score."""),
    ("Difficultés", """\
- Découverte : menace modérée, budget confortable, aides et visites guidées, comptes à rebours allongés.
- Standard : l'équilibre recommandé en formation, avec rappels des délais.
- Expert : attaquants plus actifs, budget serré, ni aide ni rappel, probabilités masquées.
- Crise majeure : menace extrême, jusqu'à 3 crises en parallèle, direction exigeante.
La taille de l'organisation est un autre réglage : la mairie est la plus accessible, l'opérateur télécom le plus exigeant."""),
    ("Score et fin de partie", """\
## Calcul du score (0 à 100)
- Réputation et confiance de la direction : 25 %
- Maîtrise du risque (amélioration + qualité EBIOS) : 20 %
- Conformité (notifications à temps + obligations) : 15 %
- Gestion de crise (qualité des décisions) : 15 %
- Impact financier (pertes et sanctions) : 10 %
- Objectifs de mandat : 15 %
Grille : 0-39 Insuffisant, 40-64 Moyen, 65-84 Bon, 85-100 Expert. En cas de fin anticipée, le score est plafonné à 30.
## Le rapport HTML
À la fin, générez le rapport : chronologie des incidents, journal des décisions, erreurs commentées avec la référence officielle (ANSSI, CNIL, textes de loi) et bonnes pratiques manquées."""),
    ("Sauvegarde et réseau local", """\
## Sauvegardes
La partie est sauvegardée automatiquement chaque semaine. « Sauvegarder » (en bas à droite du tableau de bord) permet aussi d'utiliser 3 emplacements. Au menu : « Reprendre » ou « Charger une partie ».
## Session en réseau local
Le formateur héberge une session et communique le code PIN et l'adresse IP ; les participants la rejoignent. Tous jouent la même organisation et se comparent en direct (onglet « Classement »). En mode synchronisé, la semaine suivante n'arrive que lorsque tous sont prêts. À utiliser sur un réseau de confiance."""),
    ("Raccourcis", """\
- Espace ou Entrée : passer à la semaine suivante (tableau de bord).
- Échap : revenir au tableau de bord / fermer.
- F1 : ouvrir ou fermer cette aide.
- Molette : faire défiler les listes.
- Glisser-déposer : ateliers EBIOS 1 et 3.
- Survol : la plupart des éléments affichent une infobulle explicative."""),
]


def _render_lines(text: str, width: int) -> list[tuple[str, str]]:
    """Découpe le texte d'aide en lignes typées (titre, puce, paragraphe)."""
    out: list[tuple[str, str]] = []
    for raw in text.split("\n"):
        if raw.startswith("## "):
            out.append(("h", raw[3:]))
            continue
        kind, body = ("b", raw[2:]) if raw.startswith("- ") else ("p", raw)
        size = "body"
        for i, line in enumerate(R.wrap_text(body, R.font(size), width - (22 if kind == "b" else 0))):
            out.append((kind if i == 0 else kind + "c", line))
        out.append(("gap", ""))
    return out


class HelpOverlay:
    def __init__(self) -> None:
        self.open = False
        self.section = 0

    def toggle(self, section: int | None = None) -> None:
        if section is not None:
            self.section = section
            self.open = True
        else:
            self.open = not self.open

    def draw(self, ui: UI) -> None:
        if not self.open:
            return
        surf = ui.surface
        sw, sh = surf.get_size()
        veil = pygame.Surface((sw, sh), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 190))
        surf.blit(veil, (0, 0))
        rect = pygame.Rect(0, 0, min(1180, sw - 40), sh - 60)
        rect.center = (sw // 2, sh // 2)
        R.panel(surf, rect, "panel", "accent", radius=10, width=2)
        R.draw_text(surf, "Aide — comment jouer", (rect.x + 24, rect.y + 16), "h2", "text", "bold")
        R.draw_text(surf, "F1 ou Échap pour fermer", (rect.right - 190, rect.y + 24), "small", "text_muted",
                    anchor="topright")
        if ui.button(pygame.Rect(rect.right - 170, rect.y + 14, 150, 36), "Fermer", "primary") \
                or ui.key(pygame.K_ESCAPE):
            self.open = False
            return
        nav = pygame.Rect(rect.x + 16, rect.y + 66, 270, rect.height - 82)
        y = nav.y
        bh = min(40, (nav.height - 4 * len(HELP_SECTIONS)) // len(HELP_SECTIONS))
        for i, (title, _) in enumerate(HELP_SECTIONS):
            if ui.button(pygame.Rect(nav.x, y, nav.width, bh), title, "selected" if i == self.section else "ghost",
                         size="small"):
                self.section = i
                ui.reset_scroll("help")
            y += bh + 4
        if ui.key(pygame.K_DOWN):
            self.section = (self.section + 1) % len(HELP_SECTIONS)
            ui.reset_scroll("help")
        if ui.key(pygame.K_UP):
            self.section = (self.section - 1) % len(HELP_SECTIONS)
            ui.reset_scroll("help")
        area = pygame.Rect(nav.right + 24, rect.y + 66, rect.right - nav.right - 48, rect.height - 82)
        title, text = HELP_SECTIONS[self.section]
        off = ui.begin_scroll("help", area)
        yy = area.y + off
        R.draw_text(surf, title, (area.x, yy), "h2", "accent", "bold")
        yy += 46
        line_h = R.font("body").get_height() + 4
        for kind, line in _render_lines(text, area.width - 16):
            if kind == "h":
                yy += 6
                R.draw_text(surf, line, (area.x, yy), "h3", "text", "bold")
                yy += 32
            elif kind == "gap":
                yy += 6
            else:
                indent = 22 if kind.startswith("b") else 0
                if kind == "b":
                    pygame.draw.circle(surf, config.THEME["accent"], (area.x + 8, yy + line_h // 2), 3)
                R.draw_text(surf, line, (area.x + indent, yy), "body", "text")
                yy += line_h
        ui.end_scroll("help", area, yy - (area.y + off) + 10)


# =============================================================================
# Visites guidées
# =============================================================================
@dataclass(frozen=True)
class TourStep:
    region: str | None   # zone mise en lumière (None : bulle centrée)
    title: str
    text: str


TOURS: dict[str, list[TourStep]] = {
    "DASHBOARD": [
        TourStep(None, "Bienvenue dans votre bureau de RSSI",
                 "Cette visite guidée vous montre comment jouer. Votre but : protéger l'organisation pendant votre "
                 "mandat, gérer les crises et respecter la réglementation, en gardant la confiance de tous.\n\n"
                 "Vous pourrez retrouver toutes les explications à tout moment avec le bouton « Aide » (ou F1)."),
        TourStep("hud", "Le bandeau permanent",
                 "La date, le budget SSI restant, la réputation globale, le niveau de risque et la semaine en cours. "
                 "Le bouton « Aide » est juste là, à gauche."),
        TourStep("indicators", "Vos indicateurs",
                 "Les 4 jauges de réputation (usagers, partenaires, régulateurs, presse) et la confiance de votre "
                 "direction. Sous 20/100 de réputation, ou si la direction perd confiance, la partie s'arrête."),
        TourStep("map", "La carte de votre SI",
                 "Chaque bâtiment est un bien support. Vert : sain. Jaune : faille critique exposée. Orange : en "
                 "reprise. Rouge clignotant : attaque en cours. « Matrice » affiche la matrice des risques."),
        TourStep("news", "Le fil d'actualité",
                 "Tout ce qui se passe arrive ici : vulnérabilités publiées, bulletins de veille, contrôles, "
                 "résultats de vos décisions. Lisez-le chaque semaine."),
        TourStep("objectives", "Vos objectifs de mandat",
                 "La direction vous a fixé 3 objectifs. Les atteindre augmente sa confiance et votre score final."),
        TourStep("actions", "Vos leviers d'action",
                 "Analyse de risques EBIOS RM (commencez par là), budget et achat de mesures, conformité "
                 "réglementaire et opérations SSI (vulnérabilités, équipe). Le bouton devient rouge s'il y a une "
                 "urgence."),
        TourStep("team", "La capacité de votre équipe",
                 "Chaque action et chaque déploiement consomme du temps de l'équipe (jours-homme). Si la barre "
                 "dépasse, les chantiers prennent du retard et l'équipe s'épuise."),
        TourStep("next", "Faire avancer le temps",
                 "Rien ne se passe tant que vous ne cliquez pas ici (ou Espace) : une semaine s'écoule. Si une "
                 "décision est en attente (événement, comité, crise), il faut d'abord la traiter."),
        TourStep(None, "Votre premier plan d'action",
                 "1. Ouvrez « Analyser les risques » et faites l'atelier 1.\n2. Dans « Gérer le budget », achetez une "
                 "ou deux mesures au meilleur ROI (sauvegardes, correctifs, MFA…).\n3. Passez les semaines en "
                 "surveillant le fil d'actualité.\n\nDes bulles d'aide apparaîtront la première fois que vous "
                 "ouvrirez chaque écran. Bon mandat !"),
    ],
    "EBIOS": [
        TourStep("tabs", "Les 5 ateliers EBIOS RM",
                 "La méthode de l'ANSSI se suit dans l'ordre : chaque atelier se débloque quand le précédent est "
                 "validé. Chacun demande 1,5 jour-homme à votre équipe."),
        TourStep("workspace", "L'espace de travail",
                 "Lisez la consigne au-dessus, puis agissez ici : glisser-déposer (ateliers 1 et 3), cases à cocher "
                 "(2), choix de traitements et de mesures (5). Validez avec le bouton en bas à droite."),
    ],
    "BUDGET": [
        TourStep("categories", "Votre budget annuel",
                 "Il est réparti en 6 postes. Les maintenances des mesures sont prélevées en début d'année."),
        TourStep("catalogue", "Le catalogue de 40 mesures",
                 "Filtrez par type et triez par ROI, coût ou délai. Cliquez sur une mesure pour l'étudier."),
        TourStep("simulator", "Le simulateur de ROI",
                 "Il chiffre les pertes évitées par rapport au coût de la mesure (ROI > 1 = rentable) et montre la "
                 "matrice de risque avant / après. « Commander » lance le déploiement."),
    ],
    "AUDIT": [
        TourStep("obligations", "Vos obligations permanentes",
                 "Chaque ligne rouge est une obligation non remplie : le bouton indique comment s'en acquitter."),
        TourStep("notifications", "Les notifications d'incident",
                 "Les déclarations en attente (CNIL, ANSSI…) se transmettent aussi d'ici, même après la crise."),
        TourStep("iso", "ISO 27001",
                 "Les 93 contrôles de la norme : vert = couvert. 70 % sont nécessaires pour passer l'audit."),
    ],
    "OPERATIONS": [
        TourStep("vulns", "Les vulnérabilités",
                 "Traitez d'abord les failles CRITIQUES, exposées sur Internet et exploitées activement : en urgence "
                 "ou par contournement. Les autres peuvent être planifiées."),
        TourStep("team", "Votre équipe",
                 "Surveillez la charge. En cas de surcharge durable, prenez un renfort ou demandez un recrutement "
                 "au prochain comité de direction."),
        TourStep("phishing", "La vigilance du personnel",
                 "Une campagne de faux hameçonnage mesure le taux de clic et entraîne le personnel."),
    ],
    "INCIDENT": [
        TourStep(None, "La salle de crise",
                 "Une attaque a été détectée. Restez calme : vous allez prendre 3 à 5 décisions, de l'isolement à "
                 "la reprise. Le temps de crise (H+…) n'avance qu'avec vos décisions."),
        TourStep("decision", "La décision en cours",
                 "Lisez la situation et choisissez. Si un compte à rebours s'affiche, il faut répondre avant la fin. "
                 "Le bouton « Conseil ANSSI » donne le réflexe recommandé."),
        TourStep("obligations", "Les délais réglementaires",
                 "Transmettez chaque notification avant son échéance (24 h, 72 h…). Un délai manqué entraîne une "
                 "sanction. C'est souvent la première chose à faire !"),
        TourStep("chat", "Les messages des équipes",
                 "Les équipes techniques, la direction et les prestataires vous informent ici de l'évolution."),
    ],
}


@dataclass
class CoachTour:
    key: str
    steps: list[TourStep]
    index: int = 0
    done: bool = False
    t: float = 0.0
    on_finish: Callable[[], None] | None = None
    disable_option: bool = False
    disable_requested: bool = field(default=False)

    def draw(self, ui: UI, regions: dict[str, pygame.Rect], dt: float) -> None:
        if self.done:
            return
        self.t += dt
        surf = ui.surface
        sw, sh = surf.get_size()
        step = self.steps[self.index]
        target = regions.get(step.region) if step.region else None
        veil = pygame.Surface((sw, sh), pygame.SRCALPHA)
        veil.fill((4, 6, 10, 185))
        if target is not None:
            hole = target.inflate(14, 14).clip(surf.get_rect())
            pygame.draw.rect(veil, (0, 0, 0, 0), hole, border_radius=10)
        surf.blit(veil, (0, 0))
        if target is not None:
            pulse = 0.5 + 0.5 * math.sin(self.t * 4)
            col = R.blend(config.THEME["accent"], (255, 255, 255), pulse * 0.6)
            pygame.draw.rect(surf, col, target.inflate(14, 14), 3, border_radius=10)

        width = min(520, sw - 40)
        body_h = R.measure_wrapped(step.text, width - 40, "body")
        height = body_h + 150
        bubble = pygame.Rect(0, 0, width, height)
        if target is None:
            bubble.center = (sw // 2, sh // 2)
        else:
            t = target.inflate(14, 14)
            if t.right + 24 + width <= sw - 10:
                bubble.topleft = (t.right + 24, t.centery - height // 2)
            elif t.left - 24 - width >= 10:
                bubble.topright = (t.left - 24, t.centery - height // 2)
            elif t.bottom + 20 + height <= sh - 10:
                bubble.midtop = (t.centerx, t.bottom + 20)
            else:
                bubble.midbottom = (t.centerx, t.top - 20)
            bubble.clamp_ip(surf.get_rect().inflate(-20, -20))
            # flèche vers la zone
            start = (bubble.centerx, bubble.centery)
            end = (min(max(start[0], t.left), t.right), min(max(start[1], t.top), t.bottom))
            pygame.draw.line(surf, config.THEME["accent"], start, end, 3)
            pygame.draw.circle(surf, config.THEME["accent"], end, 6)
        R.panel(surf, bubble, "panel", "accent", radius=12, width=2)
        R.draw_text(surf, f"{self.index + 1} / {len(self.steps)}", (bubble.right - 20, bubble.y + 18), "small",
                    "text_muted", anchor="topright")
        R.draw_text_fit(surf, step.title, (bubble.x + 20, bubble.y + 14), width - 110, "h3", "accent", "bold")
        R.draw_wrapped(surf, step.text, pygame.Rect(bubble.x + 20, bubble.y + 50, width - 40, body_h + 4), "body")
        by = bubble.bottom - 54
        last = self.index == len(self.steps) - 1
        if ui.button(pygame.Rect(bubble.right - 160, by, 140, 40), "Terminer" if last else "Suivant  ▶", "primary") \
                or ui.key(pygame.K_RETURN, pygame.K_RIGHT, pygame.K_SPACE):
            if last:
                self._finish()
            else:
                self.index += 1
            return
        if self.index > 0 and (ui.button(pygame.Rect(bubble.right - 310, by, 140, 40), "◀  Précédent", "ghost")
                               or ui.key(pygame.K_LEFT)):
            self.index -= 1
            return
        if ui.button(pygame.Rect(bubble.x + 20, by, 120, 40), "Passer", "ghost") or ui.key(pygame.K_ESCAPE):
            self._finish()
            return
        if self.disable_option and last:
            if ui.checkbox(pygame.Rect(bubble.x + 20, by - 40, width - 40, 30), self.disable_requested,
                           "Ne plus afficher les visites guidées"):
                self.disable_requested = not self.disable_requested

    def _finish(self) -> None:
        self.done = True
        if self.on_finish:
            self.on_finish()
