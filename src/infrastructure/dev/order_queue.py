"""File d'attente en mémoire du processus (dev et instance unique, ADR-0006)."""

import queue
from typing import Any

from src.abstraction.order_queue import OrderQueue


class InMemoryOrderQueue(OrderQueue):
    """File en mémoire du processus, pour le dev. Perdue au redémarrage."""

    def __init__(self) -> None:
        self._queue = queue.Queue()

    def publish(self, event: dict[str, Any]) -> None:
        self._queue.put(event)

    def consume(self, timeout: float = 1.0) -> dict[str, Any] | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
