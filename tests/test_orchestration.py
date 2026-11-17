"""Orchestration Prefect : décision de réentraînement et flow ERP complet (ADR-0009)."""

import pytest
from prefect.testing.utilities import prefect_test_harness

from src.infrastructure.dev.in_memory_order_repository import InMemoryOrderRepository
from src.orchestration import flows
from src.training.retraining import should_retrain
from tests.erp_simulator import erp_orders
from tests.test_erp_import import to_labeled_entity

# --- Décision de réentraînement -------------------------------------------------------------


@pytest.mark.parametrize(
    ("labeled", "seen", "minimum", "expected"),
    [
        (30, None, 500, False),  # trop peu de données pour un premier entraînement
        (300, None, 500, True),  # jamais entraîné sur ces données : on entraîne
        (1200, 1000, 500, False),  # 200 nouvelles commandes seulement
        (1500, 1000, 500, True),  # 500 nouvelles commandes : on réentraîne
    ],
)
def test_should_retrain(labeled, seen, minimum, expected):
    assert should_retrain(labeled, seen, minimum) is expected


# --- Flow complet, avec le moteur Prefect ---------------------------------------------------


class ClosableInMemoryRepository(InMemoryOrderRepository):
    """ERP en mémoire, avec la même interface de fermeture que MongoOrderRepository."""

    def close(self):
        """Rien à fermer en mémoire."""


@pytest.fixture(scope="module")
def prefect_server():
    with prefect_test_harness():
        yield


@pytest.fixture
def erp(monkeypatch, tmp_path, database_url):
    """Flows branchés sur une base temporaire, un DuckLake temporaire et un ERP en mémoire."""
    monkeypatch.chdir(tmp_path)
    repository = ClosableInMemoryRepository([to_labeled_entity(o) for o in erp_orders(300)])
    monkeypatch.setattr(flows, "MongoOrderRepository", lambda *args, **kwargs: repository)
    monkeypatch.setattr(flows, "DATABASE_URL", database_url)
    monkeypatch.setattr(flows, "DUCKLAKE_CATALOG_URL", f"sqlite:///{tmp_path / 'lake.sqlite'}")
    monkeypatch.setattr(flows, "DUCKLAKE_DATA_PATH", tmp_path / "lake")
    return repository


def test_pipeline_imports_then_trains_when_enough_new_data(prefect_server, erp):
    result = flows.erp_pipeline(min_new_orders=100)

    assert result["import"]["imported"] == 300
    assert result["training"]["data_source"] == "ducklake"
    assert result["training"]["roc_auc"] > 0.5


def test_pipeline_does_not_retrain_without_enough_new_data(prefect_server, erp):
    flows.erp_pipeline(min_new_orders=100)
    for order in erp_orders(20, first_sequence=301):
        entity, label = to_labeled_entity(order)
        erp._orders[entity.order_id], erp._labels[entity.order_id] = entity, label

    result = flows.erp_pipeline(min_new_orders=100)

    assert result["import"]["imported"] == 20
    assert result["training"] is None


def test_forced_retraining_ignores_the_threshold(prefect_server, erp):
    flows.erp_pipeline(min_new_orders=100)

    result = flows.erp_pipeline(min_new_orders=100, force_retrain=True)

    assert result["import"]["imported"] == 0
    assert result["training"] is not None
