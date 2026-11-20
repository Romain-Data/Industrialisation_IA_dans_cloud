"""Contrat de lecture des commandes d'un système source (ERP), aligné sur la correction."""

from abc import ABC, abstractmethod

from src.domain.entities import OrderEntity


class OrderRepository(ABC):
    """Commandes d'un système source, exposées en entités du domaine.

    Contrat de la correction de l'enseignant (`save`, `get`, `get_all`, `count`,
    `get_training_data`), plus la lecture incrémentale utile à l'ETL et une sonde.

    - `get` renvoie None pour un identifiant inconnu, sans lever d'exception ;
    - les erreurs levées sont celles de `src.domain.exceptions`, jamais celles de
      la bibliothèque de stockage : l'application ne connaît pas l'infrastructure ;
    - la cible n'est pas dans `OrderEntity` : elle est fournie à part.
    """

    @abstractmethod
    def save(self, order: OrderEntity) -> None:
        """Enregistre une commande sans créer de doublon (clé : order_id).

        Un dépôt en lecture seule lève ReadOnlyRepositoryError.
        """

    @abstractmethod
    def get(self, order_id: str) -> OrderEntity | None:
        """Retourne la commande, ou None si elle est inconnue."""

    @abstractmethod
    def get_all(self) -> list[OrderEntity]:
        """Retourne toutes les commandes, triées par identifiant."""

    @abstractmethod
    def count(self) -> int:
        """Retourne le nombre de commandes."""

    @abstractmethod
    def get_training_data(self) -> tuple[list[OrderEntity], list[int]]:
        """Retourne les commandes qui ont une cible, et leurs cibles dans le même ordre."""

    @abstractmethod
    def get_labeled_after(
        self, last_order_id: str | None, limit: int
    ) -> list[tuple[OrderEntity, int | None]]:
        """Au plus `limit` commandes d'identifiant strictement supérieur à `last_order_id`.

        Chaque commande est accompagnée de sa cible (None si elle n'en a pas).
        Sert à l'import incrémental : on reprend après la dernière commande importée.
        """

    @abstractmethod
    def latest_order_id(self) -> str | None:
        """Identifiant de la commande la plus récente (le plus grand), ou None si aucune.

        Sert au flux temps réel : à l'activation, on ne lit que les commandes arrivées ensuite.
        """

    @abstractmethod
    def ping(self) -> bool:
        """Indique si le système source est joignable."""
