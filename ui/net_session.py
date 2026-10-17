"""Session multijoueur en réseau local vue par le jeu (hôte ou participant).

Encapsule ``net.SessionHost`` / ``net.SessionClient`` : les opérations bloquantes
(découverte, connexion) s'exécutent dans des threads, le fil d'affichage ne fait
que consommer des événements via ``poll()``.
"""
from __future__ import annotations

import logging
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

from net.client import SessionClient
from net.discovery import discover
from net.protocol import DEFAULT_PORT, PlayerProgress, SessionInfo
from net.server import SessionHost

log = logging.getLogger(__name__)


@dataclass
class StartParams:
    org_id: str
    difficulty: str
    seed: int
    years: int
    mode: str


@dataclass
class NetSession:
    role: str                                  # "host" | "client"
    name: str
    host: SessionHost | None = None
    client: SessionClient | None = None
    players: list[PlayerProgress] = field(default_factory=list)
    start: StartParams | None = None
    mode: str = "libre"
    advance_turn: int = 0                      # dernière semaine validée par tous (mode synchronisé)
    waiting_for: int | None = None             # semaine pour laquelle on attend les autres
    disconnected: str | None = None
    events: list[str] = field(default_factory=list)

    # -- création --------------------------------------------------------------
    @classmethod
    def create_host(cls, name: str, org_id: str, difficulty: str, years: int, mode: str,
                    port: int = DEFAULT_PORT) -> "NetSession":
        seed = secrets.randbelow(2**31 - 1) + 1
        host = SessionHost(name, org_id, difficulty, years, mode, seed, port=port)
        host.start()
        s = cls("host", name, host=host, mode=mode)
        s.players = host.players()
        return s

    @classmethod
    def join(cls, ip: str, port: int, name: str, pin: str) -> "NetSession":
        client = SessionClient(ip, port, name, pin)
        client.connect()
        s = cls("client", name, client=client)
        if client.session is not None:
            s.mode = client.session.mode
        return s

    # -- infos --------------------------------------------------------------------
    @property
    def is_host(self) -> bool:
        return self.role == "host"

    @property
    def synchronized(self) -> bool:
        return self.mode == "synchronise"

    @property
    def pin(self) -> str:
        return self.host.pin if self.host else ""

    @property
    def port(self) -> int:
        return self.host.port if self.host else 0

    def session_info(self) -> SessionInfo | None:
        if self.host:
            return self.host.info()
        return self.client.session if self.client else None

    def my_id(self) -> int:
        return 0 if self.is_host else (self.client.player_id if self.client else -1)

    def leaderboard(self) -> list[PlayerProgress]:
        return sorted(self.players, key=lambda p: (-p.score, -p.turn, p.name))

    # -- cycle ----------------------------------------------------------------------
    def poll(self) -> list[dict[str, Any]]:
        if self.host:
            events = self.host.poll()
            self.players = self.host.players()
        elif self.client:
            events = self.client.poll()
        else:
            events = []
        for ev in events:
            t = ev.get("type")
            if t == "players":
                raw = ev.get("players", [])
                self.players = [p if isinstance(p, PlayerProgress) else PlayerProgress(**p) for p in raw]
            elif t == "start":
                self.start = StartParams(ev["org_id"], ev["difficulty"], int(ev["seed"]), int(ev["years"]),
                                         ev["mode"])
                self.mode = ev["mode"]
            elif t == "advance":
                self.advance_turn = max(self.advance_turn, int(ev["turn"]))
            elif t == "disconnected":
                self.disconnected = str(ev.get("reason", "Connexion perdue"))
            elif t in ("joined", "left"):
                self.events.append(f"{ev.get('name', '?')} {'a rejoint' if t == 'joined' else 'a quitté'} la session")
            elif t == "locked":
                self.events.append("Trop de codes PIN erronés : la session refuse désormais toute nouvelle connexion")
        return events

    def launch(self) -> StartParams:
        assert self.host is not None
        self.host.launch()
        self.start = StartParams(self.host.org_id, self.host.difficulty, self.host.seed, self.host.years,
                                 self.host.mode)
        return self.start

    def send_progress(self, turn: int, score: float, reputation: float, incidents: int, finished: bool) -> None:
        try:
            if self.host:
                self.host.update_host_progress(turn, score, reputation, incidents, finished)
            elif self.client and self.client.connected:
                self.client.send_progress(turn, score, reputation, incidents, finished)
        except Exception:  # le réseau ne doit jamais interrompre la partie
            log.exception("Envoi de la progression impossible")

    def ready(self, turn: int) -> None:
        self.waiting_for = turn
        try:
            if self.host:
                self.host.host_ready(turn)
            elif self.client and self.client.connected:
                self.client.set_ready(turn)
        except Exception:
            log.exception("Signal « prêt » impossible")

    def may_advance(self, turn: int) -> bool:
        """En mode synchronisé : tous les joueurs ont-ils validé la semaine ``turn`` ?"""
        if not self.synchronized or self.disconnected:
            return True
        return self.advance_turn >= turn

    def close(self) -> None:
        try:
            if self.host:
                self.host.close()
            if self.client:
                self.client.close()
        except Exception:
            log.exception("Fermeture de la session")


class Background:
    """Exécute une fonction bloquante dans un thread ; résultat ou erreur consultables à chaque image."""

    def __init__(self, func, *args: Any) -> None:  # type: ignore[no-untyped-def]
        self.result: Any = None
        self.error: str | None = None
        self.done = False

        def run() -> None:
            try:
                self.result = func(*args)
            except Exception as exc:  # message affiché au joueur
                self.error = str(exc) or exc.__class__.__name__
            finally:
                self.done = True
        threading.Thread(target=run, daemon=True).start()


def discover_sessions(timeout: float = 1.5) -> Background:
    return Background(discover, timeout)


def join_async(ip: str, port: int, name: str, pin: str) -> Background:
    return Background(NetSession.join, ip, port, name, pin)
