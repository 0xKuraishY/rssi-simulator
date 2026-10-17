"""Multijoueur en réseau local (LAN) de RSSI Simulator.

Chaque joueur fait tourner sa propre simulation de la même organisation
(même graine, même difficulté, même durée) ; seule la progression est
échangée pour un classement en direct.

Garanties : réseau local uniquement (adresses privées, loopback ou
link-local), protocole JSON ligne par ligne strictement validé, aucune
donnée persistée, pseudonyme comme seul identifiant.

Licence : GNU GPL v3.
"""
from __future__ import annotations

from net.client import SessionClient
from net.discovery import DiscoveryResponder, discover
from net.protocol import (
    DEFAULT_PORT,
    DISCOVERY_PORT,
    MAX_MESSAGE_BYTES,
    MAX_PLAYERS,
    MODES,
    PROTOCOL_VERSION,
    PlayerProgress,
    SessionInfo,
    is_lan_address,
)
from net.server import SessionHost

__all__ = [
    "DEFAULT_PORT",
    "DISCOVERY_PORT",
    "MAX_MESSAGE_BYTES",
    "MAX_PLAYERS",
    "MODES",
    "PROTOCOL_VERSION",
    "DiscoveryResponder",
    "PlayerProgress",
    "SessionClient",
    "SessionHost",
    "SessionInfo",
    "discover",
    "is_lan_address",
]
