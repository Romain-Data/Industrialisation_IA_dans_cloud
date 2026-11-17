from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src.serving.api import create_app
from src.serving.dependencies import get_order_store
from src.serving.schemas import OrderEvent
from tests.conftest import FakeModel, wait_for

CONTRACT = yaml.safe_load(
    (Path(__file__).parent.parent / "openapi.yml").read_text(encoding="utf-8")
)


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_when_everything_is_up(client):
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {
        "model": "loaded",
        "order_store": "reachable",
        "schema": "up_to_date",
        "worker": "running",
    }


def test_readiness_fails_without_model(client_without_model):
    response = client_without_model.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["model"] == "not_loaded"


def test_readiness_fails_when_schema_is_not_migrated(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'empty.db'}", model_loader=FakeModel)

    with TestClient(app) as test_client:
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["schema"] == "outdated"


def test_prediction_for_valid_order(client, valid_order):
    response = client.post("/v1/predictions", json=valid_order)

    body = response.json()
    assert response.status_code == 200
    assert body["decision"] == "oui"
    assert body["express_eligible"] is True
    assert body["probability"] == 0.8
    assert body["order_id"].startswith("CMD-")
    assert body["latency_ms"] >= 0


def test_prediction_keeps_given_order_id(client, valid_order):
    response = client.post("/v1/predictions", json={**valid_order, "order_id": "CMD-42"})

    assert response.json()["order_id"] == "CMD-42"


def test_prediction_is_unavailable_without_model(client_without_model, valid_order):
    response = client_without_model.post("/v1/predictions", json=valid_order)

    assert response.status_code == 503
    assert response.json()["error"] == "model_unavailable"


@pytest.mark.parametrize(
    "path", ["/v1/predictions", "/v1/orders"]
)
@pytest.mark.parametrize(
    "change, expected_detail",
    [
        ({"distance_km": None}, "distance_km"),
        ({"foo": 1}, "foo"),
        ({"carrier_capacity": -1}, "carrier_capacity"),
        ({"weather": "grele"}, "weather"),
        ({"stock_available": 3}, "stock_available"),
        ({"hour": 24}, "hour"),
    ],
)
def test_invalid_order_returns_contract_error(client, valid_order, path, change, expected_detail):
    order = {**valid_order, **change}
    order = {key: value for key, value in order.items() if value is not None}

    response = client.post(path, json=order)

    body = response.json()
    assert response.status_code == 422
    assert body["error"] == "validation_error"
    assert any(detail.startswith(expected_detail) for detail in body["details"])


def test_create_order_is_accepted_and_readable(client, valid_order):
    response = client.post("/v1/orders", json={**valid_order, "order_id": "CMD-000001"})

    assert response.status_code == 202
    assert response.json() == {"order_id": "CMD-000001", "status": "accepted"}

    stored = client.get("/v1/orders/CMD-000001")
    assert stored.status_code == 200
    assert stored.json()["order_id"] == "CMD-000001"
    assert stored.json()["distance_km"] == 3.5


def test_create_order_generates_missing_id(client, valid_order):
    response = client.post("/v1/orders", json=valid_order)

    assert response.status_code == 202
    assert client.get(f"/v1/orders/{response.json()['order_id']}").status_code == 200


def test_create_order_rejects_duplicate_id(client, valid_order):
    order = {**valid_order, "order_id": "CMD-000001"}
    client.post("/v1/orders", json=order)

    response = client.post("/v1/orders", json=order)

    assert response.status_code == 422
    assert response.json()["error"] == "duplicate_order"


def test_unknown_order_returns_404(client):
    response = client.get("/v1/orders/CMD-999")

    assert response.status_code == 404
    assert response.json()["error"] == "order_not_found"


def test_order_is_predicted_asynchronously(client, valid_order):
    client.post("/v1/orders", json={**valid_order, "order_id": "CMD-000001"})

    def fetch():
        response = client.get("/v1/predictions/CMD-000001")
        return response.json() if response.status_code == 200 else None

    prediction = wait_for(fetch)

    assert prediction is not None
    assert prediction["order_id"] == "CMD-000001"
    assert prediction["decision"] == "oui"


def test_unknown_prediction_returns_404(client):
    response = client.get("/v1/predictions/CMD-999")

    assert response.status_code == 404
    assert response.json()["error"] == "prediction_not_found"


def test_unexpected_error_returns_contract_500(database_url, valid_order):
    class BrokenStore:
        def save(self, order):
            raise RuntimeError("boom")

    app = create_app(database_url, model_loader=FakeModel)
    app.dependency_overrides[get_order_store] = BrokenStore

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.post("/v1/orders", json=valid_order)

    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"


def test_implemented_routes_exist_in_contract(client):
    generated = client.get("/openapi.json").json()["paths"]
    contract = CONTRACT["paths"]

    for path, methods in generated.items():
        if path in ("/docs", "/redoc"):
            continue
        for method in methods:
            assert method in contract.get(path, {}), f"{method.upper()} {path} absent du contrat"


def test_session_1_routes_are_implemented(client):
    generated = client.get("/openapi.json").json()["paths"]

    for path, methods in CONTRACT["paths"].items():
        for method, operation in methods.items():
            if operation.get("x-session") == 1:
                assert method in generated.get(path, {}), f"{method.upper()} {path} manquant"
                assert set(operation["responses"]) <= set(generated[path][method]["responses"])


@pytest.mark.parametrize(
    "schema",
    [
        "OrderFeatures",
        "OrderOutcome",
        "OrderOutcomeRecorded",
        "Prediction",
        "OrderAccepted",
        "HealthStatus",
        "ModelCard",
        "ReadinessStatus",
        "Error",
    ],
)
def test_schemas_match_contract(client, schema):
    generated = client.get("/openapi.json").json()["components"]["schemas"][schema]
    expected = CONTRACT["components"]["schemas"][schema]

    assert set(generated["properties"]) == set(expected["properties"])
    assert set(generated.get("required", [])) == set(expected.get("required", []))


def test_order_event_matches_contract():
    generated = OrderEvent.model_json_schema()
    expected = CONTRACT["components"]["schemas"]["OrderEvent"]

    assert set(generated["properties"]) == set(expected["properties"])
    assert expected["required"] and set(expected["required"]) <= set(generated["required"])


def test_model_card_describes_the_served_model(client):
    response = client.get("/v1/model")

    assert response.status_code == 200
    assert response.json()["metrics"] == {"roc_auc": 0.9}


def test_model_card_without_model_is_503(client_without_model):
    response = client_without_model.get("/v1/model")

    assert response.status_code == 503
    assert response.json()["error"] == "model_unavailable"
