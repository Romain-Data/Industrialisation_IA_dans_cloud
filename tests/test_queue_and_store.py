from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from src.abstraction.order_queue import OrderQueue
from src.abstraction.order_store import DuplicateOrderError
from src.infrastructure.dev.order_queue import InMemoryOrderQueue
from src.infrastructure.order_store import SqlAlchemyOrderStore
from src.serving.worker import OrderWorker
from tests.conftest import FakeModel


@pytest.fixture
def store(database_url):
    return SqlAlchemyOrderStore(database_url)


@pytest.fixture
def order(valid_order):
    return {"order_id": "CMD-000001", **valid_order}


def make_prediction(order_id="CMD-000001", probability=0.8):
    return {
        "order_id": order_id,
        "express_eligible": True,
        "decision": "oui",
        "probability": probability,
        "model_version": "1.0.0",
        "predicted_at": datetime.now(UTC),
        "latency_ms": 1.5,
    }


def make_event(order):
    return {"event_id": "evt-1", "event_type": "order.created", "order": order}


def test_store_roundtrip(store, order):
    store.save(order)

    assert store.get("CMD-000001") == order


def test_store_unknown_order_returns_none(store):
    assert store.get("CMD-999") is None


def test_store_rejects_duplicate_order_id(store, order):
    store.save(order)

    with pytest.raises(DuplicateOrderError):
        store.save(order)


def test_store_rejects_invalid_flag(store, order):
    order["stock_available"] = 3

    with pytest.raises(IntegrityError):
        store.save(order)


def test_store_ping(store):
    assert store.ping() is True


def test_store_prediction_roundtrip_keeps_timezone(store):
    store.save_prediction(make_prediction())

    saved = store.get_prediction("CMD-000001")

    assert saved["decision"] == "oui"
    assert saved["predicted_at"].tzinfo is not None


def test_store_prediction_is_replaced(store):
    store.save_prediction(make_prediction(probability=0.8))
    store.save_prediction(make_prediction(probability=0.3))

    assert store.get_prediction("CMD-000001")["probability"] == 0.3


def test_store_unknown_prediction_returns_none(store):
    assert store.get_prediction("CMD-999") is None


def test_in_memory_queue_is_fifo():
    queue = InMemoryOrderQueue()
    assert isinstance(queue, OrderQueue)

    queue.publish({"n": 1})
    queue.publish({"n": 2})

    assert queue.consume(timeout=0) == {"n": 1}
    assert queue.consume(timeout=0) == {"n": 2}


def test_in_memory_queue_returns_none_when_empty():
    assert InMemoryOrderQueue().consume(timeout=0) is None


def test_worker_stores_prediction_of_queued_order(store, order):
    queue = InMemoryOrderQueue()
    worker = OrderWorker(queue, store, lambda: FakeModel(0.8))
    queue.publish(make_event(order))

    assert worker.process_one() is True

    prediction = store.get_prediction("CMD-000001")
    assert prediction["express_eligible"] is True
    assert prediction["probability"] == 0.8


def test_worker_returns_false_when_queue_is_empty(store):
    worker = OrderWorker(InMemoryOrderQueue(), store, lambda: FakeModel())

    assert worker.process_one() is False


def test_worker_skips_order_when_model_is_unavailable(store, order):
    queue = InMemoryOrderQueue()
    worker = OrderWorker(queue, store, lambda: None)
    queue.publish(make_event(order))

    worker.process_one()

    assert store.get_prediction("CMD-000001") is None


def test_worker_skips_invalid_order(store, order):
    queue = InMemoryOrderQueue()
    worker = OrderWorker(queue, store, lambda: FakeModel())
    order["carrier_capacity"] = 2
    queue.publish(make_event(order))

    assert worker.process_one() is True
    assert store.get_prediction("CMD-000001") is None


def test_worker_thread_starts_and_stops(store):
    worker = OrderWorker(InMemoryOrderQueue(), store, lambda: FakeModel())

    worker.start()
    assert worker.is_alive()

    worker.stop()
    assert not worker.is_alive()
