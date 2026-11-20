"""Flux temps réel du logisticien (ADR-0013) : diffusion, SSE, historique, flux ERP."""

import asyncio
import threading
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src.etl.erp_import import import_erp_orders
from src.infrastructure.dev.in_memory_order_repository import InMemoryOrderRepository
from src.infrastructure.dev.order_queue import InMemoryOrderQueue
from src.infrastructure.dev.prediction_events import InMemoryPredictionEvents
from src.infrastructure.import_journal import SqlAlchemyImportJournal
from src.infrastructure.order_store import SqlAlchemyOrderStore
from src.serving.api import create_app
from src.serving.broadcaster import SseBroadcaster, event_stream, format_sse
from src.serving.erp_stream import ErpStream, ErpUnavailableError
from src.serving.schemas import PredictionEvent
from tests.conftest import NO_RELOAD, FakeModel, wait_for
from tests.erp_simulator import erp_orders
from tests.test_erp_import import to_labeled_entity

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


# --- Flux ERP du logisticien ------------------------------------------------------------


def erp_repository(count, first_sequence=1):
    """ERP en mémoire, alimenté par le générateur du simulateur du cours."""
    return InMemoryOrderRepository([to_labeled_entity(o) for o in erp_orders(count, first_sequence)])


def add_erp_orders(repository, count, first_sequence):
    """Nouvelles commandes arrivées dans l'ERP après l'activation du flux."""
    for order, label in (to_labeled_entity(o) for o in erp_orders(count, first_sequence)):
        repository._orders[order.order_id] = order  # pylint: disable=protected-access
        repository._labels[order.order_id] = label  # pylint: disable=protected-access


def test_stream_reads_only_orders_arrived_after_activation(database_url):
    repository = erp_repository(10)
    queue = InMemoryOrderQueue()
    stream = ErpStream(lambda: repository, SqlAlchemyOrderStore(database_url), queue, poll_seconds=60)

    status = stream.start()
    try:
        assert status["active"] is True
        assert status["last_order_id"] == "ERP-00000010"
        assert stream.poll_once() == 0  # l'historique n'est pas relu

        add_erp_orders(repository, 3, first_sequence=11)
        assert stream.poll_once() == 3
        assert stream.poll_once() == 0  # pas de doublon
        events = [queue.consume(timeout=0) for _ in range(3)]
    finally:
        status = stream.stop()

    assert [event["order"]["order_id"] for event in events] == [
        "ERP-00000011", "ERP-00000012", "ERP-00000013"
    ]
    assert queue.consume(timeout=0) is None
    assert status["active"] is False
    assert status["received"] == 3


def test_stream_skips_invalid_orders_and_moves_on(database_url):
    repository = erp_repository(1)
    queue = InMemoryOrderQueue()
    stream = ErpStream(lambda: repository, SqlAlchemyOrderStore(database_url), queue, poll_seconds=60)
    stream.start()
    try:
        add_erp_orders(repository, 2, first_sequence=2)
        bad = repository._orders["ERP-00000002"]  # pylint: disable=protected-access
        repository._orders["ERP-00000002"] = replace(bad, distance_km=-5)  # pylint: disable=protected-access

        assert stream.poll_once() == 1
        assert stream.status()["last_order_id"] == "ERP-00000003"
    finally:
        stream.stop()


def test_streamed_orders_are_already_present_for_the_hourly_import(database_url):
    repository = erp_repository(2)
    store = SqlAlchemyOrderStore(database_url)
    journal = SqlAlchemyImportJournal(database_url)
    import_erp_orders(repository, store, journal)  # import horaire précédent

    stream = ErpStream(lambda: repository, store, InMemoryOrderQueue(), poll_seconds=60)
    stream.start()
    try:
        add_erp_orders(repository, 2, first_sequence=3)
        assert stream.poll_once() == 2
    finally:
        stream.stop()

    report = import_erp_orders(repository, store, journal)
    assert report.imported == 0
    assert report.already_present == 2
    assert store.count_labeled_orders() == 4  # cible conservée pour l'entraînement


def test_stream_refuses_to_start_without_erp(database_url):
    class DownErp(InMemoryOrderRepository):
        def ping(self):
            return False

    stream = ErpStream(DownErp, SqlAlchemyOrderStore(database_url), InMemoryOrderQueue())

    with pytest.raises(ErpUnavailableError):
        stream.start()
    assert stream.status()["active"] is False


def test_logistician_activates_and_cuts_the_stream(database_url):
    repository = erp_repository(5)
    events = InMemoryPredictionEvents()
    received = []
    events.listen(received.append)

    with make_client(
        database_url, prediction_events=events, erp_source_factory=lambda: repository,
        erp_poll_seconds=0.05,
    ) as client:
        assert client.get("/v1/erp-stream").json()["active"] is False

        started = client.put("/v1/erp-stream", json={"active": True})
        add_erp_orders(repository, 2, first_sequence=6)
        wait_for(lambda: True if len(received) == 2 else None)
        stopped = client.put("/v1/erp-stream", json={"active": False})

    assert started.status_code == 200
    assert started.json()["active"] is True
    assert {event["prediction"]["order_id"] for event in received} == {"ERP-00000006", "ERP-00000007"}
    assert stopped.json() | {"since": None} == {
        "active": False, "since": None, "last_order_id": "ERP-00000007", "received": 2
    }


def test_stream_activation_fails_with_503_when_erp_is_down(database_url):
    class DownErp(InMemoryOrderRepository):
        def ping(self):
            return False

    with make_client(database_url, erp_source_factory=DownErp) as client:
        response = client.put("/v1/erp-stream", json={"active": True})

    assert response.status_code == 503
    assert response.json()["error"] == "erp_unavailable"


def test_stream_update_requires_active_flag(database_url):
    with make_client(database_url) as client:
        response = client.put("/v1/erp-stream", json={})

    assert response.status_code == 422


# --- Page du logisticien et disponibilité ---------------------------------------------


def test_logistician_page_is_served(database_url):
    with make_client(database_url) as client:
        response = client.get("/logisticien")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/v1/events/predictions" in response.text
    assert "/v1/erp-stream" in response.text


def test_readiness_fails_when_queue_is_unreachable(database_url):
    class UnreachableQueue(InMemoryOrderQueue):
        def ping(self):
            return False

    with make_client(database_url, order_queue=UnreachableQueue()) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["queue"] == "unreachable"
