"""Fumée de l'interface en mode headless (SDL_VIDEODRIVER=offscreen) : chaque écran se dessine."""
from __future__ import annotations

import pygame
import pytest

from engine.audio import Audio, _synth
from engine.game_loop import GameApp
from engine.renderer import format_eur, wrap_text, font
from engine.save_manager import SaveManager
from game.incident_engine import Phase
from tests.conftest import resolve_blockers


@pytest.fixture
def app(tmp_path, data):  # type: ignore[no-untyped-def]
    application = GameApp(size=(1280, 720), headless=True, seed=5, data=data,
                          saves=SaveManager(tmp_path / "s.sqlite3"))
    yield application
    pygame.quit()


def frames(app, n: int = 2, events=None) -> None:  # type: ignore[no-untyped-def]
    for _ in range(n):
        app.step(1 / 60, list(events or []))


def click(app, pos) -> None:  # type: ignore[no-untyped-def]
    frames(app, 1, [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)])
    frames(app, 1, [pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)])


def test_display_headless(app) -> None:  # type: ignore[no-untyped-def]
    assert app.display.mode == "headless"
    assert app.surface.get_size() == (1280, 720)


def test_menu_and_screens(app) -> None:  # type: ignore[no-untyped-def]
    frames(app)
    app.screen.mode = "options"
    frames(app)
    app.screen.mode = "credits"
    frames(app)
    app.switch("ORG_SELECT")
    app.screen.selected = "mairie"
    frames(app)
    app.screen._start()  # premier lancement : tutoriel obligatoire
    assert app.dialogs.active and app.sim is None
    for _ in range(10):
        if not app.dialogs.items:
            break
        app.dialogs.items[0].buttons[0].action and app.dialogs.items[0].buttons[0].action()
        app.dialogs.items.pop(0)
    assert app.sim is not None and app.settings["tutorial_done"]
    for name in ("DASHBOARD", "BUDGET", "AUDIT", "EBIOS"):
        app.switch(name)
        frames(app)
    app.switch("BUDGET")
    app.screen.selected = "M16"
    frames(app)
    for tab in range(1, 6):
        app.switch("EBIOS")
        app.screen.tab = tab
        frames(app)


def test_dashboard_next_week_via_keyboard(app) -> None:  # type: ignore[no-untyped-def]
    app.settings["tutorial_done"] = True
    app.start_game("pme_industrie", 3)
    assert app.screen_name == "DASHBOARD"
    frames(app, 1, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)])
    assert app.sim.turn == 2 or app.sim.pending_events or app.screen_name == "INCIDENT"


def test_incident_room_flow(app) -> None:  # type: ignore[no-untyped-def]
    app.start_game("hopital", 5)
    sim = app.sim
    inc = sim._start_incident("INC-001")
    if not inc.detected:
        inc.phase = Phase.DETECTION
        sim._on_detected(inc)
    app.switch("INCIDENT", incident=inc.uid)
    frames(app)
    d = sim.incidents.pending_decision(inc)
    app.screen.timer = 0.01
    app.screen.timer_for = d.id
    frames(app, 3)  # délai écoulé → choix par défaut
    assert inc.decisions_taken and inc.decisions_taken[0]["choice_id"] == d.default_choice.id
    frames(app)
    app.screen.feedback = None
    for dl in sim.compliance.deadlines_for(inc.uid):
        sim.notify_obligation(inc.uid, dl.kind)
    while (d := sim.incidents.pending_decision(inc)) is not None:
        app.screen._decide(d.id, d.choix[0].id)
        app.screen.feedback = None
    frames(app)  # REX
    sim.crisis_close(inc.uid)
    app.switch("INCIDENT")
    frames(app)  # aucune crise


def test_event_dialog_and_game_over(app) -> None:  # type: ignore[no-untyped-def]
    app.start_game("esn", 9)
    sim = app.sim
    sim.pending_events.append(next(iter(sim.events.events)))
    frames(app)
    assert app.dialogs.active
    dlg = app.dialogs.items[0]
    dlg.buttons[0].action()
    assert not sim.pending_events
    app.dialogs.items.clear()
    resolve_blockers(sim)
    sim.reputation.apply({"tous": -100})
    sim.next_turn()
    frames(app)
    assert app.screen_name == "GAME_OVER"
    frames(app)
    app.screen.report_path = None
    w, h = app.surface.get_size()
    click(app, (w - 200, h - 42))
    assert app.screen.report_path is not None and app.screen.report_path.exists()


def test_resume_and_corrupted_save(app) -> None:  # type: ignore[no-untyped-def]
    app.start_game("mairie", 2)
    app.autosave()
    assert app.resume_game()
    import sqlite3
    con = sqlite3.connect(app.saves.db_path)
    con.execute("UPDATE saves SET payload = '{}'")
    con.commit()
    con.close()
    assert app.resume_game() is False
    assert app.dialogs.active


def test_toasts_and_quit(app) -> None:  # type: ignore[no-untyped-def]
    app.toast("Bonjour", "success")
    frames(app)
    frames(app, 1, [pygame.event.Event(pygame.QUIT)])
    assert not app.running


def test_render_helpers() -> None:
    pygame.font.init()
    assert format_eur(1234567) == "1 234 567 €"
    assert format_eur(-5) == "-5 €"
    lines = wrap_text("un texte assez long pour être coupé en plusieurs lignes", font(14), 80)
    assert len(lines) > 1


def test_audio_silent_fallback() -> None:
    a = Audio(enabled=False)
    a.play("alert")
    a.set_volume(2)
    assert a.volume == 1.0 and not a.enabled
    assert len(_synth([(440, 0.01)])) > 0
