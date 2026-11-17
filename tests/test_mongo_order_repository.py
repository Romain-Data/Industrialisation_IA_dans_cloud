"""MongoOrderRepository contre un vrai MongoDB, alimenté comme le fait l'ERP (ADR-0007).

Contrat aligné sur la correction de l'enseignant : entités du domaine, erreurs du domaine.
MongoDB est lu à MONGO_TEST_URI. Sans cette variable, on tente mongodb://localhost:27017
et les tests sont ignorés s'il ne répond pas ; avec la variable (CI), ils échouent.
"""

import os
import uuid
from datetime import UTC, datetime

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from src.domain.entities import OrderEntity
from src.domain.exceptions import ReadOnlyRepositoryError, RepositoryUnavailableError
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
    """Base ERP jetable : 30 commandes historiques 2023+ et 10 commandes live, étiquetées."""
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


# --- Contrat de la correction : save, get, get_all, count, get_training_data -----------------


def test_get_returns_a_domain_entity(erp):
    order = erp["repository"].get("ERP-00000007")
    expected = erp["orders"][6]

    assert isinstance(order, OrderEntity)
    assert order.order_id == "ERP-00000007"
    assert order.weather == expected["weather"]
    assert order.carrier_capacity == expected["carrier_capacity"]
    assert order.order_date == datetime.combine(expected["order_date"], datetime.min.time(), UTC)


def test_the_target_is_not_part_of_the_entity(erp):
    assert not hasattr(erp["repository"].get("ERP-00000001"), "express_eligible")


def test_get_unknown_order_returns_none(erp):
    assert erp["repository"].get("ERP-99999999") is None


def test_get_all_is_sorted_by_order_id(erp):
    orders = erp["repository"].get_all()

    assert [o.order_id for o in orders] == sorted(o["order_id"] for o in erp["orders"])


def test_count(erp):
    assert erp["repository"].count() == 40


def test_save_is_refused_with_a_domain_error(erp):
    with pytest.raises(ReadOnlyRepositoryError):
        erp["repository"].save(erp["repository"].get("ERP-00000001"))
    assert erp["repository"].count() == 40


def test_training_data_pairs_each_order_with_its_target(erp):
    orders, labels = erp["repository"].get_training_data()
    expected = {o["order_id"]: o["express_eligible"] for o in erp["orders"]}

    assert len(orders) == len(labels) == 40
    assert [expected[o.order_id] for o in orders] == labels


def test_training_data_skips_orders_without_target(erp):
    erp["collection"].update_one({"order_id": "ERP-00000003"}, {"$unset": {"express_eligible": ""}})

    orders, labels = erp["repository"].get_training_data()

    assert len(orders) == len(labels) == 39
    assert "ERP-00000003" not in {o.order_id for o in orders}


# --- Import incrémental (ETL) ------------------------------------------------------------


def test_get_labeled_after_starts_strictly_after_the_last_imported_order(erp):
    batch = erp["repository"].get_labeled_after("ERP-00000030", limit=5)

    assert [order.order_id for order, _ in batch] == [f"ERP-{n:08d}" for n in range(31, 36)]
    assert all(label in (0, 1) for _, label in batch)


def test_get_labeled_after_none_starts_from_the_beginning(erp):
    assert erp["repository"].get_labeled_after(None, limit=1)[0][0].order_id == "ERP-00000001"


def test_missing_target_is_returned_as_none(erp):
    erp["collection"].update_one({"order_id": "ERP-00000001"}, {"$unset": {"express_eligible": ""}})

    assert erp["repository"].get_labeled_after(None, limit=1)[0][1] is None


def test_incremental_reading_sees_every_order_once(erp):
    seen, last = [], None
    while batch := erp["repository"].get_labeled_after(last, limit=7):
        seen += [order.order_id for order, _ in batch]
        last = batch[-1][0].order_id

    assert len(seen) == len(set(seen)) == 40


def test_new_erp_orders_are_picked_up_after_the_last_one(erp):
    # Nouvelles commandes écrites avec la même conversion que l'ERP.
    new_orders = erp_generator.OrderGenerator().live_batch(41, 3, TODAY)
    erp["collection"].insert_many([erp_storage.MongoWriter._document(o) for o in new_orders])

    batch = erp["repository"].get_labeled_after("ERP-00000040", 10)

    assert [order.order_id for order, _ in batch] == ["ERP-00000041", "ERP-00000042", "ERP-00000043"]


def test_incomplete_document_is_left_to_the_etl(erp):
    erp["collection"].update_one({"order_id": "ERP-00000002"}, {"$unset": {"weather": ""}})

    assert erp["repository"].get("ERP-00000002").weather is None


# --- Lecture seule et erreurs du domaine -----------------------------------------------------


def test_reading_never_modifies_the_erp_collection(erp):
    before = list(erp["collection"].find({}, {"_id": 0}).sort("order_id"))
    repository = erp["repository"]

    repository.get("ERP-00000001")
    repository.get_all()
    repository.count()
    repository.get_training_data()
    repository.get_labeled_after(None, limit=100)

    assert list(erp["collection"].find({}, {"_id": 0}).sort("order_id")) == before


def test_ping(erp):
    assert erp["repository"].ping() is True


def test_unreachable_mongodb_raises_a_domain_error():
    repository = MongoOrderRepository("mongodb://localhost:1", timeout_ms=200)

    assert repository.ping() is False
    with pytest.raises(RepositoryUnavailableError, match="injoignable"):
        repository.get("ERP-00000001")
    repository.close()


# --- ETL de bout en bout depuis MongoDB ------------------------------------------------------


def test_etl_imports_mongodb_orders_into_our_database(erp, database_url):
    from src.etl.erp_import import import_erp_orders
    from src.infrastructure.import_journal import SqlAlchemyImportJournal
    from src.infrastructure.order_store import SqlAlchemyOrderStore

    store = SqlAlchemyOrderStore(database_url)
    journal = SqlAlchemyImportJournal(database_url)

    report = import_erp_orders(erp["repository"], store, journal, batch_size=12)
    rerun = import_erp_orders(erp["repository"], store, journal)

    assert (report.read, report.imported, report.rejected) == (40, 40, 0)
    assert rerun.read == 0
    assert len(store.export_labeled_orders()) == 40
