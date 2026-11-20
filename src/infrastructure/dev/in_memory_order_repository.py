"""OrderRepository en mémoire : dev et tests, sans base de données (comme la correction).

Limites : données perdues au redémarrage, rien de partagé entre processus. Très bien pour
un test unitaire, inacceptable en production.
"""

from src.abstraction.order_repository import OrderRepository
from src.domain.entities import OrderEntity


class InMemoryOrderRepository(OrderRepository):
    """Commandes et cibles dans des dictionnaires, triées par identifiant à la lecture."""

    def __init__(self, labeled_orders: list[tuple[OrderEntity, int | None]] | None = None) -> None:
        self._orders: dict[str, OrderEntity] = {}
        self._labels: dict[str, int | None] = {}
        for order, label in labeled_orders or []:
            self._orders[order.order_id] = order
            self._labels[order.order_id] = label

    def save(self, order: OrderEntity) -> None:
        self._orders[order.order_id] = order
        self._labels.setdefault(order.order_id, None)

    def get(self, order_id: str) -> OrderEntity | None:
        return self._orders.get(order_id)

    def get_all(self) -> list[OrderEntity]:
        return [self._orders[key] for key in sorted(self._orders)]

    def count(self) -> int:
        return len(self._orders)

    def get_training_data(self) -> tuple[list[OrderEntity], list[int]]:
        labeled = [order for order in self.get_all() if self._labels[order.order_id] is not None]
        return labeled, [self._labels[order.order_id] for order in labeled]

    def get_labeled_after(
        self, last_order_id: str | None, limit: int
    ) -> list[tuple[OrderEntity, int | None]]:
        keys = [key for key in sorted(self._orders) if last_order_id is None or key > last_order_id]
        return [(self._orders[key], self._labels[key]) for key in keys[:limit]]

    def ping(self) -> bool:
        return True
