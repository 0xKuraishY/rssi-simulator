"""Audio minimaliste et tolérant aux pannes.

Les sons sont synthétisés à la volée (ondes sinusoïdales) : aucun fichier
n'est nécessaire. Si un fichier ``assets/sounds/<nom>.ogg`` existe, il est
prioritaire. Sans périphérique audio (CI, serveur), tout devient silencieux.
"""
from __future__ import annotations

import array
import logging
import math

import pygame

import config

log = logging.getLogger(__name__)

SAMPLE_RATE = 22050

# nom → liste de (fréquence Hz, durée s)
_TONES: dict[str, list[tuple[float, float]]] = {
    "click": [(880, 0.03)],
    "notify": [(660, 0.08), (880, 0.10)],
    "alert": [(440, 0.15), (0, 0.05), (440, 0.15), (0, 0.05), (440, 0.25)],
    "success": [(523, 0.08), (659, 0.08), (784, 0.14)],
    "fail": [(392, 0.15), (311, 0.25)],
}


def _synth(notes: list[tuple[float, float]], volume: float = 0.25) -> bytes:
    buf = array.array("h")
    amp = int(32767 * volume)
    for freq, dur in notes:
        n = int(SAMPLE_RATE * dur)
        for i in range(n):
            env = min(1.0, i / 200, (n - i) / 200)  # fondu anti-clic
            value = int(amp * env * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)) if freq else 0
            buf.append(value)
    return buf.tobytes()


class Audio:
    def __init__(self, enabled: bool = True, volume: float = 0.6) -> None:
        self.volume = volume
        self.enabled = False
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        if not enabled:
            return
        try:
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1)
            self.enabled = True
        except pygame.error as exc:
            log.info("Audio indisponible : %s", exc)

    def _get(self, name: str) -> pygame.mixer.Sound | None:
        if name in self._sounds:
            return self._sounds[name]
        sound = None
        path = config.SOUNDS_DIR / f"{name}.ogg"
        try:
            if path.exists():
                sound = pygame.mixer.Sound(str(path))
            elif name in _TONES:
                sound = pygame.mixer.Sound(buffer=_synth(_TONES[name]))
        except pygame.error as exc:
            log.debug("Son %s indisponible : %s", name, exc)
        if sound is not None:
            self._sounds[name] = sound
        return sound

    def play(self, name: str) -> None:
        if not self.enabled or self.volume <= 0:
            return
        sound = self._get(name)
        if sound is not None:
            sound.set_volume(self.volume)
            sound.play()

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
