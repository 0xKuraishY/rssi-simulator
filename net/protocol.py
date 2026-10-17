"""Protocole réseau du multijoueur LAN : encodage, validation, structures.

Format : JSON UTF-8, un objet par ligne terminée par « \\n », 16 Ko maximum
par message. Aucun pickle ni eval : seuls des objets JSON simples, validés
champ par champ (types, bornes, longueur des chaînes), sont acceptés.

Licence : GNU GPL v3.
"""
from __future__ import annotations

import ipaddress
import json
import math
import re
import socket
import threading
import time
import unicodedata
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

PROTOCOL_VERSION = 1
DISCOVERY_PORT = 47110  # UDP
DEFAULT_PORT = 47111  # TCP
MAX_MESSAGE_BYTES = 16384
MAX_PLAYERS = 16
MODES = ("libre", "synchronise")
NAME_MAX_LEN = 20
PIN_LEN = 4
RATE_LIMIT_PER_S = 50

MAX_TURN = 10_000
MAX_ABS_VALUE = 1e9
MAX_INCIDENTS = 1_000_000
MAX_YEARS = 20
MAX_SEED = 2**63 - 1
MAX_PLAYER_ID = 1_000_000
MAX_REASON_LEN = 200
MAX_PLAYERS_LIST = 64

_IDENT_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_PIN_RE = re.compile(r"^[0-9]{1,16}$")


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------
@dataclass
class SessionInfo:
    """Description publique d'une session (découverte et accueil)."""

    name: str
    host: str
    port: int
    org_id: str
    difficulty: str
    years: int
    mode: str
    players: int
    max_players: int
    started: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlayerProgress:
    """Progression d'un joueur, telle qu'affichée dans le classement."""

    player_id: int
    name: str
    turn: int = 0
    score: float = 0.0
    reputation: float = 0.0
    incidents: int = 0
    finished: bool = False
    ready_turn: int = 0
    connected: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Réseau local uniquement
# ---------------------------------------------------------------------------
def is_lan_address(ip: str) -> bool:
    """Vrai si l'adresse est privée, loopback ou link-local (jamais Internet)."""
    if not isinstance(ip, str) or not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if addr.is_unspecified or addr.is_multicast:
        return False
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local)


# ---------------------------------------------------------------------------
# Encodage / décodage
# ---------------------------------------------------------------------------
def encode(msg: dict) -> bytes:
    """Sérialise un message en JSON UTF-8 terminé par « \\n »."""
    data = (json.dumps(msg, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("Message trop volumineux")
    return data


def _reject_constant(value: str) -> Any:
    raise ValueError(f"Constante JSON interdite : {value}")


def decode(line: bytes) -> dict | None:
    """Décode une ligne JSON ; None si invalide, trop grosse ou non-objet."""
    if not isinstance(line, (bytes, bytearray)) or len(line) > MAX_MESSAGE_BYTES:
        return None
    try:
        obj = json.loads(bytes(line).decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return None
    return obj if isinstance(obj, dict) else None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def clean_name(name: str) -> str:
    """Nettoie un pseudonyme (caractères imprimables, 1 à 20 caractères)."""
    if not isinstance(name, str):
        raise ValueError("Pseudonyme invalide")
    text = unicodedata.normalize("NFC", name[:200])
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    text = " ".join(text.split())[:NAME_MAX_LEN].strip()
    if not text:
        raise ValueError("Pseudonyme vide")
    return text


def _int(v: Any, lo: int, hi: int) -> int:
    if type(v) is not int or not lo <= v <= hi:
        raise ValueError
    return v


def _num(v: Any) -> float:
    if type(v) not in (int, float) or not math.isfinite(v) or abs(v) > MAX_ABS_VALUE:
        raise ValueError
    return float(v)


def _bool(v: Any) -> bool:
    if type(v) is not bool:
        raise ValueError
    return v


def _ident(v: Any) -> str:
    if not isinstance(v, str) or not _IDENT_RE.match(v):
        raise ValueError
    return v


def _mode(v: Any) -> str:
    if v not in MODES:
        raise ValueError
    return str(v)


def _reason(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError
    text = "".join(ch for ch in v[:MAX_REASON_LEN] if ch.isprintable())
    return text or "Refus"


def _player(d: Any) -> dict[str, Any]:
    if not isinstance(d, dict):
        raise ValueError
    return {
        "player_id": _int(d.get("player_id"), 0, MAX_PLAYER_ID),
        "name": clean_name(d.get("name")),  # type: ignore[arg-type]
        "turn": _int(d.get("turn"), 0, MAX_TURN),
        "score": _num(d.get("score")),
        "reputation": _num(d.get("reputation")),
        "incidents": _int(d.get("incidents"), 0, MAX_INCIDENTS),
        "finished": _bool(d.get("finished")),
        "ready_turn": _int(d.get("ready_turn"), 0, MAX_TURN),
        "connected": _bool(d.get("connected")),
    }


def validate_session(d: Any) -> dict[str, Any] | None:
    """Valide la description d'une session ; None si invalide."""
    if not isinstance(d, dict):
        return None
    try:
        host = d.get("host", "")
        if not isinstance(host, str) or len(host) > 64:
            raise ValueError
        return {
            "name": clean_name(d.get("name")),  # type: ignore[arg-type]
            "host": host,
            "port": _int(d.get("port"), 0, 65535),
            "org_id": _ident(d.get("org_id")),
            "difficulty": _ident(d.get("difficulty")),
            "years": _int(d.get("years"), 1, MAX_YEARS),
            "mode": _mode(d.get("mode")),
            "players": _int(d.get("players"), 0, MAX_PLAYERS),
            "max_players": _int(d.get("max_players"), 1, MAX_PLAYERS),
            "started": _bool(d.get("started")),
        }
    except ValueError:
        return None


def session_from_dict(d: dict[str, Any], host: str) -> SessionInfo:
    """Construit un SessionInfo validé ; l'hôte est imposé (IP réelle)."""
    data = dict(d)
    data["host"] = host
    return SessionInfo(**data)


def _validate_fields(t: str, m: dict[str, Any]) -> dict[str, Any]:
    if t == "hello":
        pin = m.get("pin")
        if not isinstance(pin, str) or not _PIN_RE.match(pin):
            raise ValueError
        return {"version": _int(m.get("version"), 0, 1_000_000),
                "name": clean_name(m.get("name")),  # type: ignore[arg-type]
                "pin": pin}
    if t == "welcome":
        session = validate_session(m.get("session"))
        if session is None:
            raise ValueError
        return {"player_id": _int(m.get("player_id"), 0, MAX_PLAYER_ID), "session": session}
    if t == "reject":
        return {"reason": _reason(m.get("reason"))}
    if t == "players":
        lst = m.get("players")
        if not isinstance(lst, list) or len(lst) > MAX_PLAYERS_LIST:
            raise ValueError
        return {"players": [_player(p) for p in lst]}
    if t == "start":
        return {"org_id": _ident(m.get("org_id")),
                "difficulty": _ident(m.get("difficulty")),
                "seed": _int(m.get("seed"), 0, MAX_SEED),
                "years": _int(m.get("years"), 1, MAX_YEARS),
                "mode": _mode(m.get("mode"))}
    if t == "progress":
        return {"turn": _int(m.get("turn"), 0, MAX_TURN),
                "score": _num(m.get("score")),
                "reputation": _num(m.get("reputation")),
                "incidents": _int(m.get("incidents"), 0, MAX_INCIDENTS),
                "finished": _bool(m.get("finished"))}
    if t in ("ready", "advance"):
        return {"turn": _int(m.get("turn"), 0, MAX_TURN)}
    if t in ("bye", "ping"):
        return {}
    raise ValueError


def validate(msg: dict) -> dict | None:
    """Renvoie le message normalisé (champs connus uniquement) ou None."""
    if not isinstance(msg, dict):
        return None
    t = msg.get("type")
    if not isinstance(t, str):
        return None
    try:
        fields = _validate_fields(t, msg)
    except (ValueError, TypeError):
        return None
    return {"type": t, **fields}


# ---------------------------------------------------------------------------
# Flux de messages sur une socket TCP
# ---------------------------------------------------------------------------
class ProtocolError(ConnectionError):
    """Violation du protocole ou fin de connexion."""


class RateLimiter:
    """Limite simple : au plus `limit` messages par fenêtre d'une seconde."""

    def __init__(self, limit: int = RATE_LIMIT_PER_S) -> None:
        self.limit = limit
        self._start = time.monotonic()
        self._count = 0

    def hit(self) -> bool:
        now = time.monotonic()
        if now - self._start >= 1.0:
            self._start, self._count = now, 0
        self._count += 1
        return self._count <= self.limit


class MessageStream:
    """Lecture/écriture de messages validés sur une socket (thread-safe en écriture)."""

    POLL_INTERVAL = 0.2

    def __init__(self, sock: socket.socket, rate_limit: int = RATE_LIMIT_PER_S) -> None:
        self.sock = sock
        self._buf = bytearray()
        self._pending: deque[bytes] = deque()
        self._limiter = RateLimiter(rate_limit)
        self._send_lock = threading.Lock()
        sock.settimeout(self.POLL_INTERVAL)

    def _fill(self) -> bool:
        """Lit des octets ; False sur délai dépassé. Lève ProtocolError sinon."""
        try:
            data = self.sock.recv(4096)
        except TimeoutError:
            return False
        except OSError as exc:
            raise ProtocolError("Connexion interrompue") from exc
        if not data:
            raise ProtocolError("Connexion fermée")
        self._buf.extend(data)
        while True:
            idx = self._buf.find(b"\n")
            if idx < 0:
                break
            line = bytes(self._buf[:idx])
            del self._buf[: idx + 1]
            if len(line) + 1 > MAX_MESSAGE_BYTES:
                raise ProtocolError("Message trop volumineux")
            self._pending.append(line)
        if len(self._buf) > MAX_MESSAGE_BYTES:
            raise ProtocolError("Message trop volumineux")
        return True

    def recv(self, stop: threading.Event, deadline: float | None = None) -> dict:
        """Renvoie le prochain message valide (les invalides sont ignorés)."""
        while True:
            while self._pending:
                line = self._pending.popleft()
                if not self._limiter.hit():
                    raise ProtocolError("Débit de messages excessif")
                if not line.strip():
                    continue
                raw = decode(line)
                msg = validate(raw) if raw is not None else None
                if msg is not None:
                    return msg
            if stop.is_set():
                raise ProtocolError("Arrêt demandé")
            if deadline is not None and time.monotonic() > deadline:
                raise ProtocolError("Délai dépassé")
            self._fill()

    def send(self, msg: dict, timeout: float = 2.0) -> None:
        data = encode(msg)
        with self._send_lock:
            try:
                self.sock.settimeout(timeout)
                self.sock.sendall(data)
            except OSError as exc:
                raise ProtocolError("Envoi impossible") from exc
            finally:
                try:
                    self.sock.settimeout(self.POLL_INTERVAL)
                except OSError:
                    pass

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def local_lan_ips() -> list[str]:
    """Adresses IPv4 locales (réseau privé) de cette machine, pour les afficher aux participants.

    Le « connect » UDP ne transmet aucun paquet : il sert seulement à connaître
    l'interface que le système utiliserait pour joindre un réseau privé.
    """
    import socket

    ips: set[str] = set()
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 9))
            ip = s.getsockname()[0]
            if is_lan_address(ip) and not ip.startswith("127."):
                ips.add(ip)
        except OSError:
            pass
        finally:
            s.close()
    return sorted(ips) or ["127.0.0.1"]
