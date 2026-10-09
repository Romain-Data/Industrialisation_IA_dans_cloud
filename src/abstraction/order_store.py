from abc import ABC, abstractmethod


class DuplicateOrderError(Exception):
    """Une commande avec cet identifiant existe déjà."""


class OrderStore(ABC):

    @abstractmethod
    def save(self, order: dict) -> None:
        """Enregistre une commande. Lève DuplicateOrderError si order_id existe."""

    @abstractmethod
    def get(self, order_id: str) -> dict | None:
        """Retourne la commande, ou None si elle est inconnue."""

    @abstractmethod
    def ping(self) -> bool:
        """Indique si le stockage est joignable."""

    @abstractmethod
    def schema_is_current(self) -> bool:
        """Indique si le schéma du stockage est à jour des migrations."""

    @abstractmethod
    def save_prediction(self, prediction: dict) -> None:
        """Enregistre (ou remplace) la prédiction d'une commande."""

    @abstractmethod
    def get_prediction(self, order_id: str) -> dict | None:
        """Retourne la prédiction de la commande, ou None si elle n'existe pas."""
