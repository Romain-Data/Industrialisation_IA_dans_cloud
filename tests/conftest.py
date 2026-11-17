import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.infrastructure.migrations import upgrade_to_head
from src.serving.api import create_app

VALID_ORDER = {
    "hour": 14,
    "day_of_week": 2,
    "weekend": 0,
    "distance_km": 3.5,
    "order_value_eur": 89.9,
    "weight_kg": 2.4,
    "stock_available": 1,
    "preparation_time_min": 18,
    "carrier_capacity": 34.5,
    "weather": "clear",
    "delivery_zone": "centre",
    "customer_type": "business",
}


class FakeModel:
    """Modèle factice : renvoie toujours la même probabilité d'éligibilité."""

    def __init__(self, probability=0.8):
        self.probability = probability

    def predict_proba(self, data):
        return np.tile([1 - self.probability, self.probability], (len(data), 1))


def _no_model():
    raise FileNotFoundError


# Pas de surveillance du registre MLflow dans les tests d'API (voir test_model_reloader.py).
NO_RELOAD = {"version_reader": lambda: None, "reload_interval": 0}


FAKE_MODEL_CARD = {
    "project": "eligibilite-livraison-express",
    "model_version": "1.0.0",
    "model_type": "LogisticRegression",
    "task": "binary classification",
    "target": "express_eligible",
    "threshold": 0.5,
    "features": ["hour"],
    "metrics": {"roc_auc": 0.9},
}


@pytest.fixture(autouse=True)
def isolated_mlflow(tmp_path, monkeypatch):
    """Registre MLflow temporaire par test (le store est mis en cache par URI)."""
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    monkeypatch.setattr("src.training.registry.MLFLOW_TRACKING_URI", uri)
    monkeypatch.setattr("src.serving.model_loader.MLFLOW_TRACKING_URI", uri)
    monkeypatch.setattr("src.training.retraining.MLFLOW_TRACKING_URI", uri)
    monkeypatch.setattr(
        "src.training.registry.MLFLOW_ARTIFACT_ROOT", (tmp_path / "mlartifacts").as_uri()
    )


@pytest.fixture
def valid_order():
    return dict(VALID_ORDER)


@pytest.fixture
def fake_model():
    return FakeModel()


@pytest.fixture
def database_url(tmp_path):
    """Base SQLite temporaire, avec le schéma migré."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    upgrade_to_head(url)
    return url


@pytest.fixture
def client(database_url):
    app = create_app(
        database_url,
        model_loader=FakeModel,
        model_card_loader=lambda: dict(FAKE_MODEL_CARD),
        **NO_RELOAD,
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_without_model(database_url):
    app = create_app(database_url, model_loader=_no_model, **NO_RELOAD)
    with TestClient(app) as test_client:
        yield test_client


def wait_for(fetch, timeout=3.0):
    """Appelle fetch() jusqu'à ce qu'il retourne une valeur non nulle."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fetch()
        if value is not None:
            return value
        time.sleep(0.05)
    return None
