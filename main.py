"""RSSI Simulator — point d'entrée.

Exemples :
    python main.py                                   # jeu graphique
    python main.py --scenario hopital --seed 42      # démarre directement une partie
    python main.py --headless --scenario mairie      # partie automatique sans affichage (CI)
"""
from __future__ import annotations

import logging
import sys

import click

import config


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--headless", is_flag=True, help="Sans affichage : partie jouée automatiquement (CI/CD, calibrage).")
@click.option("--scenario", type=str, default=None, help="Identifiant d'organisation : hopital, mairie, "
                                                          "pme_industrie, esn, telecom.")
@click.option("--lang", type=click.Choice(config.SUPPORTED_LANGS), default=config.DEFAULT_LANG, show_default=True,
              help="Langue de l'interface.")
@click.option("--seed", type=int, default=None, help="Graine aléatoire (partie reproductible).")
@click.option("--difficulty", type=click.Choice(["decouverte", "standard", "expert", "crise"]), default=None,
              help="Niveau de difficulté (défaut : préférence enregistrée, sinon standard).")
@click.option("--years", type=click.IntRange(1, 3), default=None, help="Durée du mandat en années (1 à 3).")
@click.option("--strategy", type=click.Choice(["expert", "moyen", "novice"]), default="expert", show_default=True,
              help="Stratégie du joueur automatique (mode --headless).")
@click.option("--report/--no-report", default=True, show_default=True, help="Générer le rapport HTML (--headless).")
@click.option("--resolution", type=str, default=None, help="Résolution LARGEURxHAUTEUR (min. 1280x720).")
@click.option("--fullscreen/--windowed", default=None, help="Plein écran ou fenêtré.")
@click.option("--frames", type=int, default=None, hidden=True, help="Nombre d'images avant arrêt (tests).")
@click.option("-v", "--verbose", is_flag=True, help="Journalisation détaillée.")
def cli(headless: bool, scenario: str | None, lang: str, seed: int | None, difficulty: str | None,
        years: int | None, strategy: str, report: bool, resolution: str | None, fullscreen: bool | None,
        frames: int | None, verbose: bool) -> None:
    """RSSI Simulator : incarnez le RSSI d'une organisation française pendant 3 ans."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    from game.data_loader import get_data

    data = get_data()
    if scenario is not None and scenario not in data.organisations:
        raise click.BadParameter(f"choisir parmi {', '.join(data.organisations)}", param_hint="--scenario")

    if headless:
        config.enable_headless()
        if frames is not None:
            _run_ui(scenario, seed, None, None, True, frames, difficulty, years)
            return
        _run_headless(scenario or "hopital", seed, strategy, report, difficulty or "standard", years or 3)
        return
    size = None  # adaptée à l'écran
    if resolution:
        try:
            w, h = (int(x) for x in resolution.lower().split("x"))
            if not (0 < w <= 7680 and 0 < h <= 4320):
                raise ValueError(resolution)
            size = (w, h)
        except ValueError as exc:
            raise click.BadParameter("format attendu : 1920x1080", param_hint="--resolution") from exc
    _run_ui(scenario, seed, size, fullscreen, False, frames, difficulty, years)


def _run_ui(scenario: str | None, seed: int | None, size: tuple[int, int] | None, fullscreen: bool | None,
            headless: bool, frames: int | None, difficulty: str | None = None, years: int | None = None) -> None:
    from engine.game_loop import GameApp

    app = GameApp(size=size, headless=headless, seed=seed, fullscreen=fullscreen)
    if difficulty:
        app.settings["difficulty"] = difficulty
    if years:
        app.settings["years"] = years
    if scenario:
        app.start_game(scenario, seed)
    app.run(max_frames=frames)


def _run_headless(scenario: str, seed: int | None, strategy: str, report: bool, difficulty: str = "standard",
                  years: int = 3) -> None:
    from game.autoplay import play
    from game.report import generate_report
    from game.scoring import compute_score
    from game.simulation import new_game

    sim = play(new_game(scenario, seed, difficulty=difficulty, years=years), strategy, seed or 0)
    card = compute_score(sim)
    click.echo(f"Organisation : {sim.org.nom} — difficulté {sim.difficulty.nom}, {sim.years} an(s) — graine {sim.seed}")
    click.echo(f"Fin : {sim.game_over_reason}")
    click.echo(f"Incidents : {len(sim.incidents.incidents)} · coût net {sim.budget.cout_incident_cumule:,.0f} € · "
               f"sanctions {sim.budget.amendes_cumulees:,.0f} €")
    click.echo(f"Score : {card.total:.1f}/100 ({card.grade}, {card.percentile}e percentile)")
    if report:
        path = generate_report(sim)
        click.echo(f"Rapport : {path}")


if __name__ == "__main__":
    sys.exit(cli())
