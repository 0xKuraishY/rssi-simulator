"""Découverte des sessions sur le réseau local (UDP broadcast).

Le client diffuse la sonde « RSSI-SIMULATOR? » ; chaque hôte répond par un
petit objet JSON décrivant sa session. Les datagrammes dont l'adresse
source n'est pas locale (privée, loopback, link-local) sont ignorés.

Licence : GNU GPL v3.
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Callable

from net.protocol import (
    DISCOVERY_PORT,
    PROTOCOL_VERSION,
    SessionInfo,
    decode,
    is_lan_address,
    session_from_dict,
    validate_session,
)

log = logging.getLogger(__name__)

PROBE = b"RSSI-SIMULATOR?"
APP_TAG = "RSSI-SIMULATOR"
MAX_DATAGRAM = 2048
MAX_REPLIES_PER_S = 20


def build_reply(data: bytes, sender_ip: str, info: SessionInfo) -> bytes | None:
    """Réponse à envoyer pour une sonde reçue, ou None si à ignorer."""
    if not is_lan_address(sender_ip) or data.strip() != PROBE:
        return None
    payload = {"app": APP_TAG, "version": PROTOCOL_VERSION, "session": info.to_dict()}
    out = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return out if len(out) <= MAX_DATAGRAM else None


def parse_reply(data: bytes, sender_ip: str) -> SessionInfo | None:
    """Interprète une réponse d'hôte ; l'adresse retenue est l'IP source réelle."""
    if not is_lan_address(sender_ip) or len(data) > MAX_DATAGRAM:
        return None
    obj = decode(data)
    if obj is None or obj.get("app") != APP_TAG or obj.get("version") != PROTOCOL_VERSION:
        return None
    session = validate_session(obj.get("session"))
    if session is None or session["port"] == 0:
        return None
    return session_from_dict(session, sender_ip)


def discover(timeout: float = 1.5, port: int = DISCOVERY_PORT) -> list[SessionInfo]:
    """Diffuse une sonde et collecte les sessions qui répondent (liste vide si échec)."""
    found: dict[tuple[str, int], SessionInfo] = {}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        log.warning("Découverte impossible : socket UDP indisponible")
        return []
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sent = False
        for target in ("255.255.255.255", "127.0.0.1"):
            try:
                sock.sendto(PROBE, (target, port))
                sent = True
            except OSError:
                pass
        if not sent:
            return []
        deadline = time.monotonic() + max(0.0, timeout)
        while (remaining := deadline - time.monotonic()) > 0:
            sock.settimeout(remaining)
            try:
                data, addr = sock.recvfrom(MAX_DATAGRAM + 1)
            except TimeoutError:
                break
            except OSError:
                break
            info = parse_reply(data, addr[0])
            if info is not None:
                found[(info.host, info.port)] = info
    finally:
        sock.close()
    return list(found.values())


class DiscoveryResponder:
    """Répond aux sondes de découverte (côté hôte), dans un thread daemon."""

    def __init__(self, info_provider: Callable[[], SessionInfo], port: int = DISCOVERY_PORT) -> None:
        self._info_provider = info_provider
        self.port = port
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Démarre l'écoute ; en cas d'échec (port occupé…), la découverte est désactivée."""
        if self._thread is not None:
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.port))
            sock.settimeout(0.2)
        except OSError as exc:
            log.warning("Découverte LAN désactivée : %s", exc)
            return
        self._sock = sock
        self.port = sock.getsockname()[1]
        self._thread = threading.Thread(target=self._run, name="rssi-simulator-discovery", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        sock = self._sock
        assert sock is not None
        window, count = time.monotonic(), 0
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(MAX_DATAGRAM)
            except TimeoutError:
                continue
            except OSError:
                break
            now = time.monotonic()
            if now - window >= 1.0:
                window, count = now, 0
            if count >= MAX_REPLIES_PER_S:
                continue
            try:
                reply = build_reply(data, addr[0], self._info_provider())
                if reply is not None:
                    count += 1
                    sock.sendto(reply, addr)
            except Exception:  # noqa: BLE001 - ne jamais faire planter le jeu
                log.debug("Réponse de découverte impossible", exc_info=True)

    def close(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._sock = None
