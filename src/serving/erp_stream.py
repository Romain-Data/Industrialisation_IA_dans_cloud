"""Flux temps réel des commandes de l'ERP, activé par le logisticien (ADR-0013).

Quand le logisticien prend son poste, il active le flux : un thread lit toutes les
`poll_seconds` les commandes arrivées dans l'ERP (MongoDB, lecture seule) **depuis
l'activation**, et les fait passer par le parcours d'une commande reçue : enregistrement en
base, événement dans la file, prédiction par le worker, notification à la page.

- Les commandes sont importées comme par l'ETL horaire (même nettoyage, même validation,
  cible comprise) : l'import suivant les trouve « déjà présentes », sans doublon.
- Flux coupé : rien n'est lu en temps réel ; les commandes arrivent à l'import horaire,
  sans notification.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.abstraction.order_queue import OrderQueue
from src.abstraction.order_repository import OrderRepository
from src.abstraction.order_store import OrderStore
from src.domain.exceptions import RepositoryUnavailableError
from src.etl.erp_import import validated_row
from src.serving.events import order_created_event

logger = logging.getLogger(__name__)


class ErpUnavailableError(RuntimeError):
    """L'ERP ne répond pas : le flux ne peut pas être activé."""


class ErpStream:
    """Connecteur ERP -> file des commandes, activable et désactivable à chaud."""

    def __init__(
        self,
        source_factory: Callable[[], OrderRepository],
        store: OrderStore,
        queue: OrderQueue,
        poll_seconds: float = 2.0,
        batch_size: int = 100,
    ) -> None:
        self._source_factory = source_factory
        self._store = store
        self._queue = queue
        self._poll_seconds = poll_seconds
        self._batch_size = batch_size
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._source: OrderRepository | None = None
        self._since: datetime | None = None
        self._position: str | None = None
        self._received = 0

    @property
    def active(self) -> bool:
        """Vrai si le flux est activé."""
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        """État du flux, au format du contrat `ErpStreamStatus`."""
        with self._lock:
            return self._unlocked_status()

    def start(self) -> dict[str, Any]:
        """Active le flux à partir de la dernière commande de l'ERP (rien d'antérieur)."""
        with self._lock:
            if self.active:
                return self._unlocked_status()
            source = self._source_factory()
            try:
                if not source.ping():
                    raise ErpUnavailableError("ERP injoignable.")
                position = source.latest_order_id()
            except (RepositoryUnavailableError, ErpUnavailableError) as error:
                _close(source)
                raise ErpUnavailableError("ERP injoignable.") from error

            self._source, self._position = source, position
            self._since, self._received = datetime.now(UTC), 0
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="erp-stream", daemon=True)
            self._thread.start()
            logger.info("Flux ERP activé après la commande %s.", position)
            return self._unlocked_status()

    def stop(self) -> dict[str, Any]:
        """Coupe le flux (les commandes suivantes arriveront par l'import horaire)."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._poll_seconds + 5)
        with self._lock:
            self._thread = None
            _close(self._source)
            self._source = None
            if self._since is not None:
                logger.info("Flux ERP coupé (%d commandes reçues).", self._received)
            return self._unlocked_status()

    def _unlocked_status(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "since": self._since,
            "last_order_id": self._position,
            "received": self._received,
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except RepositoryUnavailableError:
                logger.warning("ERP injoignable : nouvelle tentative au prochain passage.")
            except Exception:  # pylint: disable=broad-exception-caught  # le flux ne s'arrête pas
                logger.exception("Erreur inattendue dans le flux ERP.")
            self._stop.wait(self._poll_seconds)

    def poll_once(self) -> int:
        """Lit et traite les nouvelles commandes de l'ERP ; retourne le nombre d'importées."""
        if self._source is None:
            return 0
        batch = self._source.get_labeled_after(self._position, self._batch_size)
        imported = 0
        for order, label in batch:
            row, errors = validated_row(order, label)
            if row is None:
                logger.warning("Commande ERP %s ignorée : %s", order.order_id, "; ".join(errors))
            elif self._store.import_orders([row]):
                # Nouvelle commande : même suite qu'une commande reçue par l'API.
                self._queue.publish(order_created_event(row))
                imported += 1
            with self._lock:
                self._position = order.order_id or self._position
        with self._lock:
            self._received += imported
        return imported


def _close(source: OrderRepository | None) -> None:
    close = getattr(source, "close", None)
    if callable(close):
        close()
