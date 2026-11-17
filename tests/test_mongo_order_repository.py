"""MongoOrderRepository contre un vrai MongoDB, alimenté comme le fait l'ERP (ADR-0007).

MongoDB est lu à MONGO_TEST_URI. Sans cette variable, on tente mongodb://localhost:27017
et les tests sont ignorés s'il ne répond pas ; avec la variable (CI), ils échouent.
"""

import os
import uuid
from datetime import UTC, datetime

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from src.infrastructure.mongo_order_repository import MongoOrderRepository
from tests.erp_simulator import TODAY, load_erp_module

erp_generator = load_erp_module("generator")
erp_storage = load_erp_module("storage")


@pytest.fixture(scope="module")
def mongo_uri():
    uri = os.getenv("MONGO_TEST_URI")
    try:
        client = MongoClient(uri or "mongodb://localhost:27017", serverSelectionTimeoutMS=1000)
        client.admin.command("ping")
        client.close()
    except PyMongoError:
        if uri:
            raise
        pytest.skip("MongoDB indisponible (définir MONGO_TEST_URI ou lancer un MongoDB local).")
    return uri or "mongodb://localhost:27017"


@pytest.fixture
def erp(mongo_uri):
    """Base ERP jetable : 30 commandes historiques 2023+ et 10 commandes live."""
    database = f"test_erp_{uuid.uuid4().hex[:8]}"
    writer = erp_storage.MongoWriter(mongo_uri)
    writer.collection = writer.client[database]["orders"]
    writer.collection.create_index("order_id", unique=True)

    generator = erp_generator.OrderGenerator()
    orders = generator.recent_history(30, TODAY, first_sequence=1)
    orders += generator.live_batch(31, 10, TODAY)
    writer.write(orders)

    repository = MongoOrderRepository(mongo_uri, database=database)
    yield {"repository": repository, "collection": writer.collection, "orders": orders}

    repository.close()
    writer.client.drop_database(database)
    writer.close()


def test_get_returns_the_raw_erp_order(erp):
    order = erp["repository"].get("ERP-00000007")
    expected = erp["orders"][6]

    assert "_id" not in order
    assert order["order_id"] == "ERP-00000007"
    assert order["weather"] == expected["weather"]
    assert order["carrier_capacity"] == expected["carrier_capacity"]
    assert order["order_date"] == datetime.combine(expected["order_date"], datetime.min.time(), UTC)


def test_get_unknown_order_returns_none(erp):
    assert erp["repository"].get("ERP-99999999") is None


def test_get_all_is_sorted_by_order_id(erp):
    orders = erp["repository"].get_all()

    assert len(orders) == 40
    assert [o["order_id"] for o in orders] == sorted(o["order_id"] for o in erp["orders"])


def test_get_all_respects_limit(erp):
    assert [o["order_id"] for o in erp["repository"].get_all(limit=3)] == [
        "ERP-00000001",
        "ERP-00000002",
        "ERP-00000003",
    ]


def test_get_after_starts_strictly_after_the_last_imported_order(erp):
    orders = erp["repository"].get_after("ERP-00000030", limit=5)

    assert [o["order_id"] for o in orders] == [f"ERP-{n:08d}" for n in range(31, 36)]


def test_get_after_none_starts_from_the_beginning(erp):
    assert erp["repository"].get_after(None, limit=1)[0]["order_id"] == "ERP-00000001"


def test_incremental_reading_sees_every_order_once(erp):
    seen, last = [], None
    while batch := erp["repository"].get_after(last, limit=7):
        seen += [o["order_id"] for o in batch]
        last = batch[-1]["order_id"]

    assert len(seen) == len(set(seen)) == 40


def test_new_erp_orders_are_picked_up_after_the_last_one(erp):
    # Nouvelles commandes écrites avec la même conversion que l'ERP.
    new_orders = erp_generator.OrderGenerator().live_batch(41, 3, TODAY)
    erp["collection"].insert_many([erp_storage.MongoWriter._document(o) for o in new_orders])

    assert [o["order_id"] for o in erp["repository"].get_after("ERP-00000040", 10)] == [
        "ERP-00000041",
        "ERP-00000042",
        "ERP-00000043",
    ]


def test_reading_never_modifies_the_erp_collection(erp):
    before = list(erp["collection"].find({}, {"_id": 0}).sort("order_id"))
    repository = erp["repository"]

    repository.get("ERP-00000001")
    repository.get_all()
    repository.get_after(None, limit=100)

    assert list(erp["collection"].find({}, {"_id": 0}).sort("order_id")) == before


def test_ping(erp):
    assert erp["repository"].ping() is True


def test_ping_fails_when_mongodb_is_unreachable():
    repository = MongoOrderRepository("mongodb://localhost:1", timeout_ms=200)

    assert repository.ping() is False
    repository.close()
