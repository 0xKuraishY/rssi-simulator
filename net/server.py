"""Hôte d'une session multijoueur LAN (le formateur).

L'hôte accepte les apprenants (PIN de session, 16 joueurs maximum),
centralise leur progression, diffuse le classement et, en mode
« synchronise », l'autorisation de passer à la semaine suivante. Tout
reste en mémoire ; rien n'est persisté.

Licence : GNU GPL v3.
"""
from __future__ import annotations

import hmac
import logging
import queue
import secrets
import socket
import threading
import time
from typing import Any

from net.discovery import DiscoveryResponder
from net.protocol import (
    DEFAULT_PORT,
    DISCOVERY_PORT,
    MAX_PLAYERS,
    MAX_SEED,
    MAX_TURN,
    MAX_YEARS,
    MODES,
    PIN_LEN,
    PROTOCOL_VERSION,
    MessageStream,
    PlayerProgress,
    ProtocolError,
    SessionInfo,
    _ident,
    _int,
    _num,
    clean_name,
    is_lan_address,
    validate,
)

log = logging.getLogger(__name__)

HANDSHAKE_TIMEOUT = 5.0
MAX_PENDING_CONNECTIONS = 32
MAX_CONNECTIONS_PER_IP = 4       # hors loopback (tests, plusieurs instances sur le même poste)
MAX_PIN_FAILURES_PER_IP = 3      # au-delà, l'adresse est bannie jusqu'à la fin de la session
MAX_PIN_FAILURES_TOTAL = 30      # au-delà, la session n'accepte plus aucune nouvelle connexion
PIN_FAILURE_DELAY = 1.0          # ralentit la force brute (10 000 combinaisons possibles)
PEER_RATE_LIMIT = 20             # messages/s par apprenant : borne l'amplification des diffusions
HOST_ID = 0


class _Client:
    def __init__(self, stream: MessageStream, ip: str) -> None:
        self.stream = stream
        self.ip = ip
        self.player_id: int | None = None


class SessionHost:
    """Session hébergée : serveur TCP + répondeur de découverte UDP."""

    def __init__(self, host_name: str, org_id: str, difficulty: str, years: int, mode: str, seed: int,
                 pin: str | None = None, port: int = DEFAULT_PORT, bind: str = "0.0.0.0",
                 discovery: bool = True) -> None:
        if mode not in MODES:
            raise ValueError(f"Mode inconnu : {mode}")
        self.org_id = _ident(org_id)
        self.difficulty = _ident(difficulty)
        self.years = _int(years, 1, MAX_YEARS)
        self.mode = mode
        self.seed = _int(seed, 0, MAX_SEED)
        if pin is None:
            pin = "".join(secrets.choice("0123456789") for _ in range(PIN_LEN))
        if not (isinstance(pin, str) and len(pin) == PIN_LEN and pin.isascii() and pin.isdigit()):
            raise ValueError("Le code PIN doit comporter 4 chiffres")
        self.pin: str = pin
        self.port: int = port
        self.bind = bind
        self.name = clean_name(host_name)
        self._discovery_enabled = discovery
        self._discovery: DiscoveryResponder | None = None

        self._lock = threading.RLock()
        self._broadcast_lock = threading.Lock()
        self._stop = threading.Event()
        self._events: queue.Queue[dict] = queue.Queue()
        self._players: dict[int, PlayerProgress] = {HOST_ID: PlayerProgress(HOST_ID, self.name)}
        self._clients: dict[int, _Client] = {}
        self._next_id = 1
        self._pending = 0
        self._per_ip: dict[str, int] = {}
        self._pin_failures: dict[str, int] = {}
        self._pin_failures_total = 0
        self._started = False
        self._advanced_turn = 0
        self._listener: socket.socket | None = None
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------------ cycle de vie
    def start(self) -> None:
        """Ouvre l'écoute TCP. Lève OSError si le port est indisponible."""
        if self._listener is not None:
            return
        if not is_lan_address(self.bind) and self.bind not in ("0.0.0.0", ""):
            raise ValueError("Adresse d'écoute hors réseau local")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.bind, self.port))
            sock.listen(MAX_PLAYERS)
            sock.settimeout(0.2)
        except OSError:
            sock.close()
            raise
        self._listener = sock
        self.port = sock.getsockname()[1]
        t = threading.Thread(target=self._accept_loop, name="rssi-simulator-host", daemon=True)
        t.start()
        self._threads.append(t)
        if self._discovery_enabled:
            self._discovery = DiscoveryResponder(self.info, DISCOVERY_PORT)
            self._discovery.start()

    def close(self) -> None:
        """Arrête la session : prévient les clients et libère les sockets."""
        if self._stop.is_set():
            return
        self._stop.set()
        if self._discovery is not None:
            self._discovery.close()
        if self._listener is not None:
            try:
                self._listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._listener.close()
            except OSError:
                pass
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for c in clients:
            try:
                c.stream.send({"type": "bye"}, timeout=0.5)
            except (ProtocolError, ValueError):
                pass
            c.stream.close()
        for t in list(self._threads):
            if t is not threading.current_thread():
                t.join(timeout=1.0)

    # ------------------------------------------------------------------ consultation
    @property
    def started(self) -> bool:
        return self._started

    def info(self) -> SessionInfo:
        with self._lock:
            connected = sum(1 for p in self._players.values() if p.connected)
            return SessionInfo(name=self.name, host="", port=self.port, org_id=self.org_id,
                               difficulty=self.difficulty, years=self.years, mode=self.mode,
                               players=connected, max_players=MAX_PLAYERS, started=self._started)

    def players(self) -> list[PlayerProgress]:
        with self._lock:
            return [PlayerProgress(**p.to_dict()) for p in self._players.values()]

    def poll(self) -> list[dict]:
        out: list[dict] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    # ------------------------------------------------------------------ actions de l'hôte
    def launch(self) -> None:
        """Lance la partie : diffuse « start » ; plus aucune nouvelle connexion."""
        with self._lock:
            if self._started:
                return
            self._started = True
        self._broadcast({"type": "start", "org_id": self.org_id, "difficulty": self.difficulty,
                         "seed": self.seed, "years": self.years, "mode": self.mode})

    def update_host_progress(self, turn: int, score: float, reputation: float, incidents: int,
                             finished: bool) -> None:
        msg = validate({"type": "progress", "turn": turn, "score": score, "reputation": reputation,
                        "incidents": incidents, "finished": bool(finished)})
        if msg is None:
            log.warning("Progression de l'hôte hors bornes, ignorée")
            return
        with self._lock:
            self._apply_progress(self._players[HOST_ID], msg)
        self._players_changed()

    def host_ready(self, turn: int) -> None:
        try:
            turn = _int(turn, 0, MAX_TURN)
        except ValueError:
            return
        with self._lock:
            p = self._players[HOST_ID]
            p.ready_turn = max(p.ready_turn, turn)
        self._players_changed()
        self._check_advance()

    # ------------------------------------------------------------------ interne
    @staticmethod
    def _apply_progress(p: PlayerProgress, msg: dict[str, Any]) -> None:
        p.turn = msg["turn"]
        p.score = _num(msg["score"])
        p.reputation = _num(msg["reputation"])
        p.incidents = msg["incidents"]
        p.finished = msg["finished"]

    def _players_payload(self) -> dict:
        with self._lock:
            return {"type": "players", "players": [p.to_dict() for p in self._players.values()]}

    def _players_changed(self) -> None:
        msg = self._players_payload()
        self._events.put(msg)
        self._broadcast(msg)

    def _broadcast(self, msg: dict) -> None:
        with self._broadcast_lock:
            with self._lock:
                targets = list(self._clients.values())
            for c in targets:
                try:
                    c.stream.send(msg)
                except (ProtocolError, ValueError):
                    c.stream.close()  # le thread du client constatera la déconnexion

    def _check_advance(self) -> None:
        if self.mode != "synchronise":
            return
        to_send: list[int] = []
        with self._lock:
            if not self._started:
                return
            ready = [p.ready_turn for p in self._players.values() if p.connected]
            if not ready:
                return
            target = min(ready)
            while self._advanced_turn < target:
                self._advanced_turn += 1
                to_send.append(self._advanced_turn)
        for n in to_send:
            msg = {"type": "advance", "turn": n}
            self._events.put(dict(msg))
            self._broadcast(msg)

    def _accept_loop(self) -> None:
        listener = self._listener
        assert listener is not None
        while not self._stop.is_set():
            try:
                sock, addr = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            ip = addr[0]
            if not is_lan_address(ip):
                log.warning("Connexion refusée (hors réseau local) : %s", ip)
                sock.close()
                continue
            with self._lock:
                refused = (self._pending >= MAX_PENDING_CONNECTIONS
                           or self._pin_failures.get(ip, 0) >= MAX_PIN_FAILURES_PER_IP
                           or self._pin_failures_total >= MAX_PIN_FAILURES_TOTAL
                           or (not ip.startswith("127.") and self._per_ip.get(ip, 0) >= MAX_CONNECTIONS_PER_IP))
                if not refused:
                    self._pending += 1
                    self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
            if refused:
                sock.close()
                continue
            t = threading.Thread(target=self._serve, args=(sock, ip), name="rssi-simulator-peer", daemon=True)
            t.start()
            self._threads = [x for x in self._threads if x.is_alive()] + [t]

    def _serve(self, sock: socket.socket, ip: str) -> None:
        client: _Client | None = None
        try:
            stream = MessageStream(sock, rate_limit=PEER_RATE_LIMIT)
            client = _Client(stream, ip)
            try:
                self._handshake(client)
                self._loop(client)
            except ProtocolError:
                pass
        except Exception:  # noqa: BLE001 - un pair défaillant ne doit jamais faire planter l'hôte
            log.exception("Erreur inattendue avec le pair %s", ip)
        finally:
            with self._lock:
                self._pending = max(0, self._pending - 1)
                left = self._per_ip.get(ip, 0) - 1
                if left > 0:
                    self._per_ip[ip] = left
                else:
                    self._per_ip.pop(ip, None)
            if client is not None:
                self._disconnect(client)
            else:
                try:
                    sock.close()
                except OSError:
                    pass

    def _reject(self, client: _Client, reason: str) -> None:
        try:
            client.stream.send({"type": "reject", "reason": reason}, timeout=1.0)
        except (ProtocolError, ValueError):
            pass
        raise ProtocolError(reason)

    def _handshake(self, client: _Client) -> None:
        deadline = time.monotonic() + HANDSHAKE_TIMEOUT
        while True:
            msg = client.stream.recv(self._stop, deadline)
            if msg["type"] == "hello":
                break
        if msg["version"] != PROTOCOL_VERSION:
            self._reject(client, "Version de protocole incompatible")
        if not hmac.compare_digest(msg["pin"].encode("ascii"), self.pin.encode("ascii")):
            with self._lock:
                self._pin_failures[client.ip] = self._pin_failures.get(client.ip, 0) + 1
                self._pin_failures_total += 1
                locked = self._pin_failures_total == MAX_PIN_FAILURES_TOTAL
            log.warning("Code PIN incorrect depuis %s", client.ip)
            if locked:
                self._events.put({"type": "locked"})
            self._stop.wait(PIN_FAILURE_DELAY)
            self._reject(client, "Code PIN incorrect")
        with self._lock:
            if self._started:
                reason = "La partie est déjà lancée"
            elif sum(1 for p in self._players.values() if p.connected) >= MAX_PLAYERS:
                reason = "La session est complète"
            else:
                reason = ""
                pid = self._next_id
                self._next_id += 1
                name = self._unique_name(msg["name"])
                self._players[pid] = PlayerProgress(pid, name)
                client.player_id = pid
                self._clients[pid] = client
        if reason:
            self._reject(client, reason)
        session = self.info().to_dict()
        client.stream.send({"type": "welcome", "player_id": pid, "session": session})
        self._events.put({"type": "joined", "name": name})
        self._players_changed()

    def _unique_name(self, name: str) -> str:
        taken = {p.name for p in self._players.values()}
        if name not in taken:
            return name
        for i in range(2, 100):
            suffix = f" ({i})"
            cand = name[: 20 - len(suffix)] + suffix
            if cand not in taken:
                return cand
        return name

    def _loop(self, client: _Client) -> None:
        while True:
            msg = client.stream.recv(self._stop)
            t = msg["type"]
            if t == "bye":
                return
            pid = client.player_id
            if t == "progress":
                with self._lock:
                    p = self._players.get(pid) if pid is not None else None
                    if p is not None:
                        self._apply_progress(p, msg)
                self._players_changed()
            elif t == "ready":
                with self._lock:
                    p = self._players.get(pid) if pid is not None else None
                    if p is not None:
                        p.ready_turn = max(p.ready_turn, msg["turn"])
                self._players_changed()
                self._check_advance()
            # ping et autres types valides mais sans objet côté hôte : ignorés

    def _disconnect(self, client: _Client) -> None:
        client.stream.close()
        pid = client.player_id
        if pid is None:
            return
        with self._lock:
            if self._clients.get(pid) is client:
                del self._clients[pid]
            p = self._players.get(pid)
            if p is None:
                return
            name = p.name
            if self._started:
                p.connected = False
            else:
                del self._players[pid]
        if self._stop.is_set():
            return
        self._events.put({"type": "left", "name": name})
        self._players_changed()
        self._check_advance()
