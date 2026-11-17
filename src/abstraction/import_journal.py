"""Contrat du journal des imports ETL : position de reprise et historique des passages."""

from abc import ABC, abstractmethod


class ImportJournal(ABC):
    """Journal des imports d'une source de commandes."""

    @abstractmethod
    def last_order_id(self, source: str) -> str | None:
        """Identifiant de la dernière commande lue au dernier import de `source` (None sinon)."""

    @abstractmethod
    def record(self, source: str, report) -> None:
        """Enregistre le compte rendu d'un import (ImportReport)."""
