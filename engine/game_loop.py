"""Boucle principale Pygame (60 FPS, delta time) et machine à états des écrans.

États : MENU | ORG_SELECT | DASHBOARD | INCIDENT | EBIOS | AUDIT | BUDGET | GAME_OVER
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import pygame

import config
from ai.llm_adapter import StaticNarrator, create_narrator
from engine import renderer as R
from engine.audio import Audio
from engine.event_bus import Event, EventBus
from engine.save_manager import AUTOSAVE_SLOT, SaveError, SaveManager
from game.scoring import compute_score
from game.data_loader import GameData, get_data
from game.simulation import Simulation
from game.state import GameScreen
from ui.components.dialog_box import DialogStack
from ui.components.help import TOURS, CoachTour, HelpOverlay
from ui.components.widgets import UI

log = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "volume": 0.6,
    "fullscreen": False,
    "timers": True,          # comptes à rebours en temps réel pour les décisions urgentes
    "ai": True,              # narration IA locale si un modèle est présent
    "tutorial_done": False,
    "difficulty": "standard",
    "years": 3,
    "pseudo": "",
}


def _load_settings(stored: Any) -> dict[str, Any]:
    """Fusionne les préférences enregistrées avec les valeurs par défaut, en écartant
    toute valeur d'un type inattendu (base modifiée à la main ou corrompue)."""
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(stored, dict):
        for key, value in stored.items():
            if not isinstance(key, str):
                continue
            default = DEFAULT_SETTINGS.get(key)
            if default is None:
                if isinstance(value, bool):  # drapeaux annexes (tour_disabled…)
                    settings[key] = value
            elif type(value) is type(default) or (type(default) is float and type(value) is int):
                settings[key] = value
    settings["volume"] = min(1.0, max(0.0, float(settings["volume"])))
    from game.difficulty import DIFFICULTIES
    if settings["difficulty"] not in DIFFICULTIES:
        settings["difficulty"] = DEFAULT_SETTINGS["difficulty"]
    if settings["years"] not in (1, 2, 3):
        settings["years"] = DEFAULT_SETTINGS["years"]
    settings["pseudo"] = settings["pseudo"][:20]
    return settings


class GameApp:
    def __init__(
        self,
        size: tuple[int, int] | None = None,
        headless: bool = False,
        seed: int | None = None,
        scenario: str | None = None,
        data: GameData | None = None,
        saves: SaveManager | None = None,
        fullscreen: bool | None = None,
    ) -> None:
        self.headless = headless
        self.seed = seed
        self.data = data or get_data()
        paths = config.user_paths().ensure()
        self.saves = saves or SaveManager(paths.saves_db)
        self.settings = _load_settings(self.saves.get_meta("settings", {}))
        if fullscreen is not None:
            self.settings["fullscreen"] = fullscreen
        pygame.init()
        self.surface, self.display = R.init_display(size, bool(self.settings["fullscreen"]), headless)
        pygame.display.set_caption(f"{config.APP_TITLE} — v{config.VERSION}")
        self.clock = pygame.time.Clock()
        self.bus = EventBus()
        self.audio = Audio(enabled=not headless, volume=float(self.settings["volume"]))
        self.narrator: StaticNarrator = create_narrator(bool(self.settings["ai"]) and not headless, seed)
        self.ui = UI(self.surface)
        self.ui.click_sound = lambda: self.audio.play("click")
        self.dialogs = DialogStack()
        self.sim: Simulation | None = None
        self.running = True
        self.toasts: list[tuple[str, str, float]] = []
        self.net = None            # ui.net_session.NetSession | None
        self.help = HelpOverlay()
        self.tour: CoachTour | None = None
        self.tour_queue: list[str] = []
        self.tips_seen: set[str] = set()
        self.fade = 0.0
        self._last_progress: tuple | None = None
        self._screens: dict[str, Any] = {}
        self.screen_name = GameScreen.MENU.value
        self.screen = self._get_screen(self.screen_name)
        self.bus.subscribe("incident.detected", self._on_incident_detected)
        self.bus.subscribe("game.over", lambda e: self.audio.play("fail"))
        if scenario:
            self.start_game(scenario, seed)

    # -- écrans --------------------------------------------------------------------
    def _factory(self, name: str) -> Callable[["GameApp"], Any]:
        from ui.screens.audit_screen import AuditScreen
        from ui.screens.budget_screen import BudgetScreen
        from ui.screens.dashboard import DashboardScreen
        from ui.screens.ebios_workshop import EbiosScreen
        from ui.screens.game_over import GameOverScreen
        from ui.screens.incident_room import IncidentRoomScreen
        from ui.screens.lobby import LobbyScreen
        from ui.screens.operations import OperationsScreen
        from ui.screens.main_menu import MainMenuScreen
        from ui.screens.org_selection import OrgSelectionScreen
        return {
            GameScreen.MENU.value: MainMenuScreen, GameScreen.ORG_SELECT.value: OrgSelectionScreen,
            GameScreen.DASHBOARD.value: DashboardScreen, GameScreen.INCIDENT.value: IncidentRoomScreen,
            GameScreen.EBIOS.value: EbiosScreen, GameScreen.AUDIT.value: AuditScreen,
            GameScreen.BUDGET.value: BudgetScreen, GameScreen.GAME_OVER.value: GameOverScreen,
            GameScreen.OPERATIONS.value: OperationsScreen, GameScreen.LOBBY.value: LobbyScreen,
        }[name]

    def _get_screen(self, name: str) -> Any:
        if name not in self._screens:
            self._screens[name] = self._factory(name)(self)
        return self._screens[name]

    def switch(self, name: str | GameScreen, **kwargs: Any) -> None:
        name = name.value if isinstance(name, GameScreen) else name
        self.screen.on_exit()
        self.screen_name = name
        self.screen = self._get_screen(name)
        self.ui.drag = None
        self.ui.focus = None
        self.fade = 0.22
        if self.tour is not None and self.tour.key != name:
            self.tour = None
        sim = self.sim
        if (sim is not None and sim.difficulty.show_hints and not self.settings.get("tour_disabled")
                and name in TOURS and name != GameScreen.DASHBOARD.value
                and name not in self.tips_seen and name not in self.tour_queue):
            self.tour_queue.append(name)
        self.screen.on_enter(**kwargs)
        self.bus.publish("screen.changed", screen=name)

    # -- partie --------------------------------------------------------------------------
    def start_game(self, org_id: str, seed: int | None = None, difficulty: str | None = None,
                   years: int | None = None) -> None:
        self.sim = Simulation(self.data, org_id, seed=seed if seed is not None else self.seed, bus=self.bus,
                              difficulty=difficulty or self.settings.get("difficulty", "standard"),
                              years=years or int(self.settings.get("years", config.GAME_YEARS)))
        self._last_progress = None
        self.tips_seen = set()
        self.tour_queue = []
        self.tour = None
        if self.sim.difficulty.show_hints and not self.settings.get("tour_disabled"):
            self.tour_queue.append(GameScreen.DASHBOARD.value)
        self._screens = {k: v for k, v in self._screens.items() if k in (GameScreen.MENU.value,)}
        self.autosave()
        self.switch(GameScreen.DASHBOARD)

    def resume_game(self, slot: str = AUTOSAVE_SLOT) -> bool:
        try:
            state = self.saves.load(slot)
            self.sim = Simulation.from_dict(self.data, state, bus=self.bus)
        except Exception as exc:  # noqa: BLE001 - une sauvegarde altérée ne doit jamais faire planter le jeu
            log.warning("Reprise impossible : %s", exc)
            self.dialogs.info("Sauvegarde illisible",
                              f"La sauvegarde n'a pas pu être chargée ({exc}). Elle est peut-être corrompue "
                              "ou issue d'une version incompatible.", "danger")
            return False
        self._screens = {k: v for k, v in self._screens.items() if k == GameScreen.MENU.value}
        self.tips_seen = {GameScreen.DASHBOARD.value}
        self.tour_queue = []
        self.tour = None
        self.switch(GameScreen.GAME_OVER if self.sim.finished else GameScreen.DASHBOARD)
        return True

    def autosave(self, slot: str = AUTOSAVE_SLOT) -> None:
        if self.sim is None:
            return
        if self.net is not None and slot == AUTOSAVE_SLOT:
            slot = "reseau"   # une partie en réseau n'écrase pas la sauvegarde solo
        try:
            label = (f"{self.sim.org.nom} — semaine {self.sim.turn}/{self.sim.calendar.total_turns} — "
                     f"{self.sim.difficulty.nom}")
            self.saves.save(self.sim.to_dict(), slot, label)
        except Exception:  # la sauvegarde ne doit jamais interrompre la partie
            log.exception("Échec de la sauvegarde automatique")

    def save_settings(self) -> None:
        self.saves.set_meta("settings", self.settings)

    def toast(self, text: str, severity: str = "info") -> None:
        self.toasts.append((text, severity, 4.0))

    def _on_incident_detected(self, event: Event) -> None:
        self.audio.play("alert")

    # -- boucle -----------------------------------------------------------------------------
    def step(self, dt: float, events: list[pygame.event.Event] | None = None) -> None:
        events = events if events is not None else pygame.event.get()
        for ev in events:
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.VIDEORESIZE:
                R.enforce_min_size(self.display, ev)
        self.ui.begin_frame(events, dt)
        self._net_frame()
        if self.ui.key(pygame.K_F1):
            self.help.toggle()
            self.ui.keys_down = [k for k in self.ui.keys_down if k != pygame.K_F1]
        self._start_queued_tour()
        self.ui.input_enabled = not (self.dialogs.active or self.overlay_active)
        keys = self.ui.keys_down
        if self.overlay_active:   # aide ou visite : l'écran ne reçoit pas les touches
            self.ui.keys_down = []
        self.screen.update(dt)
        self.screen.draw(self.ui)
        self.ui.keys_down = keys
        self.ui.input_enabled = not self.overlay_active
        self.dialogs.draw(self.ui)
        if self.tour is not None:
            self.ui.input_enabled = not self.help.open
            self.tour.draw(self.ui, getattr(self.screen, "regions", {}), dt)
            if self.tour.done:
                if self.tour.disable_requested:
                    self.settings["tour_disabled"] = True
                    self.save_settings()
                self.tour = None
        self.ui.input_enabled = True
        self.help.draw(self.ui)
        if self.fade > 0:
            veil = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
            veil.fill((8, 10, 14, int(255 * min(1.0, self.fade / 0.22))))
            self.surface.blit(veil, (0, 0))
            self.fade = max(0.0, self.fade - dt)
        self._draw_toasts(dt)
        self.ui.end_frame()
        self.bus.dispatch()

    @property
    def overlay_active(self) -> bool:
        """Aide ou visite guidée affichée : l'écran sous-jacent est en pause."""
        return self.help.open or self.tour is not None

    def start_tour(self, key: str) -> None:
        if key in TOURS:
            self.tips_seen.add(key)
            self.tour = CoachTour(key, TOURS[key], disable_option=key == GameScreen.DASHBOARD.value)

    def _start_queued_tour(self) -> None:
        if self.tour is not None or self.dialogs.active or self.help.open or self.fade > 0:
            return
        if self.screen_name in self.tour_queue:
            self.tour_queue.remove(self.screen_name)
            self.start_tour(self.screen_name)

    # -- réseau local ------------------------------------------------------------------------
    def _net_frame(self) -> None:
        if self.net is None:
            return
        self.net.poll()
        for msg in self.net.events:
            self.toast(msg, "info")
        self.net.events.clear()
        if self.net.disconnected and self.sim is not None and not getattr(self, "_net_lost_shown", False):
            self._net_lost_shown = True
            self.toast(f"Session réseau interrompue : {self.net.disconnected}. La partie continue en solo.", "warning")
        if self.sim is not None and self.sim.finished and self.net.synchronized and self.net.waiting_for != 10_000:
            self.net.ready(10_000)   # partie terminée : ne plus bloquer les autres joueurs
        if self.sim is not None:
            progress = (self.sim.turn, self.sim.finished, len(self.sim.decisions), len(self.sim.incidents.incidents))
            if progress != self._last_progress:
                self._last_progress = progress
                card = compute_score(self.sim)
                self.net.send_progress(self.sim.turn, card.total, self.sim.reputation.global_score(),
                                       len(self.sim.visible_incidents()), self.sim.finished)

    def leave_network(self) -> None:
        if self.net is not None:
            self.net.close()
            self.net = None
            self._net_lost_shown = False

    def _draw_toasts(self, dt: float) -> None:
        from ui.components.widgets import severity_color
        w, h = self.surface.get_size()
        y = h - 20
        remaining = []
        for text, sev, ttl in reversed(self.toasts):
            ttl -= dt
            if ttl <= 0:
                continue
            remaining.append((text, sev, ttl))
            width = min(560, R.font("body").size(text)[0] + 40)
            rect = pygame.Rect(w - width - 20, y - 46, width, 42)
            R.panel(self.surface, rect, "panel_alt", None)
            pygame.draw.rect(self.surface, severity_color(sev), (rect.x, rect.y, 5, rect.height),
                             border_top_left_radius=8, border_bottom_left_radius=8)
            R.draw_text(self.surface, text, (rect.x + 18, rect.centery), "body", "text", anchor="midleft")
            y -= 52
        self.toasts = list(reversed(remaining))

    def run(self, max_frames: int | None = None) -> None:
        frames = 0
        while self.running:
            dt = self.clock.tick(config.FPS) / 1000.0
            self.step(min(dt, 0.1))
            pygame.display.flip()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break
        self.autosave()
        self.leave_network()
        self.saves.close()
        pygame.quit()
