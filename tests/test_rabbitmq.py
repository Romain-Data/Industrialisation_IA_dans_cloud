"""Implémentations RabbitMQ contre un vrai broker (ADR-0013).

Ignorés sans RABBITMQ_TEST_URL : la CI fournit un service RabbitMQ (comme MongoDB).
Chaque test utilise ses propres noms de file et d'échange.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.rabbitmq import RabbitMQOrderQueue, RabbitMQPredictionEvents
from src.serving.api import create_app
from tests.conftest import NO_RELOAD, FakeModel, wait_for

RABBITMQ_URL = os.getenv("RABBITMQ_TEST_URL")

pytestmark = pytest.mark.skipif(not RABBITMQ_URL, reason="RABBITMQ_TEST_URL non défini")


@pytest.fixture
def queue():
    order_queue = RabbitMQOrderQueue(RABBITMQ_URL, queue=f"test-orders-{uuid.uuid4().hex[:8]}")
    yield order_queue
    order_queue.close()


@pytest.fixture
def events():
    prediction_events = RabbitMQPredictionEvents(
        RABBITMQ_URL, exchange=f"test-predictions-{uuid.uuid4().hex[:8]}"
    )
    yield prediction_events
    prediction_events.close()


def test_order_queue_round_trip_keeps_order(queue):
    queue.publish({"event_id": "1"})
    queue.publish({"event_id": "2"})

    assert queue.consume(timeout=1) == {"event_id": "1"}
    assert queue.consume(timeout=1) == {"event_id": "2"}
    assert queue.consume(timeout=0.1) is None


def test_order_queue_ping(queue):
    assert queue.ping() is True


def test_unreachable_broker_is_reported():
    unreachable = RabbitMQOrderQueue("amqp://guest:guest@127.0.0.1:1/%2F", queue="nowhere")

    assert unreachable.ping() is False


def test_messages_survive_a_new_consumer(queue):
    """Un événement publié reste dans la file durable jusqu'à sa consommation."""
    queue.publish({"event_id": "durable"})
    queue.close()

    other = RabbitMQOrderQueue(RABBITMQ_URL, queue=queue._queue)  # même file
    try:
        assert other.consume(timeout=1) == {"event_id": "durable"}
    finally:
        other.close()


def test_prediction_events_reach_every_listener(events):
    first, second = [], []
    events.listen(first.append)
    events.listen(second.append)
    # Les files exclusives sont liées à l'échange de façon asynchrone : on republie
    # jusqu'à ce que les deux auditeurs soient branchés.
    def delivered():
        events.publish({"event_id": "p1"})
        return True if first and second else None

    assert wait_for(delivered, timeout=10)
    assert first[0] == {"event_id": "p1"}
    assert second[0] == {"event_id": "p1"}


def test_api_with_rabbitmq_end_to_end(database_url, valid_order):
    """Commande -> file RabbitMQ -> worker -> prédiction -> échange -> relais SSE."""
    app = create_app(database_url, model_loader=FakeModel, rabbitmq_url=RABBITMQ_URL, **NO_RELOAD)
    with TestClient(app) as client:
        assert client.get("/health/ready").json()["checks"]["queue"] == "reachable"

        order_id = client.post("/v1/orders", json=valid_order).json()["order_id"]
        prediction = wait_for(
            lambda: client.get(f"/v1/predictions/{order_id}").json().get("order_id"), timeout=10
        )

    assert prediction == order_id
