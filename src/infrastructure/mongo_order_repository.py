"""Lecture des commandes ERP dans MongoDB, la base analytique de l'entreprise (ADR-0007)."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import fields
from datetime import UTC
from typing import Any, Never

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

from src.abstraction.order_repository import OrderRepository
from src.domain.entities import OrderEntity
from src.domain.exceptions import ReadOnlyRepositoryError, RepositoryUnavailableError
from src.domain.features import TARGET_COLUMN

ENTITY_FIELDS = {field.name for field in fields(OrderEntity)}
NO_ID = {"_id": 0}


@contextmanager
def _domain_errors() -> Iterator[None]:
    """Traduit les erreurs pymongo en erreur du domaine (sans détail technique)."""
    try:
        yield
    except PyMongoError as error:
        raise RepositoryUnavailableError("Base des commandes ERP injoignable.") from error


class MongoOrderRepository(OrderRepository):
    """Implémentation MongoDB du contrat OrderRepository, en lecture seule.

    Seules des lectures sont faites : MongoDB n'ayant pas d'authentification dans
    l'ERP, rien n'empêche techniquement d'écrire, c'est donc ce code qui garantit
    la lecture seule (`save` est refusé).

    Les identifiants ERP (`ERP-00000001`) sont de longueur fixe : leur ordre
    alphabétique est leur ordre de création, ce qui permet l'import incrémental.
    """

    def __init__(
        self,
        uri: str,
        database: str = "livraison_express",
        collection: str = "orders",
        timeout_ms: int = 5000,
    ) -> None:
        self._client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms, tz_aware=True)
        self._collection = self._client[database][collection]

    def save(self, order: OrderEntity) -> Never:
        raise ReadOnlyRepositoryError(
            "La base de l'ERP est en lecture seule : l'application n'y écrit jamais (ADR-0007)."
        )

    def get(self, order_id: str) -> OrderEntity | None:
        with _domain_errors():
            document = self._collection.find_one({"order_id": order_id}, NO_ID)
        return None if document is None else self._to_entity(document)

    def get_all(self) -> list[OrderEntity]:
        with _domain_errors():
            documents = list(self._collection.find({}, NO_ID).sort("order_id", ASCENDING))
        return [self._to_entity(document) for document in documents]

    def count(self) -> int:
        with _domain_errors():
            return self._collection.count_documents({})

    def get_training_data(self) -> tuple[list[OrderEntity], list[int]]:
        query = {TARGET_COLUMN: {"$in": [0, 1]}}
        with _domain_errors():
            documents = list(self._collection.find(query, NO_ID).sort("order_id", ASCENDING))
        return (
            [self._to_entity(document) for document in documents],
            [int(document[TARGET_COLUMN]) for document in documents],
        )

    def get_labeled_after(
        self, last_order_id: str | None, limit: int
    ) -> list[tuple[OrderEntity, int | None]]:
        query = {"order_id": {"$gt": last_order_id}} if last_order_id else {}
        with _domain_errors():
            documents = list(
                self._collection.find(query, NO_ID).sort("order_id", ASCENDING).limit(limit)
            )
        return [(self._to_entity(document), self._label(document)) for document in documents]

    def latest_order_id(self) -> str | None:
        with _domain_errors():
            document = self._collection.find_one({}, {"order_id": 1, "_id": 0}, sort=[("order_id", DESCENDING)])
        return None if document is None else document["order_id"]

    def ping(self) -> bool:
        try:
            self._client.admin.command("ping")
        except PyMongoError:
            return False
        return True

    def close(self) -> None:
        """Ferme les connexions au serveur MongoDB."""
        self._client.close()

    @staticmethod
    def _label(document: Mapping[str, Any]) -> int | None:
        """Cible du document : 0, 1, ou None si elle est absente (anciennes commandes)."""
        label = document.get(TARGET_COLUMN)
        return None if label is None else int(label)

    @staticmethod
    def _to_entity(document: Mapping[str, Any]) -> OrderEntity:
        """Document MongoDB -> OrderEntity (champs du domaine seulement, dates en UTC).

        Pas de validation ici : un document incomplet ou invalide est signalé par
        l'ETL qui l'importe, pas masqué par le dépôt.
        """
        # Champ absent -> None : l'ETL rejettera la commande à la validation.
        values = {name: document.get(name) for name in ENTITY_FIELDS}
        order_date = values.get("order_date")
        if order_date is not None and order_date.tzinfo is None:
            values["order_date"] = order_date.replace(tzinfo=UTC)
        return OrderEntity(**values)
