"""Construction des invites pour la narration locale (llama.cpp).

Garde-fous intégrés à l'invite système : français, ton professionnel, aucune
invention de CVE, de chiffre ou de référence, aucun nom de personne réelle.
Seul l'état fictif de la partie est transmis au modèle (exécution 100 % locale).
"""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = (
    "Tu es le narrateur d'un simulateur de crise cyber destiné à la formation professionnelle "
    "en France. Tu écris en français, sur un ton sobre et professionnel, au format d'un message "
    "court (2 à 3 phrases) envoyé par un membre de l'équipe nommé uniquement par sa fonction. "
    "Règles strictes : n'invente aucune vulnérabilité (CVE), aucun chiffre, aucune référence "
    "réglementaire ; ne cite aucun nom de personne ou d'entreprise réelle ; ne donne aucune "
    "instruction offensive. Si une information manque, reste général."
)


def team_message_prompt(context: dict[str, Any]) -> str:
    """Message d'ambiance d'un membre de la cellule de crise."""
    return (
        f"Organisation : {context.get('organisation', 'organisation')} ({context.get('secteur', '')}).\n"
        f"Incident : {context.get('incident', '')}.\n"
        f"Phase : {context.get('phase', '')}. Heure de crise : H+{context.get('heure', 0)}.\n"
        f"Émetteur : {context.get('emetteur', 'Équipe technique')}.\n"
        f"Dernière décision du RSSI : {context.get('derniere_decision', 'aucune')}.\n"
        "Rédige le message que cet émetteur envoie à la cellule de crise."
    )


def rex_summary_prompt(context: dict[str, Any]) -> str:
    """Synthèse de retour d'expérience à chaud."""
    decisions = "\n".join(f"- {d}" for d in context.get("decisions", []))
    return (
        f"Incident : {context.get('incident', '')} dans {context.get('organisation', '')}.\n"
        f"Décisions prises :\n{decisions}\n"
        "Rédige en 3 phrases une synthèse de retour d'expérience : ce qui a fonctionné, "
        "ce qui doit être amélioré, la priorité pour les 3 prochains mois."
    )


def chat_format(user_prompt: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}]
