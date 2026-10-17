"""Tests du multijoueur LAN (net/) : loopback uniquement, ports éphémères."""
from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from net import protocol
from net.client import SessionClient
from net.discovery import PROBE, DiscoveryResponder, build_reply, discover, parse_reply
from net.protocol import (
    MAX_MESSAGE_BYTES,
    PlayerProgress,
    SessionInfo,
    clean_name,
    decode,
    encode,
    is_lan_address,
    validate,
)
from net.server import SessionHost

PIN = "4242"


def wait_for(pred: Callable[[], Any], timeout: float = 3.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = pred()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("condition non atteinte dans le délai")


class Collector:
    """Accumule les événements poll() d'un hôte ou d'un client."""

    def __init__(self, source: Any) -> None:
        self.source = source
        self.events: list[dict] = []

    def of(self, kind: str) -> list[dict]:
        self.events.extend(self.source.poll())
        return [e for e in self.events if e["type"] == kind]


@pytest.fixture
def make_host() -> Iterator[Callable[..., SessionHost]]:
    hosts: list[SessionHost] = []

    def factory(mode: str = "libre") -> SessionHost:
        h = SessionHost("Formateur", "hopital", "normal", 2, mode, seed=1234, pin=PIN,
                        port=0, bind="127.0.0.1", discovery=False)
        h.start()
        hosts.append(h)
        return h

    yield factory
    for h in hosts:
        h.close()


@pytest.fixture
def make_client() -> Iterator[Callable[..., SessionClient]]:
    clients: list[SessionClient] = []

    def factory(host: SessionHost, name: str, pin: str = PIN, connect: bool = True) -> SessionClient:
        c = SessionClient("127.0.0.1", host.port, name, pin, timeout=2.0)
        clients.append(c)
        if connect:
            c.connect()
        return c

    yield factory
    for c in clients:
        c.close()


def raw_hello(host: SessionHost, name: str = "Brut") -> tuple[socket.socket, bytes]:
    s = socket.create_connection(("127.0.0.1", host.port), timeout=2.0)
    s.sendall(encode({"type": "hello", "version": 1, "name": name, "pin": PIN}))
    data = b""
    while b"\n" not in data:
        data += s.recv(4096)
    return s, data


# ---------------------------------------------------------------------------
# Protocole
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ip", ["10.1.2.3", "192.168.1.10", "172.16.0.5", "127.0.0.1",
                                "fe80::1", "fe80::1%eth0", "169.254.3.4", "::1", "::ffff:192.168.0.1"])
def test_is_lan_address_true(ip: str) -> None:
    assert is_lan_address(ip)


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888", "172.32.0.1",
                                "", "pas-une-ip", "0.0.0.0", "224.0.0.1"])
def test_is_lan_address_false(ip: str) -> None:
    assert not is_lan_address(ip)


def test_encode_decode_roundtrip_and_limits() -> None:
    msg = {"type": "ready", "turn": 3}
    data = encode(msg)
    assert data.endswith(b"\n")
    assert decode(data.rstrip(b"\n")) == msg
    with pytest.raises(ValueError):
        encode({"type": "reject", "reason": "x" * MAX_MESSAGE_BYTES})
    assert decode(b"{pas du json") is None
    assert decode(b"[1, 2]") is None
    assert decode(b'{"type":"progress","score":NaN}') is None
    assert decode(b"\xff\xfe") is None
    assert decode(b"[" * 10000) is None


def test_clean_name() -> None:
    assert clean_name("  Alice \n\t Dupont ") == "Alice Dupont"
    assert clean_name("A" * 50) == "A" * 20
    assert clean_name("Bob‮\x00x") == "Bob x"
    for bad in ("", "   ", "\x00\x01", None):
        with pytest.raises(ValueError):
            clean_name(bad)  # type: ignore[arg-type]


def test_validate_rejects_out_of_bounds() -> None:
    ok = {"type": "progress", "turn": 3, "score": 12.5, "reputation": 60, "incidents": 2,
          "finished": False, "extra": "ignoré"}
    v = validate(ok)
    assert v is not None and "extra" not in v and v["reputation"] == 60.0
    for field, value in [("turn", -1), ("turn", 10**9), ("turn", 2.5), ("turn", True),
                         ("score", float("inf")), ("score", 1e12), ("score", "12"),
                         ("incidents", -3), ("finished", 1)]:
        assert validate({**ok, field: value}) is None, (field, value)
    assert validate({"type": "inconnu"}) is None
    assert validate({"turn": 1}) is None
    assert validate({"type": "hello", "version": 1, "name": "", "pin": "1234"}) is None
    assert validate({"type": "hello", "version": 1, "name": "Al", "pin": "12;4"}) is None
    assert validate({"type": "start", "org_id": "../etc", "difficulty": "normal", "seed": 1,
                     "years": 2, "mode": "libre"}) is None
    assert validate({"type": "start", "org_id": "hopital", "difficulty": "normal", "seed": 1,
                     "years": 2, "mode": "anarchie"}) is None
    assert validate({"type": "players", "players": [{"player_id": 1}]}) is None
    p = PlayerProgress(1, "Al").to_dict()
    assert validate({"type": "players", "players": [p]}) == {"type": "players", "players": [p]}


# ---------------------------------------------------------------------------
# Découverte (sans dépendre du broadcast)
# ---------------------------------------------------------------------------
def _info() -> SessionInfo:
    return SessionInfo("Formateur", "", 47111, "hopital", "normal", 2, "libre", 3, 16, False)


def test_discovery_reply_and_parse() -> None:
    reply = build_reply(PROBE, "192.168.1.20", _info())
    assert reply is not None
    info = parse_reply(reply, "192.168.1.5")
    assert info is not None and info.host == "192.168.1.5" and info.org_id == "hopital"
    assert build_reply(PROBE, "8.8.8.8", _info()) is None
    assert build_reply(b"autre chose", "192.168.1.20", _info()) is None
    assert parse_reply(reply, "8.8.8.8") is None
    assert parse_reply(b'{"app":"RSSI-SIMULATOR","version":1,"session":{}}', "10.0.0.1") is None


def test_discovery_loopback_tolerant() -> None:
    responder = DiscoveryResponder(_info, port=0)
    responder.start()
    try:
        if responder.port == 0:
            pytest.skip("socket UDP indisponible")
        sessions = discover(timeout=0.5, port=responder.port)
        if not sessions:
            pytest.skip("envoi UDP/broadcast indisponible dans cet environnement")
        assert any(s.org_id == "hopital" and s.port == 47111 for s in sessions)
    finally:
        responder.close()


# ---------------------------------------------------------------------------
# Session hôte / clients
# ---------------------------------------------------------------------------
def test_host_and_two_clients_leaderboard(make_host: Callable[..., SessionHost],
                                          make_client: Callable[..., SessionClient]) -> None:
    host = make_host()
    assert len(host.pin) == 4
    a = make_client(host, "Alice")
    b = make_client(host, "Bob")
    assert a.connected and b.connected and a.player_id != b.player_id
    assert a.session is not None and a.session.org_id == "hopital" and a.session.host == "127.0.0.1"
    wait_for(lambda: len(host.players()) == 3)
    assert host.players()[0].player_id == 0

    a.send_progress(2, 150.0, 70.0, 1, False)
    host.update_host_progress(1, 90.0, 55.0, 0, False)
    cb = Collector(b)

    def bob_sees_alice() -> bool:
        lists = cb.of("players")
        if not lists:
            return False
        players = {p["name"]: p for p in lists[-1]["players"]}
        return players.get("Alice", {}).get("score") == 150.0 and players["Formateur"]["turn"] == 1

    wait_for(bob_sees_alice)
    ch = Collector(host)
    assert [e["name"] for e in ch.of("joined")] == ["Alice", "Bob"]
    b.close()
    wait_for(lambda: ch.of("left"))
    wait_for(lambda: len(host.players()) == 2)  # avant lancement : retiré de la liste


def test_duplicate_names_are_disambiguated(make_host: Callable[..., SessionHost],
                                           make_client: Callable[..., SessionClient]) -> None:
    host = make_host()
    make_client(host, "Alice")
    make_client(host, "Alice")
    wait_for(lambda: sorted(p.name for p in host.players()) == ["Alice", "Alice (2)", "Formateur"])


def test_wrong_pin_rejected(make_host: Callable[..., SessionHost],
                            make_client: Callable[..., SessionClient]) -> None:
    host = make_host()
    c = make_client(host, "Eve", pin="0000", connect=False)
    with pytest.raises(ConnectionError, match="PIN"):
        c.connect()
    assert not c.connected
    assert len(host.players()) == 1


def test_pin_bruteforce_bans_address(make_host: Callable[..., SessionHost],
                                     make_client: Callable[..., SessionClient],
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from net import server
    monkeypatch.setattr(server, "PIN_FAILURE_DELAY", 0.0)
    host = make_host()
    for i in range(server.MAX_PIN_FAILURES_PER_IP):
        c = make_client(host, f"Eve{i}", pin=f"{i:04d}", connect=False)
        with pytest.raises(ConnectionError, match="PIN"):
            c.connect()
    # même avec le bon code, l'adresse est désormais bannie pour la session
    c = make_client(host, "Eve", pin=PIN, connect=False)
    with pytest.raises(ConnectionError):
        c.connect()
    assert len(host.players()) == 1


def test_pin_bruteforce_locks_session(make_host: Callable[..., SessionHost],
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from net import server
    monkeypatch.setattr(server, "PIN_FAILURE_DELAY", 0.0)
    monkeypatch.setattr(server, "MAX_PIN_FAILURES_PER_IP", 1000)
    monkeypatch.setattr(server, "MAX_PIN_FAILURES_TOTAL", 3)
    host = make_host()
    events = Collector(host)
    for i in range(3):
        c = SessionClient("127.0.0.1", host.port, f"Eve{i}", f"{i:04d}", timeout=2.0)
        with pytest.raises(ConnectionError, match="PIN"):
            c.connect()
    wait_for(lambda: events.of("locked"))
    c = SessionClient("127.0.0.1", host.port, "Alice", PIN, timeout=2.0)
    with pytest.raises(ConnectionError):
        c.connect()


def test_wrong_version_rejected(make_host: Callable[..., SessionHost]) -> None:
    host = make_host()
    s = socket.create_connection(("127.0.0.1", host.port), timeout=2.0)
    s.sendall(encode({"type": "hello", "version": 99, "name": "Old", "pin": PIN}))
    data = s.recv(4096)
    s.close()
    msg = validate(decode(data.strip()) or {})
    assert msg is not None and msg["type"] == "reject" and "Version" in msg["reason"]


def test_oversized_message_disconnects(make_host: Callable[..., SessionHost]) -> None:
    host = make_host()
    s, data = raw_hello(host)
    assert b"welcome" in data
    wait_for(lambda: len(host.players()) == 2)
    try:
        s.sendall(b"x" * (MAX_MESSAGE_BYTES + 100))
    except OSError:
        pass

    def closed() -> bool:
        try:
            return s.recv(65536) == b""
        except ConnectionResetError:
            return True
        except TimeoutError:
            return False

    wait_for(closed)
    s.close()
    wait_for(lambda: len(host.players()) == 1)


def test_rate_limit_disconnects(make_host: Callable[..., SessionHost]) -> None:
    host = make_host()
    s, _ = raw_hello(host)
    wait_for(lambda: len(host.players()) == 2)
    try:
        s.sendall(encode({"type": "ping"}) * 200)
    except OSError:
        pass
    wait_for(lambda: len(host.players()) == 1)
    s.close()


def test_invalid_messages_ignored(make_host: Callable[..., SessionHost]) -> None:
    host = make_host()
    s, _ = raw_hello(host, "Brut")
    s.sendall(b"pas du json\n")
    s.sendall(b'{"type":"progress","turn":-5,"score":1,"reputation":1,"incidents":0,"finished":false}\n')
    s.sendall(b'{"type":"inconnu","x":1}\n')
    s.sendall(b"[1,2,3]\n")
    s.sendall(encode({"type": "progress", "turn": 4, "score": 33.0, "reputation": 50.0,
                      "incidents": 1, "finished": False}))
    wait_for(lambda: any(p.name == "Brut" and p.turn == 4 for p in host.players()))
    s.close()


def test_launch_sends_start_and_refuses_new_players(make_host: Callable[..., SessionHost],
                                                    make_client: Callable[..., SessionClient]) -> None:
    host = make_host()
    a = make_client(host, "Alice")
    wait_for(lambda: len(host.players()) == 2)
    host.launch()
    assert host.started and host.info().started
    ca = Collector(a)
    start = wait_for(lambda: ca.of("start"))[0]
    assert start["seed"] == 1234 and start["org_id"] == "hopital" and start["years"] == 2
    late = make_client(host, "Retard", connect=False)
    with pytest.raises(ConnectionError, match="lancée"):
        late.connect()


def test_sync_mode_advance_only_when_all_ready(make_host: Callable[..., SessionHost],
                                              make_client: Callable[..., SessionClient]) -> None:
    host = make_host("synchronise")
    a = make_client(host, "Alice")
    b = make_client(host, "Bob")
    wait_for(lambda: len(host.players()) == 3)
    host.launch()
    ch, ca = Collector(host), Collector(a)

    host.host_ready(1)
    a.set_ready(1)
    wait_for(lambda: any(p.name == "Alice" and p.ready_turn == 1 for p in host.players()))
    time.sleep(0.1)
    assert not ch.of("advance") and not ca.of("advance")

    b.set_ready(1)
    assert wait_for(lambda: ca.of("advance"))[0]["turn"] == 1
    assert wait_for(lambda: ch.of("advance"))[0]["turn"] == 1

    # Bob se déconnecte : il ne doit pas bloquer la semaine 2
    host.host_ready(2)
    a.set_ready(2)
    time.sleep(0.1)
    assert len(ch.of("advance")) == 1
    b.close()
    wait_for(lambda: len(ch.of("advance")) == 2)
    assert ch.of("advance")[-1]["turn"] == 2
    wait_for(lambda: any(e["turn"] == 2 for e in ca.of("advance")))
    bob = next(p for p in host.players() if p.name == "Bob")
    assert not bob.connected  # après lancement : conservé au classement


def test_free_mode_never_advances(make_host: Callable[..., SessionHost],
                                  make_client: Callable[..., SessionClient]) -> None:
    host = make_host("libre")
    a = make_client(host, "Alice")
    host.launch()
    host.host_ready(1)
    a.set_ready(1)
    wait_for(lambda: any(p.ready_turn == 1 for p in host.players() if p.player_id != 0))
    assert not Collector(host).of("advance")


def test_host_close_notifies_client(make_host: Callable[..., SessionHost],
                                    make_client: Callable[..., SessionClient]) -> None:
    host = make_host()
    a = make_client(host, "Alice")
    host.close()
    ca = Collector(a)
    assert wait_for(lambda: ca.of("disconnected"))
    assert not a.connected


def test_client_refuses_non_lan_host() -> None:
    c = SessionClient("8.8.8.8", 47111, "Alice", PIN)
    with pytest.raises(ConnectionError, match="réseau local"):
        c.connect()


def test_host_pin_generated() -> None:
    h = SessionHost("Formateur", "hopital", "normal", 1, "libre", seed=1, port=0,
                    bind="127.0.0.1", discovery=False)
    assert len(h.pin) == 4 and h.pin.isdigit()
    with pytest.raises(ValueError):
        SessionHost("F", "hopital", "normal", 1, "libre", seed=1, pin="12ab", discovery=False)


def test_net_has_no_unsafe_deserialisation() -> None:
    import ast
    from pathlib import Path

    for path in (Path(protocol.__file__).parent).glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
                assert not any(n.split(".")[0] in ("pickle", "marshal", "shelve") for n in names), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec"), path
    assert json.loads(encode({"type": "bye"})) == {"type": "bye"}
