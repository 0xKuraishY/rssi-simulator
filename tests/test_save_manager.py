"""Sauvegarde SQLite : écriture, lecture, corruption, versions, méta."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from engine.save_manager import (
    SCHEMA_VERSION,
    SaveCorruptedError,
    SaveManager,
    SaveNotFoundError,
    SaveVersionError,
)
from game.simulation import Simulation
from tests.conftest import resolve_blockers


@pytest.fixture
def manager(tmp_path: Path) -> SaveManager:
    m = SaveManager(tmp_path / "saves" / "saves.sqlite3")
    yield m
    m.close()


def test_save_and_load_roundtrip(manager: SaveManager) -> None:
    state = {"org_id": "mairie", "turn": 12, "données": {"liste": [1, 2, 3]}}
    info = manager.save(state, "slot1", "Mairie — semaine 12")
    assert info.turn == 12 and info.org_id == "mairie"
    assert manager.load("slot1") == state
    assert manager.exists("slot1")


def test_overwrite_same_slot(manager: SaveManager) -> None:
    manager.save({"org_id": "a", "turn": 1})
    manager.save({"org_id": "a", "turn": 2})
    assert manager.load()["turn"] == 2
    assert len(manager.list_saves()) == 1


def test_missing_slot(manager: SaveManager) -> None:
    with pytest.raises(SaveNotFoundError):
        manager.load("absent")
    assert manager.latest() is None
    assert manager.delete("absent") is False


def test_delete_and_latest(manager: SaveManager) -> None:
    manager.save({"org_id": "a", "turn": 1}, "s1")
    manager.save({"org_id": "b", "turn": 2}, "s2")
    assert manager.latest().slot == "s2"
    assert manager.delete("s2") is True
    assert [s.slot for s in manager.list_saves()] == ["s1"]


def _tamper(db: Path, sql: str, params: tuple = ()) -> None:
    con = sqlite3.connect(db)
    con.execute(sql, params)
    con.commit()
    con.close()


def test_detects_tampered_payload(manager: SaveManager) -> None:
    manager.save({"org_id": "a", "turn": 5, "budget": 1000})
    _tamper(manager.db_path, "UPDATE saves SET payload = ?", (json.dumps({"org_id": "a", "turn": 5, "budget": 10**9}),))
    with pytest.raises(SaveCorruptedError):
        manager.load()


def test_detects_invalid_json_with_valid_checksum(manager: SaveManager) -> None:
    import hashlib
    manager.save({"org_id": "a", "turn": 1})
    bad = "{pas du json"
    _tamper(manager.db_path, "UPDATE saves SET payload = ?, checksum = ?", (bad, hashlib.sha256(bad.encode()).hexdigest()))
    with pytest.raises(SaveCorruptedError):
        manager.load()


def test_detects_non_dict_payload(manager: SaveManager) -> None:
    import hashlib
    manager.save({"org_id": "a", "turn": 1})
    bad = "[1, 2]"
    _tamper(manager.db_path, "UPDATE saves SET payload = ?, checksum = ?", (bad, hashlib.sha256(bad.encode()).hexdigest()))
    with pytest.raises(SaveCorruptedError):
        manager.load()


def test_version_mismatch(manager: SaveManager) -> None:
    manager.save({"org_id": "a", "turn": 1})
    _tamper(manager.db_path, "UPDATE saves SET schema_version = ?", (SCHEMA_VERSION + 1,))
    with pytest.raises(SaveVersionError):
        manager.load()


def test_corrupted_database_file(tmp_path: Path) -> None:
    db = tmp_path / "broken.sqlite3"
    db.write_bytes(b"ceci n'est pas une base SQLite" * 100)
    with pytest.raises(SaveCorruptedError):
        SaveManager(db)


def test_meta_values(manager: SaveManager) -> None:
    assert manager.get_meta("settings", {"x": 1}) == {"x": 1}
    manager.set_meta("settings", {"volume": 0.5, "tutorial_done": True})
    assert manager.get_meta("settings")["tutorial_done"] is True
    _tamper(manager.db_path, "UPDATE meta SET value = 'corrompu' WHERE key = 'settings'")
    assert manager.get_meta("settings", "défaut") == "défaut"


def test_no_personal_data_columns(manager: SaveManager) -> None:
    con = sqlite3.connect(manager.db_path)
    cols = {row[1] for table in ("saves", "meta") for row in con.execute(f"PRAGMA table_info({table})")}
    con.close()
    forbidden = {"nom", "name", "email", "user", "username", "ip", "player"}
    assert not cols & forbidden


def test_full_simulation_save_and_resume(manager: SaveManager, data) -> None:  # type: ignore[no-untyped-def]
    sim = Simulation(data, "esn", seed=77)
    for _ in range(30):
        resolve_blockers(sim)
        sim.next_turn()
    sim.buy_measure("M10") if sim.measure_availability("M10")[0] else None
    manager.save(sim.to_dict(), "partie")
    restored = Simulation.from_dict(data, manager.load("partie"))
    assert restored.turn == sim.turn
    assert restored.budget.to_dict() == sim.budget.to_dict()
    assert restored.reputation.values == sim.reputation.values
    assert len(restored.incidents.incidents) == len(sim.incidents.incidents)
    # même graine + même état → mêmes tirages
    resolve_blockers(sim)
    resolve_blockers(restored)
    a, b = sim.next_turn(), restored.next_turn()
    assert a.detected == b.detected and a.events == b.events
    assert sim.rng.random() == restored.rng.random()


def test_incompatible_simulation_version(data) -> None:  # type: ignore[no-untyped-def]
    state = Simulation(data, "mairie", seed=1).to_dict()
    state["version"] = 999
    with pytest.raises(ValueError):
        Simulation.from_dict(data, state)
