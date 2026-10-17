"""Gestion budgétaire : répartition, catalogue filtrable, simulateur de ROI, historique."""
from __future__ import annotations

import pygame

import config
from engine import renderer as R
from game.organisation import INCIDENT_TYPE_LABELS
from game.simulation import GameRuleError
from game.state import GameScreen
from ui.components.risk_matrix import MatrixItem, draw_matrix
from ui.components.widgets import UI, section, split_h, split_v
from ui.screens.base import Screen

CATEGORY_LABELS = {"outils": "Outils", "formation": "Formation", "audit": "Audit", "assurance": "Assurance",
                   "externalisation": "Externalisation", "divers": "Divers"}
TYPE_FILTERS = [("tous", "Toutes"), ("prevention", "Prévention"), ("detection", "Détection"),
                ("reponse", "Réponse"), ("gouvernance", "Gouvernance")]
SORTS = [("roi", "ROI"), ("cout", "Coût"), ("delai", "Délai")]
SHORT = {"ransomware": "RAN", "phishing": "PHI", "fuite_donnees": "FUI", "supply_chain": "SUP", "vpn_exploit": "VPN",
         "ddos": "DDS", "initie": "INI", "double_extorsion": "DBX", "compromission_cloud": "CLD", "ot_iot": "OT"}


class BudgetScreen(Screen):
    name = GameScreen.BUDGET.value

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.filter = "tous"
        self.sort = "roi"
        self.selected: str | None = None
        self._roi_cache: dict[str, dict] = {}
        self._cache_turn = -1

    def on_enter(self, **kwargs: object) -> None:
        self._roi_cache = {}

    def _roi(self, mid: str) -> dict:
        key = f"{mid}:{self.sim.turn}:{len(self.sim.portfolio.items)}"
        if key not in self._roi_cache:
            self._roi_cache[key] = self.sim.measure_roi(mid)
        return self._roi_cache[key]

    def draw_content(self, ui: UI) -> None:
        y = self.title(ui, "Budget SSI", f"Exercice {self.sim.year} — {R.format_eur(self.sim.budget.budget_annuel_ssi)}")
        self.back_button(ui)
        area = pygame.Rect(16, y, self.size[0] - 32, self.size[1] - y - 16)
        left, mid, right = split_h(area, [0.27, 0.40, 0.33], gap=14)
        top, bottom = split_v(left, [0.55, 0.45], gap=12)
        self.regions.update(categories=top, catalogue=mid, simulator=right)
        self._categories(ui, top)
        self._history(ui, bottom)
        self._catalogue(ui, mid)
        self._simulator(ui, right)

    def _categories(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        b = self.sim.budget
        c = section(surf, rect, "Répartition", f"dépensé {R.format_eur(b.spent)}")
        max_v = max(max(v["alloue"], v["depense"]) for v in b.categories.values()) or 1
        row_h = (c.height - 70) // len(b.categories)
        y = c.y
        for cat, v in b.categories.items():
            R.draw_text(surf, CATEGORY_LABELS[cat], (c.x, y), "small", "text")
            R.draw_text(surf, f"{R.format_eur(v['depense'])} / {R.format_eur(v['alloue'])}", (c.right, y), "small",
                        "text_muted", anchor="topright")
            bar = pygame.Rect(c.x, y + 20, c.width, max(8, row_h - 30))
            pygame.draw.rect(surf, config.THEME["panel_alt"], (bar.x, bar.y, int(bar.width * v["alloue"] / max_v), bar.height),
                             border_radius=3)
            pygame.draw.rect(surf, config.THEME["accent"], (bar.x, bar.y, int(bar.width * v["depense"] / max_v), bar.height),
                             border_radius=3)
            y += row_h
        R.draw_wrapped(surf, f"Coûts d'incident cumulés : {R.format_eur(b.cout_incident_cumule)} · "
                             f"Sanctions : {R.format_eur(b.amendes_cumulees)} (hors budget SSI)",
                       pygame.Rect(c.x, c.bottom - 44, c.width, 44), "small", "text_muted")

    def _history(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        c = section(surf, rect, "Dépenses — 12 dernières semaines")
        data = self.sim.budget.weekly_spending(self.sim.turn, 12)
        max_v = max((v for _, v in data), default=0) or 1
        bw = c.width // max(1, len(data))
        for i, (t, v) in enumerate(data):
            h = int((c.height - 30) * v / max_v)
            r = pygame.Rect(c.x + i * bw + 2, c.bottom - 22 - h, bw - 4, h)
            pygame.draw.rect(surf, config.THEME["accent"], r, border_radius=2)
            R.draw_text(surf, str(t), (r.centerx, c.bottom - 18), 11, "text_muted", anchor="midtop")
            ui.tooltip(pygame.Rect(r.x, c.y, r.width, c.height), f"Semaine {t} : {R.format_eur(v)}")

    def _catalogue(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        c = section(surf, rect, "Catalogue de mesures", f"{len(sim.data.measures)} mesures")
        x = c.x
        fw = (c.width - 8) // len(TYPE_FILTERS)
        for key, label in TYPE_FILTERS:
            if ui.button(pygame.Rect(x, c.y, fw - 6, 30), label, "selected" if self.filter == key else "ghost",
                         size="small"):
                self.filter = key
            x += fw
        x = c.x
        R.draw_text(surf, "Trier par :", (x, c.y + 44), "small", "text_muted")
        x += 90
        for key, label in SORTS:
            if ui.button(pygame.Rect(x, c.y + 38, 90, 28), label, "selected" if self.sort == key else "ghost",
                         size="small"):
                self.sort = key
            x += 96
        measures = [m for m in sim.data.measures.values() if self.filter == "tous" or m.type == self.filter]
        if self.sort == "roi":
            measures.sort(key=lambda m: -self._roi(m.id)["roi"])
        elif self.sort == "cout":
            measures.sort(key=lambda m: sim.measure_costs(m)[0])
        else:
            measures.sort(key=lambda m: m.delai_semaines)
        list_r = pygame.Rect(c.x, c.y + 76, c.width, c.height - 76)
        off = ui.begin_scroll("catalogue", list_r)
        yy = list_r.y + off
        for m in measures:
            row = pygame.Rect(list_r.x, yy, list_r.width - 12, 50)
            owned = sim.portfolio.has(m.id)
            if ui.button(row, "", "selected" if m.id == self.selected else "ghost"):
                self.selected = m.id
            cost, annual = sim.measure_costs(m)
            roi = self._roi(m.id)["roi"]
            R.draw_text_fit(surf, m.nom, (row.x + 10, row.y + 5), row.width - 130, "small",
                            "text_muted" if owned else "text", "bold")
            status = "en place" if owned and sim.portfolio.items[m.id].is_active(sim.turn) else \
                "en déploiement" if owned else f"ROI {roi:.1f}"
            R.draw_text(surf, f"{m.id} · {R.format_eur(cost)} · {m.delai_semaines} sem. · {m.type}",
                        (row.x + 10, row.y + 27), 11, "text_muted")
            col = config.THEME["success"] if (not owned and roi > 1) else config.THEME["text_muted"]
            R.draw_text(surf, status, (row.right - 10, row.y + 16), "small", col, "bold", anchor="topright")
            yy += 54
        ui.end_scroll("catalogue", list_r, yy - (list_r.y + off))

    def _simulator(self, ui: UI, rect: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        c = section(surf, rect, "Simulateur de ROI")
        if self.selected is None:
            R.draw_wrapped(surf, "Sélectionnez une mesure dans le catalogue pour voir son effet sur le risque et le "
                                 "coût espéré évité.\n\nROI = (fréquence × coût moyen d'incident × coefficient de "
                                 "réduction) / coût annuel de la mesure. Une mesure est rentable si ROI > 1.",
                           c, "body", "text_muted")
            return
        m = sim.data.measures[self.selected]
        res = self._roi(m.id)
        y = c.y
        y += R.draw_wrapped(surf, m.nom, pygame.Rect(c.x, y, c.width, 50), "body", "text", "bold") + 4
        y += R.draw_wrapped(surf, m.description, pygame.Rect(c.x, y, c.width, 70), "small", "text_muted",
                            line_spacing=1) + 6
        deploy, annual = sim.measure_costs(m)
        R.draw_text(surf, f"Déploiement {R.format_eur(deploy)} · maintenance {R.format_eur(annual)}/an",
                    (c.x, y), "small", "text")
        y += 20
        R.draw_text(surf, f"ISO 27001 : {', '.join(m.controle_iso)} · Hygiène ANSSI : "
                          f"{', '.join(map(str, m.hygiene)) or '—'}", (c.x, y), 11, "text_muted")
        y += 22
        roi_col = config.THEME["success"] if res["rentable"] else config.THEME["warning"]
        R.draw_text(surf, f"ROI = {R.format_eur(res['cout_evite'])} / {R.format_eur(res['cout_annuel'])} = "
                          f"{res['roi']:.2f}", (c.x, y), "body", roi_col, "bold")
        y += 26
        for line in sorted(res["detail"], key=lambda d: -d["evite"])[:4]:
            R.draw_text_fit(surf, f"{INCIDENT_TYPE_LABELS[line['type']]} : {line['freq']:.0%}/an × "
                                  f"{R.format_eur(line['cout_moyen'])} × {line['coeff']:.0%} = "
                                  f"{R.format_eur(line['evite'])}", (c.x, y), c.width, 11, "text_muted", min_size=9)
            y += 17
        y += 6
        mh = c.bottom - y - 60
        if mh > 120:
            left, right = split_h(pygame.Rect(c.x, y, c.width, mh), [1, 1], gap=10)
            draw_matrix(ui, left, [MatrixItem(t, SHORT[t], v, g) for t, (v, g) in res["risk_before"].items()],
                        compact=True, title="Avant")
            draw_matrix(ui, right, [MatrixItem(t, SHORT[t], v, g) for t, (v, g) in res["risk_after"].items()],
                        compact=True, title="Après")
        ok, reason = sim.measure_availability(m.id)
        if ui.button(pygame.Rect(c.x, c.bottom - 46, c.width, 44), "Commander cette mesure" if ok else reason,
                     "primary", enabled=ok):
            try:
                sim.buy_measure(m.id)
                self.app.audio.play("success")
                self.app.toast(f"Commande : {m.nom}", "success")
                self.app.autosave()
            except GameRuleError as exc:
                self.app.toast(str(exc), "danger")
