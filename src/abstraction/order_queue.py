from abc import ABC, abstractmethod


class OrderQueue(ABC):

    @abstractmethod
    def publish(self, event: dict) -> None:
        """Met un événement (contrat OrderEvent) en file d'attente."""

    @abstractmethod
    def consume(self, timeout: float = 1.0) -> dict | None:
        """Retire le plus ancien événement, ou None si la file reste vide."""
