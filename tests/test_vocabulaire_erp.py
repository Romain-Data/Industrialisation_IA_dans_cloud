"""Vocabulaire des commandes aligné sur l'ERP (ADR-0007, contrat 2.0.0)."""

import pandas as pd
import pytest
from mlflow import MlflowClient

from src.config import CHAMPION_ALIAS, REGISTERED_MODEL_NAME
from src.domain.features import CATEGORY_VALUES, DATA_SCHEMA_VERSION, FEATURE_COLUMNS
from src.domain.validation import validate_order
from src.infrastructure.dev.collect import CollectDev
from src.training.pipeline import run_training
from tests.erp_simulator import erp_orders


def erp_features(order):
    """Caractéristiques d'une commande ERP, au format attendu par l'API."""
    return {column: order[column] for column in FEATURE_COLUMNS}


# --- Les commandes de l'ERP sont acceptées telles quelles ------------------------------------


def test_erp_orders_pass_domain_validation():
    orders = pd.DataFrame([erp_features(order) for order in erp_orders(200)])

    assert validate_order(orders) is True


def test_api_predicts_an_erp_order(client):
    order = erp_features(erp_orders(1)[0])

    response = client.post("/v1/predictions", json=order)

    assert response.status_code == 200
    assert response.json()["model_version"] == "2.0.0"


def test_erp_vocabulary_covers_every_value_the_erp_produces():
    orders = erp_orders(500)

    for column, allowed in CATEGORY_VALUES.items():
        assert {order[column] for order in orders} == set(allowed)


def test_synthetic_data_uses_the_erp_vocabulary():
    data = CollectDev().collect_data(n_rows=500)

    for column, allowed in CATEGORY_VALUES.items():
        assert set(data[column]) == set(allowed)
    assert data["carrier_capacity"].between(5, 50).all()


# --- L'ancien vocabulaire est refusé ------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [{"weather": "pluie"}, {"delivery_zone": "banlieue"}, {"customer_type": "premium"}],
)
def test_api_rejects_the_former_vocabulary(client, valid_order, change):
    response = client.post("/v1/predictions", json={**valid_order, **change})

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_domain_rejects_unknown_categories():
    orders = pd.DataFrame([erp_features(order) for order in erp_orders(3)])
    orders.loc[0, "weather"] = "orage"

    with pytest.raises(ValueError, match="Valeurs inconnues pour weather"):
        validate_order(orders)


def test_missing_categories_are_left_to_imputation():
    orders = pd.DataFrame([erp_features(order) for order in erp_orders(3)])
    orders.loc[0, "weather"] = None

    assert validate_order(orders) is True


# --- Un champion d'un autre schéma de données est toujours remplacé --------------------------


def test_model_of_another_data_schema_is_replaced_even_if_not_better(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class SmallCollect(CollectDev):
        def collect_data(self, n_rows=500, random_state=42):
            return super().collect_data(n_rows=n_rows, random_state=random_state)

    # Ancien champion, entraîné sur un autre vocabulaire.
    monkeypatch.setattr("src.training.train.DATA_SCHEMA_VERSION", "ancien-vocabulaire")
    _, _, old_run = run_training(SmallCollect())
    # Retour au schéma actuel (pas de monkeypatch.undo() : il annulerait aussi le
    # registre MLflow temporaire de la fixture isolated_mlflow).
    monkeypatch.setattr("src.training.train.DATA_SCHEMA_VERSION", DATA_SCHEMA_VERSION)

    # Mêmes données, même score : sans le changement de schéma, il ne serait pas promu.
    _, _, new_run = run_training(SmallCollect())

    client = MlflowClient()
    champion = client.get_model_version_by_alias(REGISTERED_MODEL_NAME, CHAMPION_ALIAS)
    assert champion.run_id == new_run != old_run
    # Les deux runs sont bien dans le même registre : l'ancien champion a été remplacé.
    assert len(client.search_model_versions(f"name='{REGISTERED_MODEL_NAME}'")) == 2
    assert client.get_run(old_run).data.params["data_schema"] == "ancien-vocabulaire"
    assert client.get_run(new_run).data.params["data_schema"] == DATA_SCHEMA_VERSION
