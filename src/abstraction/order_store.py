"""Contrat de stockage de nos propres commandes et prédictions (ADR-0001)."""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class DuplicateOrderError(Exception):
    """Une commande avec cet identifiant existe déjà."""


class OrderStore(ABC):
    """Stockage de nos commandes, de leur résultat réel et de leurs prédictions."""

    @abstractmethod
    def save(self, order: dict[str, Any]) -> None:
        """Enregistre une commande. Lève DuplicateOrderError si order_id existe."""

    @abstractmethod
    def get(self, order_id: str) -> dict[str, Any] | None:
        """Retourne la commande, ou None si elle est inconnue."""

    @abstractmethod
    def record_outcome(self, order_id: str, express_eligible: bool) -> dict[str, Any] | None:
        """Enregistre le résultat observé d'une commande (cible d'entraînement).

        Retourne le résultat enregistré, ou None si la commande est inconnue.
        """

    @abstractmethod
    def export_labeled_orders(self) -> pd.DataFrame:
        """Commandes dont le résultat est connu, au format d'entraînement.

        Colonnes : order_id, order_date, les FEATURE_COLUMNS et la cible.
        """

    @abstractmethod
    def count_labeled_orders(self) -> int:
        """Nombre de commandes dont le résultat réel (la cible) est connu."""

    @abstractmethod
    def import_orders(self, orders: list[dict[str, Any]]) -> int:
        """Insère des commandes importées, en ignorant celles déjà présentes (même order_id).

        Chaque commande porte ses caractéristiques, `created_at` (date de la source) et
        `express_eligible` (cible, ou None). Retourne le nombre de commandes insérées.
        """

    @abstractmethod
    def last_order_id(self, prefix: str) -> str | None:
        """Plus grand identifiant de commande commençant par `prefix`, ou None."""

    @abstractmethod
    def ping(self) -> bool:
        """Indique si le stockage est joignable."""

    @abstractmethod
    def schema_is_current(self) -> bool:
        """Indique si le schéma du stockage est à jour des migrations."""

    @abstractmethod
    def save_prediction(self, prediction: dict[str, Any]) -> None:
        """Enregistre (ou remplace) la prédiction d'une commande."""

    @abstractmethod
    def get_prediction(self, order_id: str) -> dict[str, Any] | None:
        """Retourne la prédiction de la commande, ou None si elle n'existe pas."""

    @abstractmethod
    def recent_predictions(self, limit: int) -> list[dict[str, Any]]:
        """Retourne les `limit` dernières prédictions, de la plus récente à la plus ancienne."""
