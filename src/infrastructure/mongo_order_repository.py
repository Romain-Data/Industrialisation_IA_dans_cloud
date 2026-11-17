"""Lecture des commandes ERP dans MongoDB, la base analytique de l'entreprise (ADR-0007)."""

from datetime import UTC

from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError

from src.abstraction.order_repository import OrderRepository


class MongoOrderRepository(OrderRepository):
    """Implémentation MongoDB du contrat OrderRepository, en lecture seule.

    Seules des lectures (`find`, `find_one`) sont faites : MongoDB n'ayant pas
    d'authentification dans l'ERP, rien n'empêche techniquement d'écrire, c'est
    donc ce code qui garantit la lecture seule.

    Les identifiants ERP (`ERP-00000001`) sont de longueur fixe : leur ordre
    alphabétique est leur ordre de création, ce qui permet l'import incrémental.
    """

    def __init__(self, uri, database="livraison_express", collection="orders", timeout_ms=5000):
        self._client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms, tz_aware=True)
        self._collection = self._client[database][collection]

    def get(self, order_id):
        return self._to_order(self._collection.find_one({"order_id": order_id}, {"_id": 0}))

    def get_all(self, limit=None):
        cursor = self._collection.find({}, {"_id": 0}).sort("order_id", ASCENDING)
        if limit is not None:
            cursor = cursor.limit(limit)
        return [self._to_order(document) for document in cursor]

    def get_after(self, last_order_id, limit):
        query = {"order_id": {"$gt": last_order_id}} if last_order_id else {}
        cursor = (
            self._collection.find(query, {"_id": 0})
            .sort("order_id", ASCENDING)
            .limit(limit)
        )
        return [self._to_order(document) for document in cursor]

    def ping(self):
        try:
            self._client.admin.command("ping")
        except PyMongoError:
            return False
        return True

    def close(self):
        """Ferme les connexions au serveur MongoDB."""
        self._client.close()

    @staticmethod
    def _to_order(document):
        """Document MongoDB -> commande brute (types Python, dates en UTC)."""
        if document is None:
            return None

        order = dict(document)
        order_date = order.get("order_date")
        if order_date is not None and order_date.tzinfo is None:
            order["order_date"] = order_date.replace(tzinfo=UTC)
        return order
