"""Contrat de lecture des commandes d'un système source (ERP), ADR-0007."""

from abc import ABC, abstractmethod


class OrderRepository(ABC):
    """Commandes d'un système source, en lecture seule.

    Contrairement à OrderStore (nos propres commandes), ce dépôt ne fait que lire :
    l'application n'écrit jamais dans la base de l'ERP (ADR-0007). Les commandes sont
    renvoyées brutes, au format du système source ; leur validation et leur nettoyage
    sont faits par l'ETL qui les importe.
    """

    @abstractmethod
    def get(self, order_id: str) -> dict | None:
        """Retourne la commande, ou None si elle est inconnue."""

    @abstractmethod
    def get_all(self, limit: int | None = None) -> list[dict]:
        """Retourne les commandes triées par identifiant (toutes, ou les `limit` premières)."""

    @abstractmethod
    def get_after(self, last_order_id: str | None, limit: int) -> list[dict]:
        """Retourne au plus `limit` commandes d'identifiant strictement supérieur à `last_order_id`.

        Sert à l'import incrémental : on reprend après la dernière commande importée.
        Avec None, on part du début.
        """

    @abstractmethod
    def ping(self) -> bool:
        """Indique si le système source est joignable."""
