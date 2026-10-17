"""Configuration commune : mode headless obligatoire et dossier de données isolé."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "offscreen"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["RSSI_SIMULATOR_AI"] = "0"

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from game.data_loader import GameData, get_data  # noqa: E402
from game.simulation import Simulation  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RSSI_SIMULATOR_DATA_DIR", str(tmp_path / "userdata"))
    return tmp_path / "userdata"


@pytest.fixture(scope="session")
def data() -> GameData:
    return get_data()


@pytest.fixture
def sim(data: GameData) -> Simulation:
    return Simulation(data, "hopital", seed=1234)


@pytest.fixture
def org(data: GameData):  # type: ignore[no-untyped-def]
    return data.organisations["hopital"]


def resolve_blockers(s: Simulation, quality: str = "bonne") -> None:
    """Résout crises et événements en attente pour pouvoir avancer."""
    for inc in s.active_crises():
        while (d := s.incidents.pending_decision(inc)) is not None:
            choice = next((c for c in d.choix if c.qualite == quality), d.choix[0])
            s.crisis_decide(inc.uid, d.id, choice.id)
        s.crisis_close(inc.uid)
    for eid in list(s.pending_events):
        s.resolve_event(eid, s.data.events[eid].choix[0].id) if s.event_choice_available(
            eid, s.data.events[eid].choix[0].id)[0] else s.pending_events.remove(eid)
    if s.pending_board:
        s.resolve_board("bilan")
