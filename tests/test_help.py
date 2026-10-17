"""Aide (F1) et visites guidées de la difficulté Découverte."""
from __future__ import annotations

import pygame
import pytest

from engine.game_loop import GameApp
from engine.save_manager import SaveManager
from game.incident_engine import Phase
from ui.components.help import HELP_SECTIONS, TOURS

E = pygame.event.Event


@pytest.fixture
def app(tmp_path, data):  # type: ignore[no-untyped-def]
    application = GameApp(size=(1280, 720), headless=True, seed=5, data=data, saves=SaveManager(tmp_path / "s.db"))
    application.settings["tutorial_done"] = True
    yield application
    pygame.quit()


def frames(app, n: int = 1, events=None) -> None:  # type: ignore[no-untyped-def]
    for i in range(n):
        app.step(1 / 60, list(events or []) if i == 0 else [])


def key(k: int):  # type: ignore[no-untyped-def]
    return [E(pygame.KEYDOWN, key=k, mod=0, unicode="")]


def test_discovery_starts_guided_tour(app) -> None:  # type: ignore[no-untyped-def]
    app.settings["difficulty"] = "decouverte"
    app.start_game("mairie", 1)
    frames(app, 20)
    assert app.tour is not None and app.tour.key == "DASHBOARD"
    frames(app, 1, key(pygame.K_SPACE))   # Espace = étape suivante, pas la semaine suivante
    assert app.sim.turn == 1 and app.tour.index == 1
    frames(app, 1, key(pygame.K_LEFT))
    assert app.tour.index == 0
    for _ in range(len(TOURS["DASHBOARD"])):
        frames(app, 1, key(pygame.K_RIGHT))
        frames(app, 2)
    assert app.tour is None and app.sim.turn == 1


def test_all_tour_steps_render_with_regions(app) -> None:  # type: ignore[no-untyped-def]
    app.settings["difficulty"] = "decouverte"
    app.start_game("hopital", 2)
    inc = app.sim._start_incident("INC-001")
    if not inc.detected:
        inc.phase = Phase.DETECTION
        app.sim._on_detected(inc)
    for screen, steps in TOURS.items():
        kwargs = {"incident": inc.uid} if screen == "INCIDENT" else {}
        app.switch(screen, **kwargs)
        frames(app, 20)
        app.start_tour(screen)
        for step in steps:
            frames(app, 2)
            if step.region:
                assert step.region in app.screen.regions, (screen, step.region)
            frames(app, 1, key(pygame.K_RIGHT))
        frames(app, 2)
        assert app.tour is None


def test_contextual_tips_once_and_only_in_discovery(app) -> None:  # type: ignore[no-untyped-def]
    app.settings["difficulty"] = "decouverte"
    app.start_game("esn", 3)
    app.tour_queue.clear()
    app.switch("BUDGET")
    frames(app, 20)
    assert app.tour is not None and app.tour.key == "BUDGET"
    frames(app, 1, key(pygame.K_ESCAPE))   # « Passer » : on reste sur l'écran
    frames(app, 2)
    assert app.tour is None and app.screen_name == "BUDGET"
    app.switch("DASHBOARD")
    app.switch("BUDGET")
    frames(app, 20)
    assert app.tour is None                  # déjà vu
    app.settings["difficulty"] = "standard"
    app.start_game("esn", 3)
    frames(app, 20)
    app.switch("OPERATIONS")
    frames(app, 20)
    assert app.tour is None


def test_tour_can_be_disabled(app) -> None:  # type: ignore[no-untyped-def]
    app.settings["difficulty"] = "decouverte"
    app.start_game("mairie", 4)
    frames(app, 20)
    tour = app.tour
    tour.index = len(tour.steps) - 1
    tour.disable_requested = True
    frames(app, 1, key(pygame.K_RETURN))
    frames(app, 2)
    assert app.settings["tour_disabled"] is True
    app.start_game("mairie", 5)
    frames(app, 20)
    assert app.tour is None
    app.switch("EBIOS")
    frames(app, 20)
    assert app.tour is None


def test_help_overlay_everywhere(app) -> None:  # type: ignore[no-untyped-def]
    frames(app, 3, key(pygame.K_F1))         # au menu
    assert app.help.open
    for i in range(len(HELP_SECTIONS)):
        app.help.section = i
        frames(app, 2)
    frames(app, 1, key(pygame.K_DOWN))
    frames(app, 1, key(pygame.K_ESCAPE))
    assert not app.help.open and app.screen_name == "MENU"
    app.settings["difficulty"] = "standard"
    app.start_game("telecom", 6)
    for screen in ("DASHBOARD", "BUDGET", "AUDIT", "EBIOS", "OPERATIONS", "ORG_SELECT", "LOBBY"):
        app.switch(screen)
        frames(app, 2)
        frames(app, 1, key(pygame.K_F1))
        assert app.help.open, screen
        frames(app, 1, key(pygame.K_ESCAPE))   # ferme l'aide sans quitter l'écran
        assert not app.help.open and app.screen_name == screen


def test_hud_help_button_and_week_total(app) -> None:  # type: ignore[no-untyped-def]
    app.settings["difficulty"] = "standard"
    app.settings["years"] = 1
    app.start_game("pme_industrie", 7)
    frames(app, 20)
    r = app.screen.regions["help"]
    frames(app, 1, [E(pygame.MOUSEBUTTONDOWN, button=1, pos=r.center)])
    frames(app, 1, [E(pygame.MOUSEBUTTONUP, button=1, pos=r.center)])
    assert app.help.open
    assert app.sim.calendar.total_turns == 52


def test_crisis_timer_paused_during_help(app) -> None:  # type: ignore[no-untyped-def]
    app.settings["difficulty"] = "standard"
    app.start_game("hopital", 8)
    inc = app.sim._start_incident("INC-001")
    if not inc.detected:
        inc.phase = Phase.DETECTION
        app.sim._on_detected(inc)
    app.switch("INCIDENT", incident=inc.uid)
    frames(app, 20)
    timer = app.screen.timer
    assert timer is not None
    app.help.toggle()
    for _ in range(120):
        app.step(1.0, [])
    assert app.screen.timer == timer and not inc.decisions_taken
