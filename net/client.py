"""Client d'une session multijoueur LAN (l'apprenant).

API non bloquante pour le fil d'affichage : les messages reçus sont
empilés dans une file que le jeu relève via poll().

Licence : GNU GPL v3.
"""
from __future__ import annotations

import logging
import queue
import socket
import threading
import time

from net.protocol import (
    MAX_TURN,
    PROTOCOL_VERSION,
    MessageStream,
    ProtocolError,
    SessionInfo,
    clean_name,
    is_lan_address,
    session_from_dict,
    validate,
)

log = logging.getLogger(__name__)

CLIENT_RATE_LIMIT = 1000  # l'hôte diffuse le classement à chaque changement (16 joueurs × 20 msg/s au pire)


class SessionClient:
    """Connexion d'un apprenant à la session d'un hôte du réseau local."""

    def __init__(self, host: str, port: int, name: str, pin: str, timeout: float = 3.0) -> None:
        self.host = "127.0.0.1" if host == "localhost" else host
        self.port = port
        self.name = clean_name(name)
        self.pin = pin
        self.timeout = timeout
        self.player_id: int = -1
        self.session: SessionInfo | None = None
        self._stream: MessageStream | None = None
        self._events: queue.Queue[dict] = queue.Queue()
        self._stop = threading.Event()
        self._connected = False
        self._thread: threading.Thread | None = None
        self._down_lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        """Se connecte et s'identifie ; lève ConnectionError avec un motif lisible."""
        if not is_lan_address(self.host):
            raise ConnectionError("Adresse hors réseau local : connexion refusée")
        if not (isinstance(self.port, int) and 0 < self.port < 65536):
            raise ConnectionError("Port invalide")
        if not (isinstance(self.pin, str) and len(self.pin) == 4 and self.pin.isascii()
                and self.pin.isdigit()):
            raise ConnectionError("Code PIN incorrect (4 chiffres attendus)")
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise ConnectionError("Impossible de joindre l'hôte de la session") from exc
        try:
            peer = sock.getpeername()[0]
        except OSError:
            peer = ""
        if not is_lan_address(peer):
            sock.close()
            raise ConnectionError("Hôte hors réseau local : connexion refusée")
        stream = MessageStream(sock, rate_limit=CLIENT_RATE_LIMIT)
        try:
            stream.send({"type": "hello", "version": PROTOCOL_VERSION, "name": self.name,
                         "pin": self.pin}, timeout=self.timeout)
            deadline = time.monotonic() + self.timeout
            while True:
                msg = stream.recv(self._stop, deadline)
                if msg["type"] == "reject":
                    raise ConnectionError(msg["reason"])
                if msg["type"] == "welcome":
                    break
        except ConnectionError as exc:
            stream.close()
            if isinstance(exc, ProtocolError):
                raise ConnectionError("Pas de réponse valide de l'hôte (" + str(exc) + ")") from exc
            raise
        except ValueError as exc:  # PIN ou pseudonyme non encodable
            stream.close()
            raise ConnectionError("Identification invalide") from exc
        self.player_id = msg["player_id"]
        self.session = session_from_dict(msg["session"], self.host)
        self._stream = stream
        self._connected = True
        self._thread = threading.Thread(target=self._reader, name="rssi-simulator-client", daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        stream = self._stream
        assert stream is not None
        reason = "Connexion avec l'hôte perdue"
        try:
            while True:
                msg = stream.recv(self._stop)
                t = msg["type"]
                if t == "bye":
                    reason = "Session terminée par l'hôte"
                    break
                if t in ("start", "players", "advance"):
                    self._events.put(msg)
        except ProtocolError as exc:
            if str(exc) in ("Message trop volumineux", "Débit de messages excessif"):
                reason = f"Déconnecté : {exc.args[0].lower()}"
        except Exception:  # noqa: BLE001 - ne jamais faire planter le jeu
            log.exception("Erreur inattendue dans le client réseau")
        self._go_down(reason)

    def _go_down(self, reason: str) -> None:
        with self._down_lock:
            if not self._connected:
                return
            self._connected = False
        if self._stream is not None:
            self._stream.close()
        if not self._stop.is_set():
            self._events.put({"type": "disconnected", "reason": reason})

    def _send(self, msg: dict) -> None:
        if not self._connected or self._stream is None:
            return
        try:
            self._stream.send(msg, timeout=self.timeout)
        except (ProtocolError, ValueError):
            self._go_down("Connexion avec l'hôte perdue")

    def send_progress(self, turn: int, score: float, reputation: float, incidents: int,
                      finished: bool) -> None:
        msg = validate({"type": "progress", "turn": turn, "score": score, "reputation": reputation,
                        "incidents": incidents, "finished": bool(finished)})
        if msg is None:
            log.warning("Progression hors bornes, non transmise")
            return
        self._send(msg)

    def set_ready(self, turn: int) -> None:
        if type(turn) is int and 0 <= turn <= MAX_TURN:
            self._send({"type": "ready", "turn": turn})

    def poll(self) -> list[dict]:
        out: list[dict] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    def close(self) -> None:
        if self._connected and self._stream is not None:
            try:
                self._stream.send({"type": "bye"}, timeout=0.5)
            except (ProtocolError, ValueError):
                pass
        self._stop.set()
        self._go_down("Déconnexion")
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
