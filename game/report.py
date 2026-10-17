"""Rapport HTML statique de fin de partie (dossier apprenant).

Le fichier est autonome : aucune ressource externe (polices, scripts, images),
ce qui garantit l'absence de requête réseau à l'ouverture.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

import config
from game.compliance_engine import OBLIGATIONS
from game.governance import OBJECTIVE_STATUS_LABELS, OBJECTIVES, objective_text
from game.organisation import INCIDENT_TYPE_LABELS
from game.risk_engine import RISK_LABELS, risk_category
from game.scoring import WEIGHT_LABELS, WEIGHTS, compute_score

if TYPE_CHECKING:
    from game.simulation import Simulation

CSS = """
:root{--bg:#0e1117;--panel:#161b22;--border:#30384a;--text:#e6e9ed;--muted:#8b949e;
--accent:#388bfd;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--crit:#be1e2d}
@media (prefers-color-scheme: light){:root{--bg:#ffffff;--panel:#f6f8fa;--border:#d0d7de;
--text:#1f2328;--muted:#57606a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.55 "DejaVu Sans",system-ui,sans-serif}main{max-width:1000px;margin:auto;padding:24px 16px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;border-bottom:1px solid var(--border);padding-bottom:6px;margin-top:36px}
.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px}
.big{font-size:40px;font-weight:700}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--muted);font-weight:600}.q-bonne{color:var(--ok)}.q-moyenne{color:var(--warn)}.q-mauvaise{color:var(--bad)}
.bar{height:10px;background:var(--border);border-radius:5px;overflow:hidden}.bar>i{display:block;height:100%;background:var(--accent)}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;border:1px solid var(--border)}
.risk-faible{background:#3fb95033}.risk-modere{background:#d2992233}.risk-eleve{background:#e6642833}.risk-critique{background:#be1e2d44}
footer{margin-top:40px;font-size:12px;color:var(--muted)}
@media print{body{background:#fff;color:#000}.card{border-color:#999}}
"""


def _eur(x: float) -> str:
    return f"{round(x):,} €".replace(",", " ")


def _sparkline(points: list[tuple[int, float]], width: int = 900, height: int = 160) -> str:
    if len(points) < 2:
        return "<p class='muted'>Historique insuffisant.</p>"
    max_t = max(t for t, _ in points)
    min_t = min(t for t, _ in points)
    span = max(1, max_t - min_t)
    pts = " ".join(f"{(t - min_t) / span * (width - 40) + 30:.1f},{height - 20 - v / 100 * (height - 30):.1f}"
                   for t, v in points)
    y20 = height - 20 - 0.20 * (height - 30)
    y40 = height - 20 - 0.40 * (height - 30)
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
            f'aria-label="Évolution de la réputation globale">'
            f'<line x1="30" x2="{width - 10}" y1="{y40:.1f}" y2="{y40:.1f}" stroke="#d29922" stroke-dasharray="4"/>'
            f'<line x1="30" x2="{width - 10}" y1="{y20:.1f}" y2="{y20:.1f}" stroke="#f85149" stroke-dasharray="4"/>'
            f'<text x="0" y="{y40 + 4:.1f}" fill="currentColor" font-size="11">40</text>'
            f'<text x="0" y="{y20 + 4:.1f}" fill="currentColor" font-size="11">20</text>'
            f'<polyline fill="none" stroke="#388bfd" stroke-width="2" points="{pts}"/></svg>')


def build_html(sim: "Simulation") -> str:
    card = compute_score(sim)
    org = sim.org
    e = escape
    parts: list[str] = []
    w = parts.append
    w(f"<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
      f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
      f"<title>Rapport RSSI Simulator — {e(org.nom)}</title><style>{CSS}</style></head><body><main>")
    w(f"<h1>Rapport de fin de mandat — {e(org.nom)}</h1>")
    w(f"<p class='muted'>{e(org.type_label)} · Difficulté {e(sim.difficulty.nom)} · mandat de {sim.years} an(s) · "
      f"Partie n° {sim.seed} · {sim.turn} semaines jouées · "
      f"généré le {datetime.now().strftime('%d/%m/%Y %H:%M')} · {e(config.APP_TITLE)} v{config.VERSION}</p>")
    if sim.game_over_reason:
        w(f"<p><strong>Fin de partie :</strong> {e(sim.game_over_reason)}</p>")

    # Score ------------------------------------------------------------------
    w("<h2>Évaluation globale</h2><div class='grid'>")
    w(f"<div class='card'><div class='muted'>Score</div><div class='big'>{card.total:.0f}/100</div>"
      f"<div>{e(card.grade)}</div></div>")
    w(f"<div class='card'><div class='muted'>Percentile</div><div class='big'>{card.percentile}<sup>e</sup></div>"
      f"<div class='muted'>par rapport à la distribution de référence du jeu</div></div>")
    w(f"<div class='card'><div class='muted'>Réputation finale</div>"
      f"<div class='big'>{sim.reputation.global_score():.0f}</div></div>")
    w(f"<div class='card'><div class='muted'>Pertes (incidents + sanctions)</div>"
      f"<div class='big' style='font-size:26px'>{_eur(sim.budget.cout_incident_cumule + sim.budget.amendes_cumulees)}</div></div>")
    w("</div><h3>Détail par critère</h3><table><tr><th>Critère</th><th>Poids</th><th>Résultat</th><th></th></tr>")
    for key, weight in WEIGHTS.items():
        v = card.components[key]
        w(f"<tr><td>{e(WEIGHT_LABELS[key])}</td><td>{weight:.0%}</td><td>{v:.0%}</td>"
          f"<td style='width:40%'><div class='bar'><i style='width:{v * 100:.0f}%'></i></div></td></tr>")
    w("</table><p class='muted'>Grille : 0-39 Insuffisant · 40-64 Moyen · 65-84 Bon · 85-100 Expert.</p>")

    w("<h2>Objectifs fixés par la direction</h2><table><tr><th>Objectif</th><th>Détail</th><th>Statut</th></tr>")
    for obj in sim.objectives:
        st = obj["status"]
        cls = {"reussi": "q-bonne", "echoue": "q-mauvaise"}.get(st, "q-moyenne")
        w(f"<tr><td>{e(OBJECTIVES[obj['id']].titre)}</td><td>{e(objective_text(obj))}</td>"
          f"<td class='{cls}'>{e(OBJECTIVE_STATUS_LABELS[st])}</td></tr>")
    w("</table>")

    w("<h2>Réputation au fil du mandat</h2>")
    w(_sparkline(sim.reputation.history))
    w("<h2>Confiance de la direction</h2>")
    w(_sparkline(sim.trust_history))

    # Décisions -----------------------------------------------------------------
    w("<h2>Les 3 meilleures décisions</h2>")
    if card.best_decisions:
        w("<ol>")
        for d in card.best_decisions:
            w(f"<li><strong>{e(d.choice)}</strong> <span class='muted'>({e(d.source_title)}, semaine {d.turn})</span>"
              f"<br>{e(d.feedback)}<br><span class='muted'>Référence : {e(d.reference)}</span></li>")
        w("</ol>")
    else:
        w("<p class='muted'>Aucune décision remarquable enregistrée.</p>")

    w("<h2>Les 3 erreurs critiques</h2>")
    if card.worst_mistakes:
        w("<ol>")
        for m in card.worst_mistakes:
            w(f"<li><strong>{e(m.title)}</strong> <span class='muted'>(semaine {m.turn})</span><br>{e(m.explanation)}"
              f"<br><span class='muted'>Référence : {e(m.reference)}</span></li>")
        w("</ol>")
    else:
        w("<p>Aucune erreur critique : bravo.</p>")

    # Incidents ----------------------------------------------------------------------
    w("<h2>Chronologie des incidents</h2>")
    incs = sim.incidents.incidents
    if not incs:
        w("<p class='muted'>Aucun incident au cours du mandat.</p>")
    else:
        w("<table><tr><th>Incident</th><th>Compromission</th><th>Détection</th><th>Phase</th>"
          "<th>Qualité des décisions</th><th>Coût</th></tr>")
        for inc in incs:
            t = sim.incidents.template(inc)
            cves = ", ".join(c.get("id", "") for c in t.cve_references) or "—"
            q = sim.incidents.decision_quality(inc) if inc.decisions_taken else None
            detected = f"sem. {inc.detection_turn}" if inc.detected else "non détecté"
            w(f"<tr><td><strong>{e(t.title)}</strong><br><span class='muted'>{e(t.id)} · CVE : {e(cves)}</span></td>"
              f"<td>sem. {inc.start_turn}</td><td>{detected}</td><td>{e(sim.phase_label(inc))}</td>"
              f"<td>{'—' if q is None else f'{q:.0%}'}</td>"
              f"<td>{_eur(inc.final_cost) if inc.final_cost is not None else '—'}</td></tr>")
        w("</table>")
        undetected = [i for i in incs if not i.detected]
        if undetected:
            w(f"<p><strong>{len(undetected)} compromission(s) toujours non détectée(s)</strong> à la fin du mandat.</p>")

    w("<h2>Journal des décisions</h2><table><tr><th>Sem.</th><th>Contexte</th><th>Décision</th><th>Évaluation</th></tr>")
    for d in sim.decisions:
        w(f"<tr><td>{d.turn}</td><td>{e(d.source_title)}</td><td>{e(d.choice)}</td>"
          f"<td class='q-{e(d.quality)}'>{e(d.quality)}</td></tr>")
    w("</table>")

    # Conformité ------------------------------------------------------------------------
    w("<h2>Notifications réglementaires</h2>")
    dls = sim.compliance.state.deadlines
    if dls:
        status_fr = {"on_time": "dans les délais", "late": "hors délai", "missed": "non réalisée", "pending": "en attente"}
        w("<table><tr><th>Incident</th><th>Obligation</th><th>Délai</th><th>Statut</th><th>Référence</th></tr>")
        for dl in dls:
            o = OBLIGATIONS[dl.kind]
            w(f"<tr><td>{e(dl.incident_uid)}</td><td>{e(o.label)}</td><td>{o.hours} h</td>"
              f"<td>{e(status_fr.get(dl.status, dl.status))}</td><td>{e(o.reference)}</td></tr>")
        w("</table>")
    else:
        w("<p class='muted'>Aucune notification requise.</p>")

    # Risque ------------------------------------------------------------------------------
    w("<h2>Cartographie du risque résiduel</h2><table><tr><th>Menace</th><th>V</th><th>G</th><th>Niveau</th></tr>")
    for t, (v, g) in sorted(sim.risk.risk_matrix(sim.turn).items(), key=lambda x: -x[1][0] * x[1][1]):
        cat = risk_category(v * g)
        w(f"<tr class='risk-{cat}'><td>{e(INCIDENT_TYPE_LABELS[t])}</td><td>{v}</td><td>{g}</td>"
          f"<td>{e(RISK_LABELS[cat])} ({v * g})</td></tr>")
    w("</table>")
    study = sim.risk.study
    w(f"<p>Étude EBIOS RM : {sum(study.done)}/5 ateliers validés"
      + (f", finalisée en semaine {study.completed_turn}" if study.completed_turn else "") + ".</p>")
    w(f"<p>Socle d'hygiène ANSSI couvert : {sim.risk.hygiene_coverage(sim.turn):.0%} des 42 mesures.</p>")

    w("<h2>Opérations SSI</h2><table>")
    mttp = sim.vulns.mean_time_to_patch()
    treated = sum(1 for v in sim.vulns.items if not v.is_open)
    exploited = sum(1 for v in sim.vulns.items if v.exploited_turn is not None)
    last = sim.phishing.last_measure()
    rows = [
        ("Vulnérabilités publiées vous concernant", str(len(sim.vulns.items))),
        ("Vulnérabilités corrigées", str(treated)),
        ("Délai moyen de correction", f"{mttp:.1f} semaines" if mttp is not None else "—"),
        ("Vulnérabilités exploitées par un attaquant", str(exploited)),
        ("Dernier taux de clic mesuré (faux hameçonnage)", f"{last[1]:.1%} (semaine {last[0]})" if last else "jamais mesuré"),
        ("Équipe SSI en fin de mandat", f"{sim.team.state.members} personne(s), {sim.team.state.departures} départ(s) "
                                        f"pour épuisement"),
        ("Comités de direction", f"{len(sim.board_state.get('history', []))} tenus, "
                                 f"{sum(1 for h in sim.board_state.get('history', []) if h['success'])} demandes accordées"),
    ]
    for label, value in rows:
        w(f"<tr><td>{e(label)}</td><td>{e(value)}</td></tr>")
    w("</table>")

    w("<h2>Bonnes pratiques manquées</h2>")
    if sim.missed_practices:
        w("<table><tr><th>Mesure</th><th>Aurait limité</th><th>Référence officielle</th></tr>")
        for p in sim.missed_practices:
            w(f"<tr><td>{e(p['mesure'])}</td><td>{e(p['incident'])}</td><td>{e(p['reference'])}</td></tr>")
        w("</table>")
    else:
        w("<p class='muted'>Aucune mesure clé manquante identifiée sur les incidents clos.</p>")

    w("<h2>Mesures déployées</h2><ul>")
    for mid in sorted(sim.portfolio.items):
        m = sim.data.measures[mid]
        st = sim.portfolio.items[mid]
        flag = " (socle initial)" if st.initial else (" (suspendue)" if st.suspended else "")
        w(f"<li>{e(m.nom)}{e(flag)} — <span class='muted'>{e(m.guide_anssi)}</span></li>")
    w("</ul>")

    w("<h2>Bilan budgétaire</h2><table>")
    for y in sim.budget.yearly:
        w(f"<tr><td>Année {y['annee']}</td><td>Budget {_eur(y['budget'])}</td><td>Dépensé {_eur(y['depense'])}</td></tr>")
    w(f"<tr><td>Année en cours</td><td>Budget {_eur(sim.budget.budget_annuel_ssi)}</td><td>Dépensé {_eur(sim.budget.spent)}</td></tr>")
    w(f"<tr><td>Coût net des incidents</td><td colspan='2'>{_eur(sim.budget.cout_incident_cumule)}"
      f" (assurance : {_eur(sim.budget.remboursements_assurance)} remboursés)</td></tr>")
    w(f"<tr><td>Sanctions</td><td colspan='2'>{_eur(sim.budget.amendes_cumulees)}</td></tr></table>")

    w("<footer><p>Rapport généré localement par RSSI Simulator. Aucune donnée personnelle n'est collectée. "
      "Les montants de sanction et probabilités sont des modèles pédagogiques (voir docs/METHODOLOGIE.md), "
      "ils ne constituent ni un barème officiel ni un conseil juridique.</p>"
      "<p>Code : GNU GPL v3 · Contenus pédagogiques : CC BY-SA 4.0.</p></footer></main></body></html>")
    return "".join(parts)


def generate_report(sim: "Simulation", directory: Path | None = None) -> Path:
    directory = Path(directory) if directory else config.user_paths().ensure().reports_dir
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"rapport-{sim.org.id}-{stamp}.html"
    path.write_text(build_html(sim), encoding="utf-8")
    return path
