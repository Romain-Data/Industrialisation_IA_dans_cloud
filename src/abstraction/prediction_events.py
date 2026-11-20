"""Contrat de diffusion des prédictions calculées (ADR-0013).

Le worker publie un événement `prediction.created` par prédiction enregistrée ; l'API
les écoute pour les relayer en temps réel aux navigateurs (page du logisticien).
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

PredictionListener = Callable[[dict[str, Any]], None]


class PredictionEvents(ABC):
    """Diffusion « un vers plusieurs » des événements de prédiction."""

    @abstractmethod
    def publish(self, event: dict[str, Any]) -> None:
        """Diffuse un événement à tous les auditeurs."""

    @abstractmethod
    def listen(self, listener: PredictionListener) -> None:
        """Appelle `listener` pour chaque événement reçu, jusqu'à `close()`.

        L'appel peut venir d'un autre thread : `listener` doit être sûr entre threads.
        """

    def ping(self) -> bool:
        """Vrai si la diffusion est joignable. Toujours vrai en mémoire."""
        return True

    def close(self) -> None:  # rien à libérer par défaut
        """Arrête l'écoute et libère les connexions."""
