"""Intégrité des données, calendrier, organisations, IA optionnelle, RGPD (aucun accès réseau)."""
from __future__ import annotations

import ast
import random
from datetime import date
from pathlib import Path

import pytest
import yaml

import config
from ai import prompt_builder
from ai.llm_adapter import StaticNarrator, create_narrator, detect_hardware, find_model
from engine.event_bus import EventBus
from game.calendar import GameCalendar
from game.event_engine import EventEngine, load_events
from game.organisation import Organisation, OrganisationError, load_organisation

ROOT = Path(__file__).resolve().parent.parent


# -- organisations --------------------------------------------------------------
def test_five_organisations_with_specified_figures(data) -> None:  # type: ignore[no-untyped-def]
    orgs = data.organisations
    assert set(orgs) == {"hopital", "mairie", "pme_industrie", "esn", "telecom"}
    expected = {
        "hopital": (850, 1_200_000, 72_000), "mairie": (420, 650_000, 39_000),
        "pme_industrie": (180, 320_000, 19_200), "esn": (400, 900_000, 63_000),
        "telecom": (2_200, 8_000_000, 640_000),
    }
    for oid, (emp, it, ssi) in expected.items():
        o = orgs[oid]
        assert (o.taille_employes, o.budget_it, o.budget_ssi) == (emp, it, ssi)
        assert 1 <= o.difficulte <= 5
    assert orgs["hopital"].regimes.nis2 == "essentielle" and orgs["hopital"].regimes.hds
    assert orgs["mairie"].regimes.nis2 == "importante"
    assert orgs["telecom"].regimes.lpm_oiv
    assert orgs["hopital"].dpo_required and not orgs["pme_industrie"].dpo_required


def test_organisation_validation() -> None:
    raw = yaml.safe_load((config.ORGANISATIONS_DIR / "mairie.yaml").read_text(encoding="utf-8"))
    for mutate in (lambda d: d.pop("budget_ssi"), lambda d: d.update(difficulte=9),
                   lambda d: d.update(budget_ssi=0), lambda d: d["probabilites_incidents"].update(zombie=0.1),
                   lambda d: d["probabilites_incidents"].update(ddos=1.5), lambda d: d["enjeux"].append({"a": "b"})):
        broken = yaml.safe_load(yaml.safe_dump(raw))
        mutate(broken)
        with pytest.raises(OrganisationError):
            Organisation.from_dict(broken)
    org = load_organisation(config.ORGANISATIONS_DIR / "mairie.yaml")
    assert org.difficulty_label == "Débutant" and org.endpoints == 380


def test_measure_catalogue(data) -> None:  # type: ignore[no-untyped-def]
    assert len(data.measures) == 40
    iso_ids = {c["id"] for c in data.iso_controls}
    for m in data.measures.values():
        assert m.controle_iso and set(m.controle_iso) <= iso_ids, m.id
        assert m.guide_anssi
        assert m.delai_semaines >= 1
        assert all(0 <= v <= 1 for v in {**m.reduction_risque, **m.reduction_impact}.values())
        assert all(1 <= h <= 42 for h in m.hygiene)
        assert all(p in data.measures for p in m.prerequis)


def test_references_between_files(data) -> None:  # type: ignore[no-untyped-def]
    for t in data.incidents.values():
        assert all(m in data.measures for m in t.mesures_cles), t.id
    for o in data.organisations.values():
        assert all(m in data.measures for m in o.mesures_initiales), o.id
    for ev in data.events.values():
        assert all(o in data.organisations for o in ev.organisations), ev.id
        for c in ev.choix:
            if "incident" in c.effets:
                assert c.effets["incident"] in data.incidents
            if "mesure_offerte" in c.effets:
                assert c.effets["mesure_offerte"] in data.measures


def test_referentials(data) -> None:  # type: ignore[no-untyped-def]
    assert len(data.referential.hygiene) == 42
    assert len(data.iso_controls) == 93
    themes = {c["theme"] for c in data.iso_controls}
    assert len(themes) == 4
    assert len(data.events) >= 3
    assert "chiffres_cles" in data.threats
    assert "rgpd" in data.regulations["regimes"]


def test_three_event_files() -> None:
    assert len(list(config.EVENTS_DIR.glob("*.yaml"))) == 3


def test_event_engine_roll(data) -> None:  # type: ignore[no-untyped-def]
    eng = EventEngine(data.organisations["mairie"], data.events, random.Random(0))
    seen = [eng.roll(t, 1 + t // 52) for t in range(1, 156)]
    fired = [e for e in seen if e]
    assert fired and len({e.id for e in fired}) == len(fired)  # événements uniques
    assert all(n <= 10 for n in eng.per_year.values())
    other = EventEngine(data.organisations["mairie"], data.events, random.Random(0))
    other.load_dict(eng.to_dict())
    assert other.seen == eng.seen
    with pytest.raises(KeyError):
        fired[0].choice("ZZ")
    assert load_events(config.EVENTS_DIR)


# -- calendrier -------------------------------------------------------------------
def test_calendar() -> None:
    cal = GameCalendar(date(2026, 1, 5))
    assert cal.date_for(1) == date(2026, 1, 5)
    assert cal.date_for(53) == date(2027, 1, 4)
    assert cal.year_of(52) == 1 and cal.year_of(53) == 2 and cal.year_of(156) == 3
    assert cal.is_year_start(105) and cal.is_year_end(104)
    assert cal.week_of_year(60) == 8
    assert cal.is_finished(157) and not cal.is_finished(156)
    assert cal.remaining(150) == 6
    assert cal.month_of(1) == 1
    assert cal.date_for(cal.turn_for_year_month(2, 6)).month == 6
    assert "janvier 2026" in cal.label(1)
    assert GameCalendar.format_date(date(2026, 3, 2), with_day=True).startswith("lun.")


# -- bus d'événements ----------------------------------------------------------------
def test_event_bus_wildcards_and_queue() -> None:
    bus = EventBus()
    got: list[str] = []
    unsub = bus.subscribe("incident.*", lambda e: got.append(e.topic))
    bus.subscribe("*", lambda e: got.append("all"))
    bus.subscribe("x", lambda e: 1 / 0)  # un abonné défaillant n'interrompt pas la diffusion
    bus.publish("incident.detected", uid="I1")
    assert bus.pending == 1 and got == []
    assert bus.dispatch() == 1
    assert got == ["incident.detected", "all"]
    bus.emit("x")
    unsub()
    bus.emit("incident.closed")
    assert got[-1] == "all" and "incident.closed" not in got
    assert bus.history[-1].get("uid") is None
    bus.clear()
    assert bus.pending == 0


# -- IA optionnelle ----------------------------------------------------------------------
def test_static_narrator_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(config.AI_ENABLED_ENV, "1")
    narrator = create_narrator(enabled=True, seed=1, models_dir=tmp_path)
    assert isinstance(narrator, StaticNarrator) and narrator.backend == "static"
    msg = narrator.team_message({"heure": 4, "phase": "Confinement"}, [{"de": "SOC", "texte": "ok"}])
    assert msg == {"de": "SOC", "texte": "ok"}
    assert "H+4" in narrator.team_message({"heure": 4, "phase": "Confinement"})["texte"]
    assert narrator.rex_summary({}, "texte") == "texte"
    assert create_narrator(enabled=False).backend == "static"
    assert find_model(tmp_path) is None


def test_find_model_and_hardware(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "petit.gguf").write_bytes(b"0" * 10)
    assert find_model(tmp_path).name == "petit.gguf"
    monkeypatch.setenv(config.AI_MODEL_ENV, str(tmp_path / "petit.gguf"))
    assert find_model(None).name == "petit.gguf"
    hw = detect_hardware()
    assert hw.backend in {"nvidia", "amd", "cpu"}
    assert hw.n_threads >= 1
    assert (hw.n_gpu_layers == -1) == (hw.backend != "cpu")


def test_prompt_guardrails() -> None:
    msgs = prompt_builder.chat_format(prompt_builder.team_message_prompt({"incident": "X", "heure": 2}))
    assert msgs[0]["role"] == "system" and "n'invente aucune" in msgs[0]["content"]
    assert "H+2" in msgs[1]["content"]
    assert "Décisions prises" in prompt_builder.rex_summary_prompt({"decisions": ["a"]})


# -- RGPD / plateforme ---------------------------------------------------------------------
def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _project_files():  # type: ignore[no-untyped-def]
    for path in ROOT.rglob("*.py"):
        if not any(part in {".venv", "venv", "build", "dist", "tests"} for part in path.relative_to(ROOT).parts):
            yield path


INTERNET_CLIENTS = {"urllib", "urllib.request", "http.client", "requests", "httpx", "aiohttp", "urllib3", "ftplib",
                    "smtplib", "telnetlib", "websocket", "paramiko", "ssl"}
NET_ALLOWED_IMPORTERS = {"ui/net_session.py", "ui/screens/lobby.py"}


def test_no_internet_access_in_code() -> None:
    """RGPD : aucun client Internet ; les sockets sont confinés au multijoueur LAN (package net/)."""
    offenders = []
    for path in _project_files():
        rel = path.relative_to(ROOT).as_posix()
        for name in _imports(path):
            root = name.split(".")[0]
            if name in INTERNET_CLIENTS or root in {"requests", "httpx", "aiohttp", "urllib3", "urllib", "http"}:
                offenders.append(f"{rel}:{name}")
            if root == "socket" and not rel.startswith("net/"):
                offenders.append(f"{rel}:{name}")
            if root == "net" and not rel.startswith("net/") and rel not in NET_ALLOWED_IMPORTERS:
                offenders.append(f"{rel}:{name}")
    assert offenders == [], f"Imports réseau interdits : {offenders}"


def test_lan_only_guard() -> None:
    from net.protocol import is_lan_address
    for ip in ("10.1.2.3", "192.168.0.10", "172.16.5.4", "127.0.0.1", "fe80::1"):
        assert is_lan_address(ip)
    for ip in ("8.8.8.8", "1.1.1.1", "2001:4860:4860::8888", "pas-une-ip"):
        assert not is_lan_address(ip)


def test_user_data_dir_per_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("RSSI_SIMULATOR_DATA_DIR", raising=False)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert config.user_data_dir() == tmp_path / "Roaming" / "rssi-simulator"
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert config.user_data_dir() == Path.home() / ".local" / "share" / "rssi-simulator"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert config.user_data_dir() == tmp_path / "xdg" / "rssi-simulator"
    monkeypatch.setattr(config.sys, "platform", "darwin")
    assert "Application Support" in str(config.user_data_dir())
    paths = config.UserPaths(tmp_path / "u").ensure()
    assert paths.reports_dir.is_dir() and paths.saves_db.name.endswith(".sqlite3")
    assert paths.settings_file.suffix == ".yaml" and paths.log_file.suffix == ".log"


def test_legacy_data_dir_is_migrated(tmp_path: Path) -> None:
    legacy = tmp_path / "cyber-rssi"
    legacy.mkdir()
    (legacy / "saves.sqlite3").write_bytes(b"partie")
    (legacy / "cyber-rssi.log").write_text("ancien journal", encoding="utf-8")
    paths = config.UserPaths(tmp_path / "rssi-simulator").ensure()
    assert not legacy.exists()
    assert paths.saves_db.read_bytes() == b"partie"
    assert paths.log_file.read_text(encoding="utf-8") == "ancien journal"


def test_headless_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)
    assert not config.is_headless()
    config.enable_headless()
    assert config.is_headless()


def test_logo_and_icons_are_shipped() -> None:
    import pygame
    from engine import renderer as R
    assert (config.IMAGES_DIR / "icon.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
    pygame.init()
    R.logo.cache_clear()
    img = R.logo(30)
    assert img is not None and img.get_size() == (30, 30)
