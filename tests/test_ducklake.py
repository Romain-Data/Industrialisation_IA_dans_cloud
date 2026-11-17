"""Résultat réel des commandes, snapshots DuckLake et entraînement depuis DuckLake (ADR-0001)."""

import pytest
from mlflow import MlflowClient

from src.config import REGISTERED_MODEL_NAME
from src.domain.features import FEATURE_COLUMNS, TARGET_COLUMN
from src.infrastructure.collect_ducklake import MIN_LABELED_ORDERS, CollectDuckLake
from src.infrastructure.dev.collect import CollectDev
from src.infrastructure.ducklake_store import DuckLakeSnapshotStore, ducklake_catalog
from src.infrastructure.order_store import SqlAlchemyOrderStore
from src.training.pipeline import build_collector, run_training


@pytest.fixture
def store(database_url):
    return SqlAlchemyOrderStore(database_url)


@pytest.fixture
def lake(tmp_path):
    return DuckLakeSnapshotStore(f"sqlite:///{tmp_path / 'lake.sqlite'}", tmp_path / "lake_data")


def save_labeled_orders(store, n_rows, batch="a"):
    """Enregistre des commandes synthétiques avec leur résultat réel."""
    orders = CollectDev().collect_data(n_rows=n_rows)
    for row in orders.to_dict(orient="records"):
        order_id = f"{row['order_id']}-{batch}"
        store.save({"order_id": order_id, **{c: row[c] for c in FEATURE_COLUMNS}})
        store.record_outcome(order_id, bool(row[TARGET_COLUMN]))


# --- Résultat réel ----------------------------------------------------------------


def test_record_outcome_on_unknown_order_returns_none(store):
    assert store.record_outcome("CMD-inconnue", True) is None


def test_only_labeled_orders_are_exported(store, valid_order):
    store.save({"order_id": "CMD-1", **valid_order})
    store.save({"order_id": "CMD-2", **valid_order})
    store.record_outcome("CMD-1", False)

    exported = store.export_labeled_orders()

    assert list(exported["order_id"]) == ["CMD-1"]
    assert exported.loc[0, TARGET_COLUMN] == 0
    assert {"order_id", "order_date", TARGET_COLUMN, *FEATURE_COLUMNS} == set(exported.columns)


def test_put_outcome_records_the_result(client, valid_order):
    order_id = client.post("/v1/orders", json=valid_order).json()["order_id"]

    response = client.put(f"/v1/orders/{order_id}/outcome", json={"express_eligible": True})

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == order_id
    assert body["express_eligible"] is True
    assert body["recorded_at"]


def test_put_outcome_on_unknown_order_is_404(client):
    response = client.put("/v1/orders/CMD-inconnue/outcome", json={"express_eligible": True})

    assert response.status_code == 404
    assert response.json()["error"] == "order_not_found"


def test_put_outcome_rejects_invalid_body(client, valid_order):
    order_id = client.post("/v1/orders", json=valid_order).json()["order_id"]

    response = client.put(f"/v1/orders/{order_id}/outcome", json={"express_eligible": "peut-être"})

    assert response.status_code == 422


# --- Snapshots DuckLake -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:///lake.sqlite", ("sqlite", "sqlite:lake.sqlite")),
        (
            "postgresql+psycopg://user:pwd@db:5432/ducklake",
            ("postgres", "postgres:dbname=ducklake host=db port=5432 user=user password=pwd"),
        ),
    ],
)
def test_catalog_url_conversion(url, expected):
    assert ducklake_catalog(url) == expected


def test_snapshots_keep_previous_versions(store, lake):
    save_labeled_orders(store, 10)
    first = lake.write(store.export_labeled_orders())

    save_labeled_orders(store, 15, batch="b")
    second = lake.write(store.export_labeled_orders())

    assert second > first
    assert len(lake.read(first)) == 10
    assert len(lake.read(second)) == 25
    assert len(lake.read()) == 25
    assert {first, second} <= set(lake.versions())


def test_reading_an_empty_lake_fails_clearly(lake):
    with pytest.raises(LookupError):
        lake.read()


# --- Entraînement depuis DuckLake --------------------------------------------------------


def test_collect_refuses_too_few_labeled_orders(store, lake):
    save_labeled_orders(store, 5)

    with pytest.raises(ValueError, match="au moins"):
        CollectDuckLake(store, lake).collect_data()


def test_training_from_ducklake_logs_the_snapshot(tmp_path, monkeypatch, store, lake):
    monkeypatch.chdir(tmp_path)
    save_labeled_orders(store, max(MIN_LABELED_ORDERS, 300))

    _, metrics, run_id = run_training(CollectDuckLake(store, lake))

    params = MlflowClient().get_run(run_id).data.params
    assert params["data_source"] == "ducklake"
    assert int(params["ducklake_snapshot"]) in lake.versions()
    assert params["training_rows"] == "300"
    assert 0 <= metrics["roc_auc"] <= 1
    assert MlflowClient().search_model_versions(f"name='{REGISTERED_MODEL_NAME}'")


def test_retraining_on_a_past_snapshot_uses_the_same_rows(store, lake):
    save_labeled_orders(store, 60)
    version = lake.write(store.export_labeled_orders())
    save_labeled_orders(store, 20, batch="b")
    lake.write(store.export_labeled_orders())

    replay = CollectDuckLake(store, lake, version=version).collect_data()

    assert len(replay) == 60


def test_unknown_training_source_is_rejected():
    with pytest.raises(ValueError, match="TRAINING_SOURCE"):
        build_collector("csv")
