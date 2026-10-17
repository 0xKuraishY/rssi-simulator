"""Calendrier simulé : 1 tour = 1 semaine, 156 tours (3 ans)."""
from __future__ import annotations

from datetime import date, timedelta

import config

MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
DAYS_FR = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


class GameCalendar:
    def __init__(self, start: date = config.START_DATE, total_turns: int = config.TOTAL_TURNS,
                 weeks_per_year: int = config.WEEKS_PER_YEAR) -> None:
        self.start = start
        self.total_turns = total_turns
        self.weeks_per_year = weeks_per_year

    def date_for(self, turn: int) -> date:
        """Date du lundi de la semaine ``turn`` (tour 1 = date de début)."""
        return self.start + timedelta(weeks=max(turn, 1) - 1)

    def year_of(self, turn: int) -> int:
        """Année de jeu (1, 2, 3…)."""
        return (max(turn, 1) - 1) // self.weeks_per_year + 1

    def week_of_year(self, turn: int) -> int:
        return (max(turn, 1) - 1) % self.weeks_per_year + 1

    def is_year_start(self, turn: int) -> bool:
        return self.week_of_year(turn) == 1

    def is_year_end(self, turn: int) -> bool:
        return self.week_of_year(turn) == self.weeks_per_year

    def month_of(self, turn: int) -> int:
        return self.date_for(turn).month

    def is_finished(self, turn: int) -> bool:
        return turn > self.total_turns

    def remaining(self, turn: int) -> int:
        return max(0, self.total_turns - turn)

    def turn_for_year_month(self, year: int, month: int) -> int:
        """Premier tour de l'année de jeu ``year`` tombant dans le mois ``month``."""
        first = (year - 1) * self.weeks_per_year + 1
        for t in range(first, first + self.weeks_per_year):
            if self.date_for(t).month == month:
                return t
        return first

    @staticmethod
    def format_date(d: date, with_day: bool = False) -> str:
        base = f"{d.day} {MONTHS_FR[d.month - 1]} {d.year}"
        return f"{DAYS_FR[d.weekday()]} {base}" if with_day else base

    def label(self, turn: int) -> str:
        return f"Semaine {turn}/{self.total_turns} — {self.format_date(self.date_for(turn))}"
