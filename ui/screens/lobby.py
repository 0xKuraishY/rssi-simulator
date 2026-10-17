"""Salon multijoueur en réseau local : héberger ou rejoindre une session de formation."""
from __future__ import annotations

import pygame

from engine import renderer as R
from game.difficulty import DIFFICULTIES, DURATIONS
from game.state import GameScreen
from net.protocol import DEFAULT_PORT, MODES, local_lan_ips
from ui.components.widgets import UI, section, split_h
from ui.net_session import Background, NetSession, discover_sessions, join_async
from ui.screens.base import Screen

MODE_LABELS = {"libre": "Libre — chacun à son rythme", "synchronise": "Synchronisé — tous avancent ensemble"}
IP_CHARS = "0123456789."
PIN_CHARS = "0123456789"


class LobbyScreen(Screen):
    name = GameScreen.LOBBY.value
    show_hud = False

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.mode = "choix"
        self.pseudo = ""
        self.org_index = 0
        self.difficulty = "standard"
        self.years = 1
        self.net_mode = "synchronise"
        self.ip = ""
        self.port = str(DEFAULT_PORT)
        self.pin = ""
        self.scan: Background | None = None
        self.join_task: Background | None = None
        self.found = []
        self.error = ""
        self.ips: list[str] = []

    def on_enter(self, **kwargs: object) -> None:
        self.pseudo = self.app.settings.get("pseudo", "") or self.pseudo
        self.error = ""
        if self.app.net is None:
            self.mode = "choix"

    # -- logique ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        if self.scan is not None and self.scan.done:
            self.found = self.scan.result or []
            if self.scan.error:
                self.error = f"Recherche impossible : {self.scan.error}"
            self.scan = None
        if self.join_task is not None and self.join_task.done:
            if self.join_task.error:
                self.error = self.join_task.error
            else:
                self.app.net = self.join_task.result
                self.mode = "attente"
            self.join_task = None
        net = self.app.net
        if net is not None and net.start is not None and self.app.sim is None and not net.is_host:
            self._start_game()
        if net is not None and net.disconnected and self.mode == "attente":
            self.error = f"Session interrompue : {net.disconnected}"
            self.app.leave_network()
            self.mode = "rejoindre"

    def _start_game(self) -> None:
        net = self.app.net
        p = net.start
        # paramètres venus du réseau : un hôte malveillant ou d'une autre version ne doit pas faire planter le jeu
        if (p.org_id not in self.app.data.organisations or p.difficulty not in DIFFICULTIES
                or p.years not in DURATIONS):
            self.error = "Paramètres de partie inconnus reçus de l'hôte (version différente ?)"
            self.app.leave_network()
            self.mode = "rejoindre"
            return
        self.app.settings["tutorial_done"] = True
        self.app.start_game(p.org_id, p.seed, p.difficulty, p.years)

    def _remember_pseudo(self) -> None:
        self.app.settings["pseudo"] = self.pseudo.strip()
        self.app.save_settings()

    def _create(self) -> None:
        org = list(self.app.data.organisations)[self.org_index % len(self.app.data.organisations)]
        try:
            port = int(self.port)
            self.app.net = NetSession.create_host(self.pseudo.strip(), org, self.difficulty, self.years,
                                                  self.net_mode, port=port)
        except (OSError, ValueError) as exc:
            self.error = f"Impossible d'ouvrir la session sur le port {self.port} : {exc}"
            return
        self._remember_pseudo()
        self.ips = local_lan_ips()
        self.mode = "attente"

    def _leave(self) -> None:
        self.app.leave_network()
        self.mode = "choix"
        self.error = ""

    # -- dessin -------------------------------------------------------------------------
    def draw_content(self, ui: UI) -> None:
        surf = ui.surface
        w, h = surf.get_size()
        R.draw_text(surf, "Session en réseau local", (24, 20), "h1", "text", "bold")
        R.draw_text(surf, "Formation en groupe : tous jouent la même organisation, avec la même graine, et se "
                          "comparent en direct.", (24, 66), "body", "text_muted")
        area = pygame.Rect(24, 110, w - 48, h - 200)
        getattr(self, f"_{self.mode}")(ui, area)
        if self.error:
            R.draw_wrapped(surf, self.error, pygame.Rect(260, h - 76, w - 560, 50), "small", "danger")
        if ui.button(pygame.Rect(w - 140, 24, 116, 40), "? Aide", "ghost", tooltip="Session en réseau local (F1)"):
            self.app.help.toggle(11)
        label = "← Quitter la session" if self.app.net is not None else "← Menu principal"
        if ui.button(pygame.Rect(24, h - 70, 220, 48), label, "ghost") or ui.key(pygame.K_ESCAPE):
            if self.app.net is not None:
                self._leave()
            elif self.mode != "choix":
                self.mode = "choix"
            else:
                self.app.switch(GameScreen.MENU)

    def _choix(self, ui: UI, area: pygame.Rect) -> None:
        surf = ui.surface
        left, right = split_h(pygame.Rect(area.x, area.y, area.width, 300), [1, 1], gap=20)
        for rect, title, text, mode in (
                (left, "Héberger une session", "Le formateur (ou un joueur) choisit l'organisation, la difficulté "
                 "et le mode. Un code PIN est communiqué aux participants.", "heberger"),
                (right, "Rejoindre une session", "Recherchez les sessions du réseau local ou saisissez l'adresse "
                 "IP de l'hôte, puis le code PIN.", "rejoindre")):
            c = section(surf, rect, title)
            R.draw_wrapped(surf, text, pygame.Rect(c.x, c.y, c.width, 120), "body", "text_muted")
            if ui.button(pygame.Rect(c.x, c.bottom - 50, c.width, 48), title, "primary"):
                self.mode = mode
                self.error = ""
        note = ("Confidentialité : seuls un pseudonyme et la progression (semaine, score, réputation) circulent, "
                "uniquement sur le réseau local (connexions hors réseau privé refusées), sans chiffrement : à "
                "réserver à un réseau de confiance (salle de formation). Rien n'est enregistré.")
        R.draw_wrapped(surf, note, pygame.Rect(area.x, area.y + 330, area.width, 80), "small", "text_muted")

    def _pseudo_field(self, ui: UI, x: int, y: int, w: int) -> int:
        R.draw_text(ui.surface, "Votre pseudonyme", (x, y), "small", "accent", "bold")
        self.pseudo = ui.text_input(pygame.Rect(x, y + 22, w, 40), "pseudo", self.pseudo, "ex. Equipe-Bleue", 20)
        return y + 74

    def _heberger(self, ui: UI, area: pygame.Rect) -> None:
        surf = ui.surface
        c = section(surf, area, "Paramètres de la session")
        x, y, w = c.x, c.y, min(760, c.width)
        y = self._pseudo_field(ui, x, y, 360)
        orgs = list(self.app.data.organisations.values())
        org = orgs[self.org_index % len(orgs)]
        R.draw_text(surf, "Organisation", (x, y), "small", "accent", "bold")
        if ui.button(pygame.Rect(x, y + 22, 40, 40), "◀"):
            self.org_index -= 1
        R.panel(surf, pygame.Rect(x + 48, y + 22, 300, 40), "panel_alt")
        R.draw_text_fit(surf, f"{org.type_label} ({org.difficulty_label})", (x + 198, y + 42), 290, "body",
                        anchor="center")
        if ui.button(pygame.Rect(x + 356, y + 22, 40, 40), "▶"):
            self.org_index += 1
        y += 76
        R.draw_text(surf, "Difficulté", (x, y), "small", "accent", "bold")
        bx = x
        for d in DIFFICULTIES.values():
            if ui.button(pygame.Rect(bx, y + 22, 170, 38), d.nom, "selected" if d.id == self.difficulty else "ghost",
                         tooltip=d.description):
                self.difficulty = d.id
            bx += 178
        y += 74
        R.draw_text(surf, "Durée", (x, y), "small", "accent", "bold")
        bx = x
        for years, label in DURATIONS.items():
            if ui.button(pygame.Rect(bx, y + 22, 170, 38), f"{years} an{'s' if years > 1 else ''}",
                         "selected" if years == self.years else "ghost", tooltip=label):
                self.years = years
            bx += 178
        y += 74
        R.draw_text(surf, "Mode", (x, y), "small", "accent", "bold")
        bx = x
        for m in MODES:
            if ui.button(pygame.Rect(bx, y + 22, 350, 38), MODE_LABELS[m], "selected" if m == self.net_mode else "ghost"):
                self.net_mode = m
            bx += 358
        y += 74
        R.draw_text(surf, "Port TCP", (x, y), "small", "accent", "bold")
        self.port = ui.text_input(pygame.Rect(x, y + 22, 160, 40), "port", self.port, str(DEFAULT_PORT), 5, PIN_CHARS)
        ok = bool(self.pseudo.strip())
        if ui.button(pygame.Rect(c.right - 300, c.bottom - 50, 300, 48), "Créer la session", "primary", enabled=ok,
                     tooltip=None if ok else "Saisissez un pseudonyme"):
            self._create()

    def _rejoindre(self, ui: UI, area: pygame.Rect) -> None:
        surf = ui.surface
        left, right = split_h(area, [0.45, 0.55], gap=16)
        c = section(surf, left, "Connexion")
        x, y = c.x, c.y
        y = self._pseudo_field(ui, x, y, c.width)
        R.draw_text(surf, "Adresse IP de l'hôte", (x, y), "small", "accent", "bold")
        self.ip = ui.text_input(pygame.Rect(x, y + 22, c.width - 130, 40), "ip", self.ip, "192.168.1.20", 15, IP_CHARS)
        self.port = ui.text_input(pygame.Rect(c.right - 120, y + 22, 120, 40), "port", self.port, "port", 5, PIN_CHARS)
        y += 74
        R.draw_text(surf, "Code PIN (4 chiffres)", (x, y), "small", "accent", "bold")
        self.pin = ui.text_input(pygame.Rect(x, y + 22, 160, 40), "pin", self.pin, "0000", 4, PIN_CHARS)
        ready = bool(self.pseudo.strip() and self.ip and len(self.pin) == 4 and self.port.isdigit())
        busy = self.join_task is not None
        if ui.button(pygame.Rect(x, c.bottom - 50, c.width, 48), "Connexion…" if busy else "Rejoindre", "primary",
                     enabled=ready and not busy):
            self.error = ""
            self._remember_pseudo()
            self.join_task = join_async(self.ip.strip(), int(self.port), self.pseudo.strip(), self.pin)

        c2 = section(surf, right, "Sessions trouvées sur le réseau")
        if ui.button(pygame.Rect(c2.x, c2.y, 240, 38), "Recherche…" if self.scan else "Rechercher", "secondary",
                     enabled=self.scan is None):
            self.found = []
            self.error = ""
            self.scan = discover_sessions()
        y = c2.y + 50
        if not self.found and self.scan is None:
            R.draw_wrapped(surf, "Aucune session détectée. La découverte automatique peut être bloquée par le pare-feu : "
                                 "saisissez alors l'adresse IP affichée sur l'écran de l'hôte.",
                           pygame.Rect(c2.x, y, c2.width, 60), "small", "text_muted")
        for s in self.found:
            r = pygame.Rect(c2.x, y, c2.width, 56)
            dif = DIFFICULTIES.get(s.difficulty)
            org = self.app.data.organisations.get(s.org_id)
            if ui.button(r, "", "ghost", enabled=not s.started):
                self.ip, self.port = s.host, str(s.port)
            R.draw_text(surf, f"{s.name} — {org.type_label if org else s.org_id}", (r.x + 12, r.y + 6), "body",
                        "text", "bold")
            R.draw_text(surf, f"{s.host}:{s.port} · {dif.nom if dif else s.difficulty} · {s.years} an(s) · "
                              f"{s.mode} · {s.players}/{s.max_players} joueurs" + (" · déjà lancée" if s.started else ""),
                        (r.x + 12, r.y + 32), "small", "text_muted")
            y += 64

    def _attente(self, ui: UI, area: pygame.Rect) -> None:
        surf = ui.surface
        net = self.app.net
        if net is None:
            self.mode = "choix"
            return
        left, right = split_h(area, [0.45, 0.55], gap=16)
        info = net.session_info()
        c = section(surf, left, "Session" + (" (vous êtes l'hôte)" if net.is_host else ""))
        y = c.y
        if net.is_host:
            R.draw_text(surf, "Code PIN à communiquer", (c.x, y), "small", "accent", "bold")
            R.draw_text(surf, net.pin, (c.x, y + 20), 64, "text", "bold")
            y += 100
            R.draw_text(surf, "Adresse(s) de cet ordinateur", (c.x, y), "small", "accent", "bold")
            y += 22
            for ip in self.ips[:3]:
                R.draw_text(surf, f"{ip} : {net.port}", (c.x, y), "h3", "text", "bold")
                y += 30
            y += 10
        if info is not None:
            org = self.app.data.organisations.get(info.org_id)
            dif = DIFFICULTIES.get(info.difficulty)
            for label, value in (("Organisation", org.type_label if org else info.org_id),
                                 ("Difficulté", dif.nom if dif else info.difficulty),
                                 ("Durée", f"{info.years} an(s)"), ("Mode", MODE_LABELS.get(info.mode, info.mode))):
                R.draw_text(surf, label, (c.x, y), "small", "text_muted")
                R.draw_text_fit(surf, value, (c.x + 120, y), c.width - 120, "small", "text", "bold")
                y += 24
        c2 = section(surf, right, "Participants", f"{len(net.players)} connecté(s)")
        y = c2.y
        for p in net.players:
            R.draw_text(surf, ("★ " if p.player_id == 0 else "• ") + p.name, (c2.x, y), "body",
                        "accent" if p.player_id == net.my_id() else "text")
            y += 30
        if net.is_host:
            if ui.button(pygame.Rect(c2.right - 300, c2.bottom - 50, 300, 48), "Lancer la partie", "primary",
                         tooltip="Plus personne ne pourra rejoindre ensuite"):
                params = net.launch()
                self.app.settings["tutorial_done"] = True
                self.app.start_game(params.org_id, params.seed, params.difficulty, params.years)
        else:
            R.draw_text(surf, "En attente du lancement par l'hôte…", (c2.x, c2.bottom - 30), "body", "text_muted")
