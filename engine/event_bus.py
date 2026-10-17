"""Bus d'événements Pub/Sub découplant les systèmes du jeu.

Deux modes de diffusion :
- ``publish`` met l'événement en file ; ``dispatch`` le distribue (une fois par
  image dans la boucle principale) → ordre déterministe, indispensable pour
  rejouer une partie avec la même graine ;
- ``emit`` distribue immédiatement (tests, cas synchrones).

Les sujets sont des chaînes hiérarchiques séparées par des points
(``incident.detected``). Un abonnement à ``incident.*`` reçoit tous les sujets
commençant par ``incident.`` ; ``*`` reçoit tout.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._queue: deque[Event] = deque()
        self.history: deque[Event] = deque(maxlen=200)

    # -- abonnements -------------------------------------------------------
    def subscribe(self, topic: str, handler: Handler) -> Callable[[], None]:
        """Abonne ``handler`` ; renvoie une fonction de désabonnement."""
        self._handlers[topic].append(handler)
        return lambda: self.unsubscribe(topic, handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        handlers = self._handlers.get(topic)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def clear(self) -> None:
        self._handlers.clear()
        self._queue.clear()

    # -- diffusion ---------------------------------------------------------
    def publish(self, topic: str, **payload: Any) -> Event:
        event = Event(topic, payload)
        self._queue.append(event)
        return event

    def emit(self, topic: str, **payload: Any) -> Event:
        event = Event(topic, payload)
        self._deliver(event)
        return event

    def dispatch(self, max_events: int = 1000) -> int:
        """Distribue les événements en file. Les événements publiés pendant la
        distribution sont traités dans le même appel (dans la limite fixée)."""
        count = 0
        while self._queue and count < max_events:
            self._deliver(self._queue.popleft())
            count += 1
        return count

    @property
    def pending(self) -> int:
        return len(self._queue)

    def _matching_handlers(self, topic: str) -> list[Handler]:
        handlers = list(self._handlers.get(topic, ()))
        parts = topic.split(".")
        for i in range(len(parts) - 1, 0, -1):
            handlers.extend(self._handlers.get(".".join(parts[:i]) + ".*", ()))
        handlers.extend(self._handlers.get("*", ()))
        return handlers

    def _deliver(self, event: Event) -> None:
        self.history.append(event)
        for handler in self._matching_handlers(event.topic):
            try:
                handler(event)
            except Exception:  # un abonné défaillant ne doit pas bloquer les autres
                log.exception("Erreur dans un abonné à %s", event.topic)
