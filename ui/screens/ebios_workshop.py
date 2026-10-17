"""Atelier EBIOS Risk Manager : 5 ateliers jouables, accessibles séquentiellement."""
from __future__ import annotations

import pygame

import config
from engine import renderer as R
from game.organisation import INCIDENT_TYPE_LABELS
from game.risk_engine import RISK_LABELS, TREATMENT_LABELS, Treatment, risk_category
from game.simulation import GameRuleError
from game.state import GameScreen
from ui.components.risk_matrix import MatrixItem, draw_matrix
from ui.components.widgets import UI, section, split_h, split_v
from ui.screens.base import MARGIN, Screen

WORKSHOPS = [
    (1, "Cadrage et socle"),
    (2, "Sources de risque"),
    (3, "Scénarios stratégiques"),
    (4, "Scénarios opérationnels"),
    (5, "Traitement du risque"),
]
HELP = {
    1: "Glissez chaque bien support dans la bonne zone : « primaire » s'il soutient directement une valeur métier "
       "vitale, « secondaire » sinon. Puis passez en revue le socle d'hygiène et marquez jusqu'à 10 écarts prioritaires.",
    2: "Retenez les couples source de risque / objectif visé pertinents pour votre organisation. La pertinence "
       "sectorielle (1-4) s'appuie sur les tendances publiées par l'ANSSI.",
    3: "Associez un couple SR/OV à un chemin d'attaque. La vraisemblance est calculée automatiquement ; vous pouvez "
       "ajuster la position d'un scénario en le faisant glisser dans la matrice (un écart > 1 cran doit être justifié).",
    4: "Chaque scénario stratégique est décliné en modes opératoires (MITRE ATT&CK). Les mesures en place réduisent "
       "la vraisemblance ; la gravité correspond au pire critère DICT.",
    5: "Choisissez une option de traitement pour chaque scénario et sélectionnez des mesures dans la limite du budget. "
       "Comparez la matrice avant / après.",
}
FILTERS = [("tous", "Toutes"), ("pertinents", "Pertinence ≥ 3"), ("retenus", "Retenues")]


class EbiosScreen(Screen):
    name = GameScreen.EBIOS.value

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.tab = 1
        self.filter = "tous"
        self.selected_pair: str | None = None
        self.path_index = 0
        self.selected_op: str | None = None
        self.basket: list[str] = []

    def on_enter(self, **kwargs: object) -> None:
        study = self.sim.risk.study
        self.tab = next((n for n, _ in WORKSHOPS if not study.done[n - 1]), 5)
        self.basket = []

    def _validate(self, n: int) -> None:
        try:
            if n == 5 and self.basket:
                for mid in list(self.basket):
                    self.sim.buy_measure(mid)
                self.basket = []
            score = self.sim.complete_workshop(n)
        except (ValueError, GameRuleError) as exc:
            self.app.toast(str(exc), "warning")
            return
        self.app.audio.play("success")
        self.app.autosave()
        msg = f"Atelier {n} validé — qualité de l'analyse : {score:.0%}."
        if n == 5:
            msg += ("\n\nL'étude EBIOS RM est finalisée : elle satisfait l'exigence d'analyse de risques de NIS2 "
                    "(art. 21) pendant 12 mois. Pensez à la mettre à jour chaque année (cycle opérationnel).")
        self.app.dialogs.info(f"Atelier {n} validé", msg, "success")
        if n < 5:
            self.tab = n + 1

    def draw_content(self, ui: UI) -> None:
        surf = ui.surface
        study = self.sim.risk.study
        y = self.title(ui, "Atelier EBIOS Risk Manager", "Méthode de l'ANSSI — 5 ateliers successifs")
        self.back_button(ui)
        x = MARGIN
        tab_w = (self.size[0] - 2 * MARGIN - 40) // 5
        self.regions["tabs"] = pygame.Rect(MARGIN, y, self.size[0] - 2 * MARGIN, 40)
        for n, label in WORKSHOPS:
            done = study.done[n - 1]
            unlocked = study.unlocked(n)
            style = "selected" if n == self.tab else ("success" if done else "secondary")
            text = f"{n}. {label}" + (" ✓" if done else "")
            if ui.button(pygame.Rect(x, y, tab_w, 40), text, style, enabled=unlocked,
                         tooltip=None if unlocked else "Validez d'abord l'atelier précédent"):
                self.tab = n
            x += tab_w + 10
        if study.complete and ui.button(pygame.Rect(x, y, 30, 40), "↺", "ghost",
                                        tooltip="Relancer une nouvelle étude (mise à jour annuelle)"):
            self.sim.risk.reset_study()
            self.tab = 1
        y += 52
        R.draw_wrapped(surf, HELP[self.tab], pygame.Rect(MARGIN, y, self.size[0] - 2 * MARGIN, 44), "small",
                       "text_muted")
        area = pygame.Rect(MARGIN, y + 48, self.size[0] - 2 * MARGIN, self.size[1] - y - 48 - MARGIN)
        self.regions["workspace"] = area
        getattr(self, f"_w{self.tab}")(ui, area)

    # ======================================================================
    # Atelier 1
    # ======================================================================
    def _w1(self, ui: UI, area: pygame.Rect) -> None:
        surf = ui.surface
        risk = self.sim.risk
        study = risk.study
        left, right = split_h(area, [0.58, 0.42], gap=14)
        c = section(surf, left, "Cartographie des biens supports", "glisser-déposer")
        pool_r, prim_r, sec_r = split_v(c, [0.36, 0.32, 0.32], gap=10)
        zones = [(pool_r, None, "À classer"), (prim_r, "primaire", "Biens supports PRIMAIRES (missions vitales)"),
                 (sec_r, "secondaire", "Biens supports SECONDAIRES")]
        for zr, key, label in zones:
            R.panel(surf, zr, "panel_alt", "border")
            R.draw_text(surf, label, (zr.x + 10, zr.y + 6), "small", "accent" if key else "text_muted", "bold")
            assets = [a for a in self.sim.org.assets_critiques if study.asset_classification.get(a.id) == key]
            cx, cy = zr.x + 10, zr.y + 30
            for a in assets:
                wdt = R.font("small").size(a.nom)[0] + 20
                if cx + wdt > zr.right - 10:
                    cx, cy = zr.x + 10, cy + 34
                chip = pygame.Rect(cx, cy, wdt, 28)
                dragging = ui.drag is not None and ui.drag.key == f"asset:{a.id}"
                pygame.draw.rect(surf, (40, 48, 60) if not dragging else (25, 30, 38), chip, border_radius=6)
                pygame.draw.rect(surf, config.THEME["border"], chip, 1, border_radius=6)
                R.draw_text(surf, a.nom, chip.center, "small", "text", anchor="center")
                d = a.dict_besoins
                ui.tooltip(chip, f"{a.nom} ({a.type}) — besoins D{d.get('D', '?')} I{d.get('I', '?')} "
                                 f"C{d.get('C', '?')} T{d.get('T', '?')}")
                ui.draggable(chip, f"asset:{a.id}", a.id, a.nom)
                cx += wdt + 8
            dropped = ui.drop_target(zr)
            if dropped is not None and str(dropped.key).startswith("asset:"):
                if key is None:
                    study.asset_classification.pop(dropped.payload, None)
                else:
                    risk.classify_asset(dropped.payload, key)
        n_done = len(study.asset_classification)
        n_all = len(self.sim.org.assets_critiques)

        c2 = section(surf, right, "Socle d'hygiène ANSSI (42 mesures)",
                     f"{risk.hygiene_coverage(self.sim.turn):.0%} en place")
        in_place = risk.hygiene_in_place(self.sim.turn)
        list_r = pygame.Rect(c2.x, c2.y, c2.width, c2.height - 60)
        off = ui.begin_scroll("hyg", list_r)
        yy = list_r.y + off
        theme = None
        for i, m in sorted(risk.ref.hygiene.items()):
            if m.theme != theme:
                theme = m.theme
                R.draw_text(surf, theme, (list_r.x, yy + 4), "small", "accent", "bold")
                yy += 24
            ok = i in in_place
            row = pygame.Rect(list_r.x, yy, list_r.width - 10, 24)
            prio = i in study.hygiene_priorities
            mark = "✓" if ok else ("★" if prio else "✗")
            col = config.THEME["success"] if ok else (config.THEME["warning"] if prio else config.THEME["danger"])
            R.draw_text(surf, mark, (row.x + 2, row.y + 3), "small", col, "bold")
            R.draw_text_fit(surf, f"{i}. {m.titre}", (row.x + 22, row.y + 3), row.width - 24, "small",
                            "text" if ok else "text_muted")
            ui.tooltip(row, m.titre + ("" if ok else " — cliquez pour marquer comme écart prioritaire"))
            if not ok and ui.clicked(row):
                risk.toggle_hygiene_priority(i)
            yy += 24
        ui.end_scroll("hyg", list_r, yy - (list_r.y + off))
        R.draw_text_fit(surf, f"Biens classés : {n_done}/{n_all} · écarts prioritaires : "
                              f"{len(study.hygiene_priorities)}/10", (c2.x, c2.bottom - 32), c2.width - 275, "small",
                        "text_muted")
        if ui.button(pygame.Rect(c2.right - 260, c2.bottom - 44, 260, 42), "Valider l'atelier 1", "primary",
                     enabled=n_done == n_all):
            self._validate(1)

    # ======================================================================
    # Atelier 2
    # ======================================================================
    def _w2(self, ui: UI, area: pygame.Rect) -> None:
        surf = ui.surface
        risk = self.sim.risk
        selected = set(risk.study.selected_pairs)
        c = section(surf, area, "Couples sources de risque / objectifs visés",
                    f"{len(selected)} retenus · secteur : {self.sim.org.secteur}")
        x = c.x
        for key, label in FILTERS:
            if ui.button(pygame.Rect(x, c.y, 150, 32), label, "selected" if self.filter == key else "ghost",
                         size="small"):
                self.filter = key
            x += 160
        cols = [("", 40), ("Source de risque", 260), ("Objectif visé", 330), ("Motivation", 110),
                ("Ressources", 110), ("Pertinence secteur", 150)]
        hy = c.y + 44
        cx = c.x
        for label, wdt in cols:
            R.draw_text(surf, label, (cx, hy), "small", "text_muted", "bold")
            cx += wdt
        list_r = pygame.Rect(c.x, hy + 26, c.width, c.height - 140)
        off = ui.begin_scroll("pairs", list_r)
        yy = list_r.y + off
        for sr, ov in risk.all_pairs():
            key = f"{sr.id}:{ov.id}"
            pert = risk.pair_pertinence(sr.id)
            if self.filter == "pertinents" and pert < 3:
                continue
            if self.filter == "retenus" and key not in selected:
                continue
            row = pygame.Rect(list_r.x, yy, list_r.width - 12, 32)
            if ui.hovered(row):
                pygame.draw.rect(surf, (28, 34, 43), row, border_radius=4)
            if ui.checkbox(pygame.Rect(row.x + 6, row.y, 30, 32), key in selected):
                risk.toggle_pair(sr.id, ov.id)
            cx = row.x + 40
            values = [(f"{sr.id} {sr.nom}", 260), (ov.nom, 330), ("●" * sr.motivation, 110), ("●" * sr.ressources, 110)]
            for text, wdt in values:
                R.draw_text(surf, text[: wdt // 8], (cx, row.y + 7), "small", "text")
                cx += wdt
            pcol = [None, config.THEME["text_muted"], config.THEME["accent"], config.THEME["warning"],
                    config.THEME["danger"]][pert]
            R.draw_text(surf, f"{pert}/4", (cx, row.y + 7), "small", pcol, "bold")
            ui.tooltip(pygame.Rect(row.x + 40, row.y, 260, 32), sr.description)
            yy += 34
        ui.end_scroll("pairs", list_r, yy - (list_r.y + off))
        if ui.button(pygame.Rect(c.right - 260, c.bottom - 44, 260, 42), "Valider l'atelier 2", "primary",
                     enabled=bool(selected)):
            self._validate(2)

    # ======================================================================
    # Atelier 3
    # ======================================================================
    def _w3(self, ui: UI, area: pygame.Rect) -> None:
        surf = ui.surface
        risk = self.sim.risk
        left, right = split_h(area, [0.42, 0.58], gap=14)
        c = section(surf, left, "Construire un scénario stratégique")
        R.draw_text(surf, "1. Couple SR/OV retenu", (c.x, c.y), "small", "accent", "bold")
        list_r = pygame.Rect(c.x, c.y + 22, c.width, int(c.height * 0.40))
        off = ui.begin_scroll("w3pairs", list_r)
        yy = list_r.y + off
        for key in risk.study.selected_pairs:
            sr_id, ov_id = key.split(":")
            label = f"{risk.ref.sources[sr_id].nom} → {risk.ref.objectives[ov_id].nom}"
            r = pygame.Rect(list_r.x, yy, list_r.width - 12, 30)
            if ui.button(r, label, "selected" if key == self.selected_pair else "ghost", size="small"):
                self.selected_pair = key
            yy += 34
        ui.end_scroll("w3pairs", list_r, yy - (list_r.y + off))
        y = list_r.bottom + 12
        R.draw_text(surf, "2. Chemin d'attaque", (c.x, y), "small", "accent", "bold")
        paths = list(risk.ref.paths.values())
        path = paths[self.path_index % len(paths)]
        y += 24
        if ui.button(pygame.Rect(c.x, y, 40, 36), "◀"):
            self.path_index -= 1
        R.panel(surf, pygame.Rect(c.x + 48, y, c.width - 96, 36), "panel_alt")
        R.draw_text(surf, path.nom, (c.x + c.width // 2, y + 18), "small", "text", anchor="center")
        if ui.button(pygame.Rect(c.right - 40, y, 40, 36), "▶"):
            self.path_index += 1
        y += 44
        R.draw_text(surf, f"Vecteur : {path.vecteur} · exposition de l'organisation : "
                          f"{self.sim.org.exposition.get(path.vecteur, 2)}/4", (c.x, y), "small", "text_muted")
        y += 24
        if self.selected_pair:
            sr_id, ov_id = self.selected_pair.split(":")
            types = risk.scenario_types(ov_id, path.id)
            v = risk.strategic_likelihood(sr_id, path.id)
            g = risk.strategic_severity(types)
            labels = ", ".join(INCIDENT_TYPE_LABELS[t] for t in types) or "aucun type applicable"
            y += R.draw_wrapped(surf, f"Calcul : V{v} × G{g} = {v * g} — menaces : {labels}",
                                pygame.Rect(c.x, y, c.width, 60), "small", "text")
        if ui.button(pygame.Rect(c.x, c.bottom - 98, c.width, 42), "Ajouter le scénario", "secondary",
                     enabled=self.selected_pair is not None):
            s = risk.add_strategic_scenario(self.selected_pair, path.id)
            self.app.toast(f"{s.id} ajouté (V{s.likelihood} × G{s.severity})", "success")
        if ui.button(pygame.Rect(c.x, c.bottom - 46, c.width, 42), "Valider l'atelier 3", "primary",
                     enabled=bool(risk.study.strategic)):
            self._validate(3)

        c2 = section(surf, right, "Matrice stratégique 4×4", f"{len(risk.study.strategic)} scénarios")
        items = []
        for s in risk.study.strategic:
            tip = (f"{s.id} : {risk.ref.sources[s.sr_id].nom} / {risk.ref.objectives[s.ov_id].nom} via "
                   f"{risk.ref.paths[s.path_id].nom}. Calcul V{s.likelihood_calc}×G{s.severity_calc}"
                   + (" — position ajustée" if s.deviation else ""))
            items.append(MatrixItem(s.id, s.id, s.likelihood, s.severity, tip))
        mrect = pygame.Rect(c2.x, c2.y, c2.width, c2.height - 50)
        moved = draw_matrix(ui, mrect, items, draggable=True)
        if moved:
            key, v, g = moved
            s = risk.adjust_strategic(key, v, g)
            if s.deviation > 1:
                self.app.toast("Écart important avec le calcul : il devra être justifié.", "warning")
        if risk.study.strategic:
            last = risk.study.strategic[-1]
            if ui.button(pygame.Rect(c2.x, c2.bottom - 40, 260, 36), f"Retirer {last.id}", "ghost", size="small"):
                risk.remove_strategic_scenario(last.id)

    # ======================================================================
    # Atelier 4
    # ======================================================================
    def _w4(self, ui: UI, area: pygame.Rect) -> None:
        surf = ui.surface
        risk = self.sim.risk
        ops = risk.study.operational or risk.generate_operational(self.sim.turn)
        left, right = split_h(area, [0.52, 0.48], gap=14)
        c = section(surf, left, "Scénarios opérationnels", f"{len(ops)} modes opératoires")
        list_r = pygame.Rect(c.x, c.y, c.width, c.height - 54)
        off = ui.begin_scroll("ops", list_r)
        yy = list_r.y + off
        for op in ops:
            r = pygame.Rect(list_r.x, yy, list_r.width - 12, 40)
            cat = op.category
            if ui.button(r, "", "selected" if op.id == self.selected_op else "ghost"):
                self.selected_op = op.id
            pygame.draw.rect(surf, config.RISK_COLORS[cat], (r.x, r.y, 6, r.height), border_radius=3)
            R.draw_text_fit(surf, f"{op.strategic_id} · {INCIDENT_TYPE_LABELS[op.incident_type]}", (r.x + 14, r.y + 4),
                            r.width - 20, "small", "text", "bold")
            R.draw_text(surf, f"V{op.likelihood_base}→V{op.likelihood} × G{op.severity} = {op.score} "
                              f"({RISK_LABELS[cat]})", (r.x + 14, r.y + 22), 11, "text_muted")
            yy += 46
        ui.end_scroll("ops", list_r, yy - (list_r.y + off))
        if ui.button(pygame.Rect(c.right - 260, c.bottom - 44, 260, 42), "Valider l'atelier 4", "primary",
                     enabled=bool(ops)):
            self._validate(4)

        top, bottom = split_v(right, [0.48, 0.52], gap=12)
        c2 = section(surf, top, "Matrice opérationnelle")
        draw_matrix(ui, c2, [MatrixItem(o.id, o.id.split("-")[0], o.likelihood, o.severity,
                                        f"{o.id} — {INCIDENT_TYPE_LABELS[o.incident_type]}") for o in ops], compact=True)
        c3 = section(surf, bottom, "Mode opératoire MITRE ATT&CK")
        op = next((o for o in ops if o.id == self.selected_op), ops[0] if ops else None)
        if op is None:
            return
        d = op.impact
        R.draw_text(surf, f"Impact DICT : D{d.get('D', 1)} I{d.get('I', 1)} C{d.get('C', 1)} T{d.get('T', 1)} "
                          f"→ gravité G{max(d.values()) if d else 1} (pire critère)", (c3.x, c3.y), "small", "text")
        red = risk.reduction(op.incident_type, self.sim.turn)
        R.draw_text(surf, f"Réduction par les mesures en place : {red:.0%}", (c3.x, c3.y + 22), "small", "text_muted")
        off = ui.begin_scroll("mitre", pygame.Rect(c3.x, c3.y + 48, c3.width, c3.height - 48))
        yy = c3.y + 48 + off
        for i, tid in enumerate(op.techniques):
            tech = self.sim.data.mitre.get(tid, {})
            R.draw_text(surf, f"{i + 1}. {tid}", (c3.x, yy), "small", "accent", "bold")
            R.draw_text(surf, f"{tech.get('nom', '?')} — {tech.get('tactique', '')}", (c3.x + 110, yy), "small", "text")
            yy += 22
        ui.end_scroll("mitre", pygame.Rect(c3.x, c3.y + 48, c3.width, c3.height - 48), yy - (c3.y + 48 + off))

    # ======================================================================
    # Atelier 5
    # ======================================================================
    def _w5(self, ui: UI, area: pygame.Rect) -> None:
        surf = ui.surface
        sim = self.sim
        risk = sim.risk
        ops = risk.study.operational
        col1, col2, col3 = split_h(area, [0.36, 0.32, 0.32], gap=14)

        c = section(surf, col1, "Options de traitement")
        list_r = pygame.Rect(c.x, c.y, c.width, c.height)
        off = ui.begin_scroll("treat", list_r)
        yy = list_r.y + off
        for op in ops:
            cat = op.category
            pygame.draw.rect(surf, config.RISK_COLORS[cat], (list_r.x, yy, 5, 58), border_radius=2)
            R.draw_text_fit(surf, f"{op.strategic_id} · {INCIDENT_TYPE_LABELS[op.incident_type]} — risque {op.score}",
                            (list_r.x + 12, yy), list_r.width - 30, "small", "text", "bold")
            bx = list_r.x + 12
            bw = (list_r.width - 30) // 4
            for opt in Treatment:
                sel = risk.study.treatments.get(op.id) == opt.value
                if ui.button(pygame.Rect(bx, yy + 22, bw - 4, 30), TREATMENT_LABELS[opt.value],
                             "selected" if sel else "ghost", size="small"):
                    risk.set_treatment(op.id, opt.value)
                bx += bw
            yy += 66
        ui.end_scroll("treat", list_r, yy - (list_r.y + off))

        c2 = section(surf, col2, "Mesures envisagées", f"budget restant {R.format_eur(sim.budget.remaining)}")
        relevant_types = {o.incident_type for o in ops if risk.study.treatments.get(o.id) == Treatment.REDUIRE.value} \
            or {o.incident_type for o in ops}
        candidates = [m for m in sim.data.measures.values() if not sim.portfolio.has(m.id)
                      and (any(m.reduction_for(t) or m.impact_reduction_for(t) for t in relevant_types)
                           or (m.assurance and any(v == Treatment.TRANSFERER.value
                                                   for v in risk.study.treatments.values())))]
        priorities = set(risk.study.hygiene_priorities)
        candidates.sort(key=lambda m: (not (set(m.hygiene) & priorities), -sum(m.reduction_for(t) for t in relevant_types)))
        basket_cost = sum(sim.measure_costs(sim.data.measures[mid])[0] for mid in self.basket)
        list_r = pygame.Rect(c2.x, c2.y, c2.width, c2.height - 100)
        off = ui.begin_scroll("w5m", list_r)
        yy = list_r.y + off
        for m in candidates:
            cost, annual = sim.measure_costs(m)
            in_basket = m.id in self.basket
            affordable = in_basket or basket_cost + cost <= sim.budget.remaining
            row = pygame.Rect(list_r.x, yy, list_r.width - 12, 44)
            if ui.checkbox(pygame.Rect(row.x, row.y, 26, 44), in_basket, enabled=affordable):
                if in_basket:
                    self.basket.remove(m.id)
                elif affordable:
                    self.basket.append(m.id)
            star = "★ " if set(m.hygiene) & priorities else ""
            R.draw_text_fit(surf, star + m.nom, (row.x + 30, row.y + 3), row.width - 34, "small",
                            "text" if affordable else "text_muted", "bold" if star else "regular")
            R.draw_text(surf, f"{R.format_eur(cost)} · {m.delai_semaines} sem. · maint. {R.format_eur(annual)}/an",
                        (row.x + 30, row.y + 22), 11, "text_muted")
            ui.tooltip(row, f"{m.description} ({m.guide_anssi})")
            yy += 48
        ui.end_scroll("w5m", list_r, yy - (list_r.y + off))
        over = basket_cost > sim.budget.remaining
        R.draw_text(surf, f"Sélection : {R.format_eur(basket_cost)}", (c2.x, c2.bottom - 92), "body",
                    "danger" if over else "text", "bold")
        R.draw_text(surf, "★ = couvre un écart prioritaire de l'atelier 1", (c2.x, c2.bottom - 66), 11, "text_muted")
        missing = [o.id for o in ops if o.id not in risk.study.treatments]
        if ui.button(pygame.Rect(c2.x, c2.bottom - 44, c2.width, 42), "Valider et commander", "primary",
                     enabled=not missing and not over,
                     tooltip=f"Traitement manquant : {', '.join(missing[:4])}" if missing else None):
            self._validate(5)

        c3 = section(surf, col3, "Avant / après")
        sim_res = risk.simulate_treatment(sim.turn, [sim.data.measures[mid] for mid in self.basket])
        top, bottom = split_v(pygame.Rect(c3.x, c3.y, c3.width, c3.height - 50), [1, 1], gap=10)
        draw_matrix(ui, top, [MatrixItem(o.id, o.id.split("-")[0], o.likelihood, o.severity) for o in sim_res["before"]],
                    compact=True, title=f"Avant — max {sim_res['before_max']} ({RISK_LABELS[risk_category(max(1, sim_res['before_max']))]})")
        draw_matrix(ui, bottom, [MatrixItem(o.id, o.id.split("-")[0], o.likelihood, o.severity) for o in sim_res["after"]],
                    compact=True, title=f"Après — max {sim_res['after_max']} ({RISK_LABELS[risk_category(max(1, sim_res['after_max']))]})")
        R.draw_text(surf, f"Risque moyen : {sim_res['before_avg']:.1f} → {sim_res['after_avg']:.1f}",
                    (c3.x, c3.bottom - 30), "body", "success" if sim_res["after_avg"] < sim_res["before_avg"] else "text",
                    "bold")
