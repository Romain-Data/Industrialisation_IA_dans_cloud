"""Worker qui consomme la file des commandes et enregistre leurs prédictions (ADR-0006)."""

import logging
import threading
from collections.abc import Callable
from typing import Any

from src.abstraction.order_queue import OrderQueue
from src.abstraction.order_store import OrderStore
from src.domain.classifier import Classifier
from src.serving.service import compute_prediction

logger = logging.getLogger(__name__)


class OrderWorker:
    """Consomme les événements de commande et enregistre leur prédiction."""

    def __init__(
        self,
        order_queue: OrderQueue,
        order_store: OrderStore,
        get_model: Callable[[], Classifier | None],
    ) -> None:
        self._queue = order_queue
        self._store = order_store
        self._get_model = get_model
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def process_one(self, timeout: float = 0.0) -> bool:
        """Traite au plus un événement. Retourne False si la file est vide."""
        event = self._queue.consume(timeout)

        if event is None:
            return False

        self._handle(event)
        return True

    def _handle(self, event: dict[str, Any]) -> None:
        order = dict(event["order"])
        order_id = order.pop("order_id")
        model = self._get_model()

        if model is None:
            logger.warning("Modèle indisponible, commande %s non prédite.", order_id)
            return

        try:
            prediction = compute_prediction(order_id, order, model)
        except ValueError:
            logger.exception("Commande %s invalide, prédiction ignorée.", order_id)
            return

        self._store.save_prediction(prediction)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_one(timeout=0.2)
            except Exception:
                logger.exception("Erreur inattendue dans le worker.")

    def start(self) -> None:
        """Démarre le thread du worker (thread démon, arrêté avec l'API)."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="order-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Demande l'arrêt du worker et attend la fin du traitement en cours (2 s au plus)."""
        self._stop.set()

        if self._thread is not None:
            self._thread.join(timeout=2)

    def is_alive(self) -> bool:
        """Indique si le thread du worker tourne (utilisé par /health/ready)."""
        return self._thread is not None and self._thread.is_alive()
