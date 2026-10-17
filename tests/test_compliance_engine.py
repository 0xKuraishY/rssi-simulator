"""Conformité : délais CNIL / NIS2 / LPM, pénalités, obligations, contrôles, ISO 27001."""
from __future__ import annotations

import random

import pytest

from game.compliance_engine import OBLIGATIONS, PERMANENT, ComplianceEngine, Inspection
from game.incident_engine import Phase


def make(data, org_id: str) -> ComplianceEngine:  # type: ignore[no-untyped-def]
    return ComplianceEngine(data.organisations[org_id], random.Random(4), data.iso_controls)


def test_regulatory_deadlines() -> None:
    assert OBLIGATIONS["cnil_72h"].hours == 72
    assert OBLIGATIONS["nis2_24h"].hours == 24
    assert OBLIGATIONS["nis2_72h"].hours == 72
    assert OBLIGATIONS["nis2_1mois"].hours == 720
    assert OBLIGATIONS["lpm_24h"].hours == 24
    assert OBLIGATIONS["plainte_72h"].hours == 72


def test_applicable_obligations_by_regime(data) -> None:  # type: ignore[no-untyped-def]
    all_kinds = ["nis2_24h", "lpm_24h", "hds_signalement", "cnil_72h", "nis2_72h", "nis2_1mois"]
    pme = make(data, "pme_industrie").applicable_obligations(all_kinds, insured=False)
    assert pme == ["cnil_72h"]
    tel = make(data, "telecom").applicable_obligations(all_kinds, insured=True)
    assert {"lpm_24h", "nis2_24h", "plainte_72h"} <= set(tel)
    assert "hds_signalement" not in tel
    hop = make(data, "hopital").applicable_obligations(all_kinds, insured=False, personal_data=False)
    assert "cnil_72h" not in hop and "hds_signalement" in hop
    assert hop == sorted(hop, key=lambda k: OBLIGATIONS[k].hours)


def test_notify_on_time_late_and_missed(data) -> None:  # type: ignore[no-untyped-def]
    c = make(data, "hopital")
    c.open_deadlines("I1", ["cnil_72h", "nis2_24h", "nis2_72h"])
    c.open_deadlines("I1", ["cnil_72h"])  # pas de doublon
    assert len(c.deadlines_for("I1")) == 3
    assert c.notify("I1", "nis2_24h", 20).status == "on_time"
    assert c.check_deadlines("I1", 50) == []
    missed = c.check_deadlines("I1", 80)
    assert {d.kind for d in missed} == {"cnil_72h", "nis2_72h"}
    assert c.check_deadlines("I1", 90) == []  # signalé une seule fois
    late = c.notify("I1", "cnil_72h", 90)
    assert late.status == "late"
    assert c.notify("I1", "cnil_72h", 95) is late  # idempotent
    with pytest.raises(KeyError):
        c.notify("I2", "cnil_72h", 1)
    assert c.notification_rate() == pytest.approx(1 / 3)
    assert c.time_left(c.deadlines_for("I1")[0], 10) == 62


def test_notify_after_deadline_without_check(data) -> None:  # type: ignore[no-untyped-def]
    c = make(data, "hopital")
    c.open_deadlines("I1", ["nis2_24h"])
    assert c.notify("I1", "nis2_24h", 30).status == "late"
    assert c.state.missed == 1


def test_cnil_fine_minimum_and_cap(data) -> None:  # type: ignore[no-untyped-def]
    pme = make(data, "pme_industrie")
    assert pme.cnil_fine(1, False) >= 15_000
    hop = make(data, "hopital")
    assert hop.cnil_fine(4, True) > hop.cnil_fine(1, False)
    assert hop.cnil_fine(4, True, 168) >= hop.cnil_fine(4, True, 0)
    tel = make(data, "telecom")
    assert tel.cnil_fine(4, True, 1000) <= max(10_000_000, 0.02 * tel.org.chiffre_affaires)


def test_nis2_fine_proportional_to_cap(data) -> None:  # type: ignore[no-untyped-def]
    ess = make(data, "telecom")  # essentielle, CA 900 M€ → plafond 18 M€
    imp = make(data, "mairie")   # importante → plafond 7 M€ (CA 70 M€)
    assert ess.nis2_fine(1) == pytest.approx(round(max(10e6, 0.02 * 900e6) * 0.005, -3))
    assert imp.nis2_fine(1) == pytest.approx(round(7e6 * 0.005, -3))
    assert ess.nis2_fine(4) == pytest.approx(4 * ess.nis2_fine(1), rel=0.01)


def test_penalty_for_each_kind(data) -> None:  # type: ignore[no-untyped-def]
    c = make(data, "telecom")
    c.open_deadlines("I", list(OBLIGATIONS))
    pens = {d.kind: c.penalty_for(d, 3, False) for d in c.deadlines_for("I")}
    assert pens["cnil_72h"][0] >= 15_000
    assert pens["nis2_24h"][0] == 0 and pens["nis2_24h"][1]["regulateurs"] < 0
    assert pens["nis2_72h"][0] > pens["nis2_1mois"][0] > 0
    assert pens["lpm_24h"][0] == 150_000
    assert pens["plainte_72h"] == (0.0, {})
    assert pens["rgpd_art34"][0] == 0 and pens["rgpd_art34"][1]["utilisateurs"] < 0
    assert pens["hds_signalement"][0] == 0


def test_permanent_obligations(data) -> None:  # type: ignore[no-untyped-def]
    c = make(data, "mairie")
    keys = {p.key for p in c.applicable_permanent()}
    assert {"registre", "dpo", "formation_rgpd", "nis2_enregistrement"} <= keys
    assert "hds_hebergeur" not in keys and "lpm_homologation" not in keys
    assert not c.is_satisfied("registre", 10, set(), None)
    c.mark_done("registre", 10)
    assert c.is_satisfied("registre", 40, set(), None)
    assert not c.is_satisfied("registre", 62, set(), None)  # validité 52 semaines
    assert c.is_satisfied("dpo", 1, {"M39"}, None)
    assert c.is_satisfied("nis2_analyse_risques", 30, set(), 10)
    assert not c.is_satisfied("nis2_analyse_risques", 70, set(), 10)
    assert 0 <= c.compliance_rate(10, set(), None) < 1
    assert not make(data, "pme_industrie").regime_active("rgpd_dpo")


def test_iso_progress_and_smsi(data) -> None:  # type: ignore[no-untyped-def]
    c = make(data, "esn")
    assert len(data.iso_controls) == 93
    base = c.iso_progress(set())
    assert base == pytest.approx(data.organisations["esn"].iso_avancement_initial / 93)
    added = c.iso_smsi_step(set())
    assert len(added) == 5 and all(a.startswith(("5.", "6.")) for a in added)
    assert c.iso_progress({"8.13", "8.15"}) > base
    assert c.is_satisfied("iso_certification", 1, {"M38"}, None)


def test_inspections_schedule_and_run(data) -> None:  # type: ignore[no-untyped-def]
    c = make(data, "telecom")
    planned = c.schedule_year(1, lambda y, m: m * 4, certified=True)
    assert any(i.kind == "iso" for i in planned)
    assert c.due_inspections(0) == []
    assert c.upcoming_inspections(0)
    # CNIL : plusieurs écarts → sanction
    cnil = Inspection("cnil", 5)
    res = c.run_inspection(cnil, 5, set(), None, 0.2, set(), False)
    assert res["gaps"] and res["fine"] > 0 and cnil.result == "non conforme"
    # ANSSI : socle insuffisant
    res = c.run_inspection(Inspection("anssi", 6), 6, set(), None, 0.3, set(), False)
    assert any("hygiène" in g for g in res["gaps"])
    # ISO : incident majeur mal géré → suspension
    res = c.run_inspection(Inspection("iso", 7), 7, {"M38"}, None, 0.9, set(), True)
    assert res["gaps"] and c.state.iso_suspended_until == 7 + 26
    assert not c.is_satisfied("iso_certification", 10, {"M38"}, None)


def test_inspection_conforming(data) -> None:  # type: ignore[no-untyped-def]
    c = make(data, "pme_industrie")
    c.mark_done("registre", 1)
    res = c.run_inspection(Inspection("cnil", 2), 2, {"M02"}, None, 0.9, set(), False)
    assert res["gaps"] == [] and res["reputation"]["regulateurs"] > 0
    assert c.schedule_anssi_ex_post(5) is None
    assert make(data, "mairie").schedule_anssi_ex_post(5).turn > 5


def test_serialization(data) -> None:  # type: ignore[no-untyped-def]
    c = make(data, "hopital")
    c.open_deadlines("I1", ["cnil_72h"])
    c.mark_done("registre", 3)
    c.schedule_year(1, lambda y, m: m, certified=False)
    other = make(data, "hopital")
    other.load_dict(c.to_dict())
    assert other.to_dict() == c.to_dict()


# -- intégration : délai CNIL manqué dans la simulation ------------------------------
def test_missed_cnil_deadline_triggers_fine(sim) -> None:  # type: ignore[no-untyped-def]
    inc = sim._start_incident("INC-003")
    if not inc.detected:
        inc.phase = Phase.DETECTION
        sim._on_detected(inc)
    kinds = {d.kind for d in sim.compliance.deadlines_for(inc.uid)}
    assert "cnil_72h" in kinds
    fines_before = sim.budget.amendes_cumulees
    while (d := sim.incidents.pending_decision(inc)) is not None:
        sim.crisis_decide(inc.uid, d.id, d.choix[0].id)
    sim.crisis_close(inc.uid)  # l'horloge passe à H+168 sans notification
    assert sim.budget.amendes_cumulees >= fines_before + 15_000
    assert any("CNIL" in m.title for m in sim.mistakes)


def test_notification_in_time_avoids_fine(sim) -> None:  # type: ignore[no-untyped-def]
    inc = sim._start_incident("INC-003")
    if not inc.detected:
        inc.phase = Phase.DETECTION
        sim._on_detected(inc)
    for d in sim.compliance.deadlines_for(inc.uid):
        sim.notify_obligation(inc.uid, d.kind)
    while (d := sim.incidents.pending_decision(inc)) is not None:
        sim.crisis_decide(inc.uid, d.id, d.choix[0].id)
        for dl in sim.compliance.deadlines_for(inc.uid):
            if dl.done_hour is None:
                sim.notify_obligation(inc.uid, dl.kind)
    sim.crisis_close(inc.uid)
    assert sim.budget.amendes_cumulees == 0
    assert sim.compliance.notification_rate() == 1.0


def test_compliance_actions(sim) -> None:  # type: ignore[no-untyped-def]
    from game.simulation import GameRuleError
    sim.compliance_action("registre")
    assert sim.compliance.is_satisfied("registre", sim.turn, set(), None)
    with pytest.raises(GameRuleError):
        sim.compliance_action("nis2_analyse_risques")
    with pytest.raises(GameRuleError):
        sim.compliance_action("inconnu")
    sim.compliance_action("formation_rgpd")  # via la mesure M02
    assert sim.portfolio.has("M02")
    added = sim.iso_smsi_step()
    assert len(added) == 5
    assert PERMANENT["registre"].validity_weeks == 52
