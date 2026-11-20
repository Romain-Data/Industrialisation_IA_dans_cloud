"""Flux temps réel du logisticien (ADR-0013) : diffusion, SSE, historique, démonstration."""

import asyncio
import threading
from pathlib import Path

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from src.domain.validation import validate_order
from src.infrastructure.dev.demo_orders import DEMO_PREFIX, demo_orders
from src.infrastructure.dev.order_queue import InMemoryOrderQueue
from src.infrastructure.dev.prediction_events import InMemoryPredictionEvents
from src.serving.api import create_app
from src.serving.broadcaster import SseBroadcaster, event_stream, format_sse
from src.serving.schemas import OrderFeatures, PredictionEvent
from tests.conftest import NO_RELOAD, FakeModel, wait_for

CONTRACT = yaml.safe_load(
    (Path(__file__).parent.parent / "openapi.yml").read_text(encoding="utf-8")
)


def make_client(database_url, **kwargs):
    app = create_app(database_url, model_loader=FakeModel, rabbitmq_url=None, **NO_RELOAD, **kwargs)
    return TestClient(app)


# --- Diffusion des prédictions -------------------------------------------------------


def test_worker_publishes_a_prediction_event(database_url, valid_order):
    events = InMemoryPredictionEvents()
    received = []
    events.listen(received.append)

    with make_client(database_url, prediction_events=events) as client:
        order_id = client.post("/v1/orders", json=valid_order).json()["order_id"]
        event = wait_for(lambda: received[0] if received else None)

    assert event["event_type"] == "prediction.created"
    assert event["prediction"]["order_id"] == order_id
    assert event["prediction"]["decision"] == "oui"
    PredictionEvent(**event)  # conforme au contrat


def test_in_memory_events_isolate_a_failing_listener():
    events = InMemoryPredictionEvents()
    received = []

    def broken(_event):
        raise RuntimeError("boom")

    events.listen(broken)
    events.listen(received.append)
    events.publish({"event_id": "1"})

    assert received == [{"event_id": "1"}]


def test_prediction_event_matches_contract():
    generated = PredictionEvent.model_json_schema()
    expected = CONTRACT["components"]["schemas"]["PredictionEvent"]

    assert set(generated["properties"]) == set(expected["properties"])
    assert set(expected["required"]) <= set(generated["required"])


# --- Relais SSE -----------------------------------------------------------------------


def test_format_sse_has_id_type_and_json_data():
    message = format_sse({"event_id": "abc", "event_type": "prediction.created", "x": 1})

    assert message.startswith("id: abc\nevent: prediction.created\ndata: {")
    assert message.endswith("\n\n")


def test_event_stream_relays_events_from_another_thread():
    async def scenario():
        broadcaster = SseBroadcaster()
        disconnected = asyncio.Event()

        async def is_disconnected():
            return disconnected.is_set()

        stream = event_stream(broadcaster, is_disconnected, keepalive_seconds=0.05)
        assert (await anext(stream)).startswith("retry:")

        reader = asyncio.ensure_future(anext(stream))
        while broadcaster.subscriber_count == 0:  # abonné une fois le flux démarré
            await asyncio.sleep(0.01)
        event = {"event_id": "e1", "event_type": "prediction.created"}
        threading.Thread(target=broadcaster.dispatch, args=(event,)).start()

        messages = [await reader]
        while "e1" not in messages[-1]:  # des keepalive peuvent précéder l'événement
            messages.append(await anext(stream))
        assert messages[-1].startswith("id: e1\nevent: prediction.created\n")

        disconnected.set()
        await stream.aclose()
        return broadcaster.subscriber_count

    assert asyncio.run(scenario()) == 0  # abonné retiré à la déconnexion


def test_event_stream_sends_keepalive_when_idle():
    async def scenario():
        broadcaster = SseBroadcaster()

        async def connected():
            return False

        stream = event_stream(broadcaster, connected, keepalive_seconds=0.01)
        await anext(stream)  # retry
        message = await anext(stream)
        await stream.aclose()
        return message

    assert asyncio.run(scenario()) == ": keepalive\n\n"


def test_stream_route_is_declared_as_event_stream(database_url):
    with make_client(database_url) as client:
        operation = client.get("/openapi.json").json()["paths"]["/v1/events/predictions"]["get"]

    assert "text/event-stream" in operation["responses"]["200"]["content"]


# --- Historique -------------------------------------------------------------------------


def test_recent_predictions_are_listed_newest_first(database_url, valid_order):
    with make_client(database_url) as client:
        ids = []
        for suffix in ("A", "B"):
            order_id = f"CMD-RECENT-{suffix}"
            client.post("/v1/orders", json={**valid_order, "order_id": order_id})
            wait_for(lambda oid=order_id: client.get(f"/v1/predictions/{oid}").json().get("order_id"))
            ids.append(order_id)

        body = client.get("/v1/predictions", params={"limit": 1}).json()
        everything = client.get("/v1/predictions").json()

    assert body["count"] == 1
    assert body["predictions"][0]["order_id"] == "CMD-RECENT-B"
    assert [p["order_id"] for p in everything["predictions"]] == ["CMD-RECENT-B", "CMD-RECENT-A"]


@pytest.mark.parametrize("limit", [0, 101])
def test_recent_predictions_limit_is_bounded(database_url, limit):
    with make_client(database_url) as client:
        response = client.get("/v1/predictions", params={"limit": limit})

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


# --- Démonstration ----------------------------------------------------------------------


def test_demo_orders_are_valid_orders():
    orders = demo_orders(20)

    assert all(order["order_id"].startswith(DEMO_PREFIX) for order in orders)
    assert len({order["order_id"] for order in orders}) == 20
    for order in orders:
        OrderFeatures(**order)  # contrat de l'API (vocabulaire de l'ERP)
    assert validate_order(pd.DataFrame(orders))


def test_demo_is_disabled_by_default(database_url):
    with make_client(database_url, demo_mode=False) as client:
        response = client.post("/v1/demo/orders", json={"count": 2})

    assert response.status_code == 404
    assert response.json()["error"] == "demo_disabled"


def test_demo_orders_follow_the_real_order_path(database_url):
    events = InMemoryPredictionEvents()
    received = []
    events.listen(received.append)

    with make_client(database_url, demo_mode=True, prediction_events=events) as client:
        response = client.post("/v1/demo/orders", json={"count": 3})
        body = response.json()
        wait_for(lambda: True if len(received) == 3 else None)
        stored = [client.get(f"/v1/orders/{order_id}").status_code for order_id in body["order_ids"]]

    assert response.status_code == 202
    assert body["count"] == 3
    assert stored == [200, 200, 200]
    assert {event["prediction"]["order_id"] for event in received} == set(body["order_ids"])


def test_demo_default_count_and_rate_limit(database_url):
    with make_client(database_url, demo_mode=True, demo_min_interval=60) as client:
        first = client.post("/v1/demo/orders")
        second = client.post("/v1/demo/orders", json={"count": 1})

    assert first.status_code == 202
    assert first.json()["count"] == 5
    assert second.status_code == 429
    assert second.json()["error"] == "too_many_requests"


@pytest.mark.parametrize("count", [0, 21])
def test_demo_count_is_bounded(database_url, count):
    with make_client(database_url, demo_mode=True) as client:
        response = client.post("/v1/demo/orders", json={"count": count})

    assert response.status_code == 422


# --- Page du logisticien et disponibilité ---------------------------------------------


@pytest.mark.parametrize("demo_mode", [True, False])
def test_logistician_page_is_served(database_url, demo_mode):
    with make_client(database_url, demo_mode=demo_mode) as client:
        response = client.get("/logisticien")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert f"const DEMO_MODE = {'true' if demo_mode else 'false'};" in response.text
    assert "/v1/events/predictions" in response.text


def test_readiness_fails_when_queue_is_unreachable(database_url):
    class UnreachableQueue(InMemoryOrderQueue):
        def ping(self):
            return False

    with make_client(database_url, order_queue=UnreachableQueue()) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["queue"] == "unreachable"
