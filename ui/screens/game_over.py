"""Écran de fin de partie : score, percentile, meilleures décisions, erreurs critiques, rapport HTML."""
from __future__ import annotations

import webbrowser

import pygame

import config
from engine import renderer as R
from game.governance import OBJECTIVE_STATUS_LABELS, OBJECTIVES
from game.report import generate_report
from game.scoring import WEIGHT_LABELS, WEIGHTS, ScoreCard, compute_score
from game.state import GameScreen
from ui.components.widgets import UI, section, split_h, split_v
from ui.screens.base import Screen

GRADE_COLORS = {"Insuffisant": config.THEME["danger"], "Moyen": config.THEME["warning"],
                "Bon": config.THEME["accent"], "Expert": config.THEME["success"]}


class GameOverScreen(Screen):
    name = GameScreen.GAME_OVER.value

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.card: ScoreCard | None = None
        self.report_path = None

    def on_enter(self, **kwargs: object) -> None:
        if not self.sim.finished:
            self.sim.abandon()
        self.card = compute_score(self.sim)
        self.report_path = None
        self.app.autosave()

    def draw_content(self, ui: UI) -> None:
        surf = ui.surface
        sim = self.sim
        card = self.card or compute_score(sim)
        y = self.title(ui, "Fin de mandat", sim.game_over_reason or "")
        area = pygame.Rect(16, y, self.size[0] - 32, self.size[1] - y - 80)
        left, mid, right = split_h(area, [0.30, 0.35, 0.35], gap=14)

        c = section(surf, left, "Évaluation globale")
        col = GRADE_COLORS.get(card.grade, config.THEME["text"])
        R.draw_text(surf, f"{card.total:.0f}", (c.centerx, c.y + 10), 96, col, "bold", anchor="midtop")
        R.draw_text(surf, "/ 100", (c.centerx, c.y + 120), "h3", "text_muted", anchor="midtop")
        R.draw_text(surf, card.grade, (c.centerx, c.y + 156), "h2", col, "bold", anchor="midtop")
        R.draw_text(surf, f"{card.percentile}e percentile de la distribution de référence", (c.centerx, c.y + 196),
                    "small", "text_muted", anchor="midtop")
        yy = c.y + 236
        for key, weight in WEIGHTS.items():
            v = card.components[key]
            R.draw_text(surf, f"{WEIGHT_LABELS[key]} ({weight:.0%})", (c.x, yy), "small", "text")
            R.draw_text(surf, f"{v:.0%}", (c.right, yy), "small", "text", "bold", anchor="topright")
            ui.progress(pygame.Rect(c.x, yy + 20, c.width, 8), v)
            yy += 38
        yy += 6
        stats = [(OBJECTIVES[o["id"]].titre, OBJECTIVE_STATUS_LABELS[o["status"]]) for o in sim.objectives]
        stats += [
            ("Incidents subis", str(len(sim.incidents.incidents))),
            ("Pertes (incidents + sanctions)", R.format_eur(sim.budget.cout_incident_cumule + sim.budget.amendes_cumulees)),
            ("Confiance de la direction", f"{sim.trust:.0f}/100"),
            ("Difficulté", f"{sim.difficulty.nom} · {sim.years} an(s)"),
        ]
        for label, value in stats:
            if yy + 20 > c.bottom:
                break
            R.draw_text(surf, label, (c.x, yy), "small", "text_muted")
            R.draw_text(surf, value, (c.right, yy), "small", "text", "bold", anchor="topright")
            yy += 22

        if self.app.net is not None:
            mid, board_r = split_v(mid, [0.55, 0.45], gap=10)
            cb = section(surf, board_r, "Classement de la session")
            by = cb.y
            for rank, p in enumerate(self.app.net.leaderboard()[:6], 1):
                col = "accent" if p.player_id == self.app.net.my_id() else "text"
                R.draw_text_fit(surf, f"{rank}. {p.name}" + ("" if p.finished else f" (sem. {p.turn})"), (cb.x, by),
                                cb.width - 80, "body", col)
                R.draw_text(surf, f"{p.score:.0f}", (cb.right, by), "body", col, "bold", anchor="topright")
                by += 26
        c2 = section(surf, mid, "Vos 3 meilleures décisions")
        yy = c2.y
        if not card.best_decisions:
            R.draw_text(surf, "Aucune décision remarquable enregistrée.", (c2.x, yy), "small", "text_muted")
        for i, d in enumerate(card.best_decisions, 1):
            R.draw_text_fit(surf, f"{i}. {d.source_title}", (c2.x, yy), c2.width, "small", "success", "bold")
            yy += 22
            yy += R.draw_wrapped(surf, d.choice, pygame.Rect(c2.x, yy, c2.width, 60), "small", "text", "bold") + 2
            yy += R.draw_wrapped(surf, d.feedback, pygame.Rect(c2.x, yy, c2.width, 90), "small", "text_muted",
                                 line_spacing=1) + 14

        c3 = section(surf, right, "3 erreurs critiques à retenir")
        yy = c3.y
        if not card.worst_mistakes:
            R.draw_text(surf, "Aucune erreur critique : remarquable.", (c3.x, yy), "small", "success")
        for i, m in enumerate(card.worst_mistakes, 1):
            R.draw_text_fit(surf, f"{i}. {m.title}", (c3.x, yy), c3.width, "small", "danger", "bold")
            yy += 22
            yy += R.draw_wrapped(surf, m.explanation, pygame.Rect(c3.x, yy, c3.width, 100), "small", "text",
                                 line_spacing=1) + 2
            yy += R.draw_wrapped(surf, "Référence : " + m.reference, pygame.Rect(c3.x, yy, c3.width, 40), 11, "accent") + 14

        w, h = self.size
        if ui.button(pygame.Rect(16, h - 66, 280, 48), "Menu principal", "ghost"):
            self.app.leave_network()
            self.app.switch(GameScreen.MENU)
        if ui.button(pygame.Rect(w - 356, h - 66, 340, 48), "Générer le rapport HTML", "primary"):
            self.report_path = generate_report(sim)
            self.app.toast("Rapport généré", "success")
        if self.report_path is not None:
            R.draw_text(surf, str(self.report_path), (310, h - 54), "small", "text_muted")
            if ui.button(pygame.Rect(w - 576, h - 66, 210, 48), "Ouvrir le rapport", "secondary"):
                webbrowser.open(self.report_path.as_uri())  # fichier local uniquement
