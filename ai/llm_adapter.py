"""Adaptateur de narration : LLM local (llama-cpp-python) ou dialogues statiques YAML.

Détection du matériel :
1. NVIDIA (nvidia-smi)  → n_gpu_layers = -1 (toutes les couches sur GPU)
2. AMD (rocm-smi)       → n_gpu_layers = -1
3. CPU seul             → n_gpu_layers = 0, n_threads = nb de cœurs - 1
4. llama-cpp ou modèle absent → narration statique : le jeu reste 100 % fonctionnel.

Aucune requête réseau : le modèle GGUF doit être déposé manuellement dans
<dossier de données>/models/ (ou désigné par RSSI_SIMULATOR_MODEL).
"""
from __future__ import annotations

import logging
import os
import random
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import config
from ai import prompt_builder

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HardwareProfile:
    backend: str  # "nvidia" | "amd" | "cpu"
    n_gpu_layers: int
    n_threads: int


def _probe(cmd: list[str]) -> bool:
    if shutil.which(cmd[0]) is None:
        return False
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=5, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def detect_hardware() -> HardwareProfile:
    threads = max(1, (os.cpu_count() or 2) - 1)
    if _probe(["nvidia-smi", "-L"]):
        return HardwareProfile("nvidia", -1, threads)
    if _probe(["rocm-smi", "--showproductname"]):
        return HardwareProfile("amd", -1, threads)
    return HardwareProfile("cpu", 0, threads)


def find_model(models_dir: Path | None = None) -> Path | None:
    explicit = os.environ.get(config.AI_MODEL_ENV)
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    directory = models_dir or config.user_paths().models_dir
    if not directory.is_dir():
        return None
    candidates = sorted(directory.glob("*.gguf"), key=lambda p: p.stat().st_size)
    return candidates[0] if candidates else None


class StaticNarrator:
    """Narration à partir des messages YAML des scénarios (aucune dépendance)."""

    backend = "static"
    available = True

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def team_message(self, context: dict[str, Any], fallback: list[dict[str, str]] | None = None) -> dict[str, str]:
        if fallback:
            return dict(self.rng.choice(fallback))
        return {"de": context.get("emetteur", "Cellule de crise"),
                "texte": f"Point de situation H+{context.get('heure', 0)} : les équipes poursuivent "
                         f"la phase « {context.get('phase', '')} »."}

    def rex_summary(self, context: dict[str, Any], fallback: str = "") -> str:
        return fallback or "Retour d'expérience : consolider la détection, la sauvegarde et la préparation à la crise."


class LlamaNarrator(StaticNarrator):
    backend = "llama"

    def __init__(self, model_path: Path, hardware: HardwareProfile, seed: int | None = None) -> None:
        super().__init__(seed)
        from llama_cpp import Llama  # import tardif : dépendance optionnelle

        self.hardware = hardware
        self._lock = threading.Lock()
        self._llm = Llama(
            model_path=str(model_path), n_ctx=config.AI_CONTEXT_SIZE,
            n_gpu_layers=hardware.n_gpu_layers, n_threads=hardware.n_threads,
            seed=seed if seed is not None else -1, verbose=False,
        )

    def _complete(self, prompt: str) -> str:
        with self._lock:
            out = self._llm.create_chat_completion(
                messages=prompt_builder.chat_format(prompt),
                max_tokens=config.AI_MAX_TOKENS, temperature=config.AI_TEMPERATURE,
            )
        return str(out["choices"][0]["message"]["content"]).strip()

    def team_message(self, context: dict[str, Any], fallback: list[dict[str, str]] | None = None) -> dict[str, str]:
        try:
            text = self._complete(prompt_builder.team_message_prompt(context))
            if text:
                return {"de": context.get("emetteur", "Cellule de crise"), "texte": text}
        except Exception:  # le jeu ne doit jamais dépendre de l'IA
            log.exception("Génération IA indisponible, repli statique")
        return super().team_message(context, fallback)

    def rex_summary(self, context: dict[str, Any], fallback: str = "") -> str:
        try:
            return self._complete(prompt_builder.rex_summary_prompt(context)) or fallback
        except Exception:
            log.exception("Génération IA indisponible, repli statique")
            return super().rex_summary(context, fallback)


def create_narrator(enabled: bool = True, seed: int | None = None, models_dir: Path | None = None) -> StaticNarrator:
    if not enabled or os.environ.get(config.AI_ENABLED_ENV) == "0":
        return StaticNarrator(seed)
    model = find_model(models_dir)
    if model is None:
        log.info("Aucun modèle GGUF trouvé : narration statique")
        return StaticNarrator(seed)
    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        log.info("llama-cpp-python non installé : narration statique")
        return StaticNarrator(seed)
    hardware = detect_hardware()
    try:
        narrator = LlamaNarrator(model, hardware, seed)
        log.info("Narration IA locale active (%s, %s)", model.name, hardware.backend)
        return narrator
    except Exception:
        log.exception("Chargement du modèle impossible : narration statique")
        return StaticNarrator(seed)


def run_async(func: Callable[[], Any], callback: Callable[[Any], None]) -> threading.Thread:
    """Exécute une génération hors du fil d'affichage (évite de figer l'interface)."""
    def worker() -> None:
        callback(func())
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread
