"""Diffusion des prédictions en mémoire, dans un seul processus (dev, tests)."""

import logging
import threading
from typing import Any

from src.abstraction.prediction_events import PredictionEvents, PredictionListener

logger = logging.getLogger(__name__)


class InMemoryPredictionEvents(PredictionEvents):
    """Appelle directement les auditeurs du processus, dans le thread de l'émetteur."""

    def __init__(self) -> None:
        self._listeners: list[PredictionListener] = []
        self._lock = threading.Lock()

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:  # un auditeur en erreur ne bloque pas les autres
                logger.exception("Auditeur de prédictions en erreur.")

    def listen(self, listener: PredictionListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def close(self) -> None:
        with self._lock:
            self._listeners.clear()
