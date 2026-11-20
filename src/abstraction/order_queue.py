"""Contrat de la file d'attente des commandes à prédire (ADR-0006, ADR-0013)."""

from abc import ABC, abstractmethod
from typing import Any


class OrderQueue(ABC):
    """File d'événements `order.created` entre l'API (producteur) et le worker (consommateur)."""

    @abstractmethod
    def publish(self, event: dict[str, Any]) -> None:
        """Publie un événement de commande."""

    @abstractmethod
    def consume(self, timeout: float = 1.0) -> dict[str, Any] | None:
        """Retourne le prochain événement, ou None si la file reste vide pendant `timeout` s."""

    def ping(self) -> bool:
        """Vrai si la file est joignable (sonde /health/ready). Toujours vrai en mémoire."""
        return True

    def close(self) -> None:  # rien à libérer par défaut
        """Libère les connexions (arrêt de l'API)."""
