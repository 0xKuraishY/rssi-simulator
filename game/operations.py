"""Opérations SSI au quotidien : équipe, vulnérabilités, niveau de menace, hameçonnage.

Ces systèmes donnent du « travail de fond » entre deux crises : chaque semaine,
l'équipe SSI dispose d'une capacité limitée (jours-homme) à répartir entre le
déploiement des mesures, la correction des vulnérabilités et les actions de
conformité. Une équipe surchargée retarde les chantiers et finit par s'épuiser.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from game.difficulty import Difficulty
    from game.organisation import Organisation

# --- Équipe -------------------------------------------------------------------
JH_PER_MEMBER = 4.0            # jours-homme SSI par personne et par semaine (le reste : run, réunions)
CRISIS_CAPACITY_FACTOR = 0.6   # une crise mobilise l'équipe
BURNOUT_WEEKS = 6              # semaines consécutives de surcharge avant risque de départ
BURNOUT_RISK = 0.25
REINFORCEMENT_WEEKS = 8
REINFORCEMENT_JH = 2.0         # jours-homme par semaine apportés par un renfort en régie
REINFORCEMENT_DAY_RATE = 800.0
RECRUIT_DELAY = 8

# --- Vulnérabilités ---------------------------------------------------------------
VULN_WEEKLY_RATE = 0.30
VISIBILITY_BASE = 0.55
MAINTENANCE_WINDOW = 4         # une fenêtre de maintenance toutes les 4 semaines
EXPLOIT_BASE = 0.010           # probabilité hebdomadaire d'exploitation d'une faille exposée exploitée
AUTO_PATCH_DELAY = 4           # correction automatique (gestion outillée des correctifs)
MAX_VULN_FACTOR = 1.8

# --- Hameçonnage ---------------------------------------------------------------------
PHISHING_FLOOR = 0.03
PHISHING_CAMPAIGN_COST = 1_500.0


# =============================================================================
# Équipe SSI
# =============================================================================
@dataclass
class TeamState:
    members: int
    used: float = 0.0
    overload_weeks: int = 0
    reinforcement_until: int = 0
    pending_recruits: list[int] = field(default_factory=list)   # tours d'arrivée
    departures: int = 0
    utilization: float = 0.0
    history: list[float] = field(default_factory=list)


class TeamEngine:
    def __init__(self, org: "Organisation", difficulty: "Difficulty", rng: random.Random) -> None:
        self.org = org
        self.difficulty = difficulty
        self.rng = rng
        self.state = TeamState(members=max(1, org.equipe_ssi))

    def capacity(self, turn: int, in_crisis: bool = False) -> float:
        cap = self.state.members * JH_PER_MEMBER * self.difficulty.capacity_mult
        if turn < self.state.reinforcement_until:
            cap += REINFORCEMENT_JH
        if in_crisis:
            cap *= CRISIS_CAPACITY_FACTOR
        return round(cap, 1)

    def available(self, turn: int, in_crisis: bool = False) -> float:
        return max(0.0, self.capacity(turn, in_crisis) - self.state.used)

    def reserve(self, jh: float, turn: int, in_crisis: bool = False) -> bool:
        if jh <= self.available(turn, in_crisis) + 1e-6:
            self.state.used += jh
            return True
        return False

    def reinforcement_cost(self) -> float:
        return REINFORCEMENT_WEEKS * REINFORCEMENT_JH * REINFORCEMENT_DAY_RATE

    def add_reinforcement(self, turn: int) -> None:
        self.state.reinforcement_until = max(self.state.reinforcement_until, turn) + REINFORCEMENT_WEEKS

    def recruit(self, turn: int) -> int:
        arrival = turn + RECRUIT_DELAY
        self.state.pending_recruits.append(arrival)
        return arrival

    def end_week(self, turn: int, background_load: float, in_crisis: bool) -> dict[str, Any]:
        """Clôt la semaine : calcule la charge totale, la surcharge et ses conséquences."""
        cap = max(0.1, self.capacity(turn, in_crisis))
        load = self.state.used + background_load
        self.state.utilization = load / cap
        self.state.history.append(round(self.state.utilization, 2))
        self.state.history = self.state.history[-26:]
        result: dict[str, Any] = {"departure": False, "arrivals": 0, "overloaded": load > cap}
        if self.state.utilization > 1.0:
            self.state.overload_weeks += 1
        elif self.state.utilization < 0.9:
            self.state.overload_weeks = 0
        if (self.state.overload_weeks >= BURNOUT_WEEKS and self.state.members > 1
                and self.rng.random() < BURNOUT_RISK):
            self.state.members -= 1
            self.state.departures += 1
            self.state.overload_weeks = 0
            result["departure"] = True
        arrived = [t for t in self.state.pending_recruits if t <= turn + 1]
        if arrived:
            self.state.members += len(arrived)
            self.state.pending_recruits = [t for t in self.state.pending_recruits if t > turn + 1]
            result["arrivals"] = len(arrived)
        self.state.used = 0.0
        return result

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.state)

    def load_dict(self, d: dict[str, Any]) -> None:
        self.state = TeamState(**d)


def measure_weekly_load(categorie: str) -> float:
    """Charge hebdomadaire de l'équipe pendant le déploiement d'une mesure."""
    return 0.5 if categorie in ("externalisation", "assurance", "formation") else 1.5


# =============================================================================
# Vulnérabilités
# =============================================================================
@dataclass(frozen=True)
class VulnDef:
    id: str
    produit: str
    titre: str
    gravite: str        # critique | elevee
    exploitee: bool
    exposition: str     # internet | interne
    type: str
    charge_jh: float
    arret: bool
    organisations: tuple[str, ...] = ()

    @property
    def weight(self) -> float:
        w = 0.14 if self.gravite == "critique" else 0.07
        if self.exploitee:
            w += 0.10
        if self.exposition == "interne":
            w *= 0.5
        return w


def load_vulns(path: Path) -> dict[str, VulnDef]:
    with Path(path).open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)["vulnerabilites"]
    return {v["id"]: VulnDef(
        id=v["id"], produit=v["produit"], titre=v["titre"], gravite=v["gravite"], exploitee=bool(v["exploitee"]),
        exposition=v["exposition"], type=v["type"], charge_jh=float(v["charge_jh"]), arret=bool(v["arret"]),
        organisations=tuple(v.get("organisations") or ())) for v in raw}


@dataclass
class VulnInstance:
    uid: str
    cve: str
    discovered: int
    visible: bool
    status: str = "ouverte"   # ouverte | planifiee | contournee | corrigee | acceptee
    due_turn: int | None = None
    closed_turn: int | None = None
    exploited_turn: int | None = None   # exploitation silencieuse par un attaquant

    @property
    def is_open(self) -> bool:
        return self.status in ("ouverte", "planifiee", "contournee", "acceptee")


VULN_ACTIONS = {
    "urgence": "Corriger en urgence",
    "planifier": "Planifier (fenêtre de maintenance)",
    "contourner": "Mesure de contournement",
    "accepter": "Accepter le risque",
}


class VulnerabilityEngine:
    def __init__(self, org: "Organisation", defs: dict[str, VulnDef], difficulty: "Difficulty",
                 rng: random.Random) -> None:
        self.org = org
        self.defs = {k: v for k, v in defs.items() if not v.organisations or org.id in v.organisations}
        self.difficulty = difficulty
        self.rng = rng
        self.items: list[VulnInstance] = []
        self.patched_delays: list[int] = []
        self._counter = 0

    def definition(self, v: VulnInstance) -> VulnDef:
        return self.defs[v.cve]

    def get(self, uid: str) -> VulnInstance:
        for v in self.items:
            if v.uid == uid:
                return v
        raise KeyError(uid)

    def open_items(self, visible_only: bool = False) -> list[VulnInstance]:
        return [v for v in self.items if v.is_open and (v.visible or not visible_only)]

    def visibility(self, active: set[str]) -> float:
        p = VISIBILITY_BASE
        if "M26" in active:
            p += 0.30
        if "M40" in active:
            p += 0.10
        return min(0.98, p)

    def spawn(self, turn: int, active: set[str]) -> VulnInstance | None:
        if self.rng.random() >= VULN_WEEKLY_RATE * self.difficulty.vuln_rate:
            return None
        seen = {v.cve for v in self.items}
        candidates = sorted(c for c in self.defs if c not in seen)
        if not candidates:
            return None
        cve = self.rng.choice(candidates)
        self._counter += 1
        inst = VulnInstance(f"V{self._counter:03d}", cve, turn, self.rng.random() < self.visibility(active))
        self.items.append(inst)
        return inst

    def reveal_hidden(self, share: float = 1.0) -> list[VulnInstance]:
        """Un audit (test d'intrusion, scan) révèle les vulnérabilités ignorées."""
        revealed = []
        for v in self.items:
            if v.is_open and not v.visible and self.rng.random() < share:
                v.visible = True
                revealed.append(v)
        return revealed

    def factor(self, incident_type: str) -> float:
        f = 1.0
        for v in self.items:
            if not v.is_open:
                continue
            d = self.defs[v.cve]
            if d.type == incident_type:
                f *= 1.0 + (d.weight * 0.5 if v.status == "contournee" else d.weight)
        return min(MAX_VULN_FACTOR, f)

    def apply_action(self, uid: str, action: str, turn: int) -> VulnInstance:
        v = self.get(uid)
        if not v.is_open or v.status == "planifiee":
            raise ValueError("Cette vulnérabilité est déjà traitée")
        if action == v.status or (action == "contourner" and v.status == "contournee"):
            raise ValueError("Action déjà appliquée")
        if action == "urgence":
            v.status, v.due_turn = "planifiee", turn + 1
        elif action == "planifier":
            v.status, v.due_turn = "planifiee", turn + (MAINTENANCE_WINDOW - turn % MAINTENANCE_WINDOW)
        elif action == "contourner":
            v.status = "contournee"
        elif action == "accepter":
            v.status = "acceptee"
        else:
            raise ValueError(f"Action inconnue : {action}")
        return v

    def action_cost(self, uid: str, action: str) -> float:
        d = self.defs[self.get(uid).cve]
        return {"urgence": d.charge_jh * 1.5, "planifier": d.charge_jh, "contourner": d.charge_jh * 0.5,
                "accepter": 0.0}[action]

    def weekly(self, turn: int, active: set[str], exploit_allowed: bool) -> dict[str, list[VulnInstance]]:
        """Corrections planifiées, correction automatique, exploitation par les attaquants."""
        patched, exploited = [], []
        auto = "M08" in active
        for v in self.items:
            if not v.is_open:
                continue
            d = self.defs[v.cve]
            if v.status == "planifiee" and v.due_turn is not None and turn >= v.due_turn:
                v.status, v.closed_turn = "corrigee", turn
                self.patched_delays.append(turn - v.discovered)
                patched.append(v)
                continue
            if auto and v.status == "ouverte" and turn - v.discovered >= AUTO_PATCH_DELAY \
                    and not (d.gravite == "critique" and d.exposition == "internet"):
                v.status, v.closed_turn = "corrigee", turn
                v.visible = True
                self.patched_delays.append(turn - v.discovered)
                patched.append(v)
                continue
            if (exploit_allowed and d.exploitee and d.exposition == "internet" and v.status != "contournee"
                    and v.exploited_turn is None):
                age = turn - v.discovered
                p = EXPLOIT_BASE * self.difficulty.incident_mult * (1 + age / 10)
                if self.rng.random() < p:
                    v.exploited_turn = turn
                    exploited.append(v)
        return {"patched": patched, "exploited": exploited}

    # indicateurs
    def critical_exposed(self) -> list[VulnInstance]:
        return [v for v in self.open_items() if self.defs[v.cve].gravite == "critique"
                and self.defs[v.cve].exposition == "internet" and v.status != "contournee"]

    def oldest_critical_age(self, turn: int) -> int:
        ages = [turn - v.discovered for v in self.critical_exposed()]
        return max(ages, default=0)

    def mean_time_to_patch(self) -> float | None:
        return sum(self.patched_delays) / len(self.patched_delays) if self.patched_delays else None

    def to_dict(self) -> dict[str, Any]:
        return {"items": [asdict(v) for v in self.items], "patched_delays": list(self.patched_delays),
                "counter": self._counter}

    def load_dict(self, d: dict[str, Any]) -> None:
        self.items = [VulnInstance(**v) for v in d.get("items", []) if v["cve"] in self.defs]
        self.patched_delays = list(d.get("patched_delays", []))
        self._counter = int(d.get("counter", len(self.items)))


# =============================================================================
# Niveau de menace (bulletins de veille)
# =============================================================================
@dataclass(frozen=True)
class Campaign:
    id: str
    titre: str
    texte: str
    facteurs: dict[str, float]
    duree: int


def load_campaigns(path: Path) -> dict[str, Campaign]:
    with Path(path).open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)["campagnes"]
    return {c["id"]: Campaign(c["id"], c["titre"], c["texte"], {k: float(v) for k, v in c["facteurs"].items()},
                              int(c["duree"])) for c in raw}


THREAT_LEVELS = ((1.1, "Modéré"), (1.4, "Élevé"), (99.0, "Très élevé"))


class ThreatEngine:
    def __init__(self, campaigns: dict[str, Campaign], difficulty: "Difficulty", rng: random.Random) -> None:
        self.campaigns = campaigns
        self.difficulty = difficulty
        self.rng = rng
        self.active: list[dict[str, Any]] = []   # {"id", "until"}
        self.history: list[str] = []

    def weekly(self, turn: int) -> Campaign | None:
        self.active = [a for a in self.active if a["until"] >= turn]
        max_active = 2 if self.difficulty.level >= 3 else 1
        if len(self.active) >= max_active or not self.campaigns:
            return None
        if self.rng.random() >= 0.06 * self.difficulty.incident_mult:
            return None
        current = {a["id"] for a in self.active}
        options = sorted(k for k in self.campaigns if k not in current)
        c = self.campaigns[self.rng.choice(options)]
        self.active.append({"id": c.id, "until": turn + c.duree})
        self.history.append(c.id)
        return c

    def factor(self, incident_type: str, turn: int) -> float:
        f = 1.0
        for a in self.active:
            if a["until"] < turn:
                continue
            fac = self.campaigns[a["id"]].facteurs
            f *= fac.get(incident_type, fac.get("tous", 1.0))
        return f

    def level(self, turn: int) -> tuple[float, str]:
        factors = [self.factor(t, turn) for t in ("ransomware", "phishing", "ddos", "vpn_exploit",
                                                    "supply_chain", "compromission_cloud")]
        intensity = max(factors) * self.difficulty.incident_mult
        for threshold, label in THREAT_LEVELS:
            if intensity <= threshold:
                return intensity, label
        return intensity, THREAT_LEVELS[-1][1]

    def active_campaigns(self, turn: int) -> list[Campaign]:
        return [self.campaigns[a["id"]] for a in self.active if a["until"] >= turn]

    def to_dict(self) -> dict[str, Any]:
        return {"active": list(self.active), "history": list(self.history)}

    def load_dict(self, d: dict[str, Any]) -> None:
        self.active = [a for a in d.get("active", []) if a["id"] in self.campaigns]
        self.history = list(d.get("history", []))


# =============================================================================
# Indicateur : taux de clic aux campagnes d'hameçonnage
# =============================================================================
class PhishingKPI:
    def __init__(self, initial_rate: float) -> None:
        self.initial = initial_rate
        self.rate = initial_rate
        self.measured: list[tuple[int, float]] = []

    def quarterly(self, awareness: bool, mail_filter: bool) -> None:
        if awareness:
            self.rate = max(PHISHING_FLOOR, self.rate * 0.78)
        else:
            self.rate = min(self.initial * 1.1, self.rate + 0.01)
        if mail_filter:
            self.rate = max(PHISHING_FLOOR, self.rate * 0.97)

    def run_campaign(self, turn: int, rng: random.Random) -> float:
        """Campagne de faux hameçonnage : mesure (bruitée) et effet pédagogique immédiat."""
        observed = max(0.0, self.rate + rng.uniform(-0.02, 0.02))
        self.measured.append((turn, round(observed, 3)))
        self.rate = max(PHISHING_FLOOR, self.rate * 0.92)
        return observed

    def factor(self) -> float:
        return max(0.3, self.rate / self.initial) if self.initial > 0 else 1.0

    def last_measure(self) -> tuple[int, float] | None:
        return self.measured[-1] if self.measured else None

    def to_dict(self) -> dict[str, Any]:
        return {"initial": self.initial, "rate": self.rate, "measured": [list(m) for m in self.measured]}

    def load_dict(self, d: dict[str, Any]) -> None:
        self.initial = float(d["initial"])
        self.rate = float(d["rate"])
        self.measured = [(int(t), float(r)) for t, r in d.get("measured", [])]
