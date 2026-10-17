"""Niveaux de difficulté, indépendants de l'organisation choisie.

L'organisation fixe le contexte (taille, budget, réglementation) ; la difficulté
règle l'intensité de la menace, la sévérité des conséquences et les aides affichées.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Difficulty:
    id: str
    nom: str
    description: str
    incident_mult: float        # probabilité des incidents
    cost_mult: float            # coût des incidents
    fine_mult: float            # montant des sanctions
    budget_mult: float          # budget SSI initial
    reputation_recovery: float  # points de réputation regagnés par semaine
    timer_mult: float           # durée des comptes à rebours en temps réel
    grace_turns: int            # semaines sans compromission au début
    max_open_incidents: int
    vuln_rate: float            # fréquence des nouvelles vulnérabilités
    capacity_mult: float        # capacité de l'équipe SSI
    board_leniency: float       # bienveillance du comité de direction (0-1)
    trust_loss_mult: float      # sensibilité de la confiance de la direction
    dismissal_threshold: float  # confiance en dessous de laquelle le RSSI est remercié
    show_probabilities: bool    # probabilités chiffrées dans les infobulles
    show_hints: bool            # conseil « réflexe ANSSI » disponible en salle de crise
    deadline_reminders: bool    # rappels des délais réglementaires
    level: int                  # 1 (facile) → 4 (très difficile)


DIFFICULTIES: dict[str, Difficulty] = {d.id: d for d in (
    Difficulty(
        "decouverte", "Découverte",
        "Pour découvrir le métier : menace modérée, budget confortable, aides et rappels affichés, "
        "comptes à rebours allongés.",
        incident_mult=0.65, cost_mult=0.75, fine_mult=0.5, budget_mult=1.25, reputation_recovery=0.40,
        timer_mult=2.0, grace_turns=6, max_open_incidents=1, vuln_rate=0.6, capacity_mult=1.3,
        board_leniency=0.80, trust_loss_mult=0.6, dismissal_threshold=5.0, show_probabilities=True, show_hints=True,
        deadline_reminders=True, level=1,
    ),
    Difficulty(
        "standard", "Standard",
        "L'équilibre recommandé en formation : menace réaliste, rappels des délais réglementaires, "
        "sans indice sur les bonnes décisions.",
        incident_mult=1.0, cost_mult=1.0, fine_mult=1.0, budget_mult=1.0, reputation_recovery=0.25,
        timer_mult=1.0, grace_turns=3, max_open_incidents=2, vuln_rate=1.0, capacity_mult=1.0,
        board_leniency=0.60, trust_loss_mult=1.0, dismissal_threshold=12.0, show_probabilities=True, show_hints=False,
        deadline_reminders=True, level=2,
    ),
    Difficulty(
        "expert", "Expert",
        "Pour les RSSI confirmés : attaquants plus actifs, budget serré, aucune aide ni rappel, "
        "probabilités masquées.",
        incident_mult=1.35, cost_mult=1.2, fine_mult=1.0, budget_mult=0.9, reputation_recovery=0.15,
        timer_mult=0.75, grace_turns=2, max_open_incidents=2, vuln_rate=1.3, capacity_mult=0.9,
        board_leniency=0.45, trust_loss_mult=1.2, dismissal_threshold=15.0, show_probabilities=False, show_hints=False,
        deadline_reminders=False, level=3,
    ),
    Difficulty(
        "crise", "Crise majeure",
        "Contexte de menace extrême : campagnes simultanées, jusqu'à 3 crises en parallèle, direction "
        "exigeante. Réservé aux équipes entraînées.",
        incident_mult=1.8, cost_mult=1.4, fine_mult=1.2, budget_mult=0.8, reputation_recovery=0.10,
        timer_mult=0.5, grace_turns=1, max_open_incidents=3, vuln_rate=1.6, capacity_mult=0.8,
        board_leniency=0.35, trust_loss_mult=1.4, dismissal_threshold=20.0, show_probabilities=False, show_hints=False,
        deadline_reminders=False, level=4,
    ),
)}

DEFAULT_DIFFICULTY = "standard"
DURATIONS = {1: "1 an (session courte)", 2: "2 ans", 3: "3 ans (mandat complet)"}


def get_difficulty(difficulty_id: str | None) -> Difficulty:
    return DIFFICULTIES.get(difficulty_id or DEFAULT_DIFFICULTY, DIFFICULTIES[DEFAULT_DIFFICULTY])
