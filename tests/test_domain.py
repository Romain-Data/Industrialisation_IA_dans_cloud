import pandas as pd
import pytest

from src.domain.cleaning import clean_orders_data
from src.domain.validation import validate_dataset, validate_order
from src.infrastructure.dev.collect import CollectDev


@pytest.fixture(scope="module")
def orders():
    return CollectDev().collect_data(n_rows=200)


def test_collect_dev_is_deterministic():
    first = CollectDev().collect_data(n_rows=50)
    second = CollectDev().collect_data(n_rows=50)

    assert len(first) == 50
    assert first.equals(second)


def test_validate_dataset_accepts_generated_data(orders):
    assert validate_dataset(orders) is True


def test_validate_dataset_rejects_missing_column(orders):
    with pytest.raises(ValueError, match="Colonnes obligatoires absentes"):
        validate_dataset(orders.drop(columns="distance_km"))


def test_validate_dataset_rejects_duplicates(orders):
    duplicated = orders.copy()
    duplicated.loc[1, "order_id"] = duplicated.loc[0, "order_id"]

    with pytest.raises(ValueError, match="dupliqués"):
        validate_dataset(duplicated)


@pytest.mark.parametrize(
    "column, value, message",
    [
        ("hour", 25, "heures"),
        ("distance_km", -1, "distance"),
        ("weight_kg", -1, "poids"),
        ("preparation_time_min", -1, "préparation"),
        ("carrier_capacity", 1.5, "capacité"),
        ("stock_available", 3, "stock_available"),
    ],
)
def test_validate_dataset_rejects_out_of_range(orders, column, value, message):
    broken = orders.copy()
    broken.loc[0, column] = value

    with pytest.raises(ValueError, match=message):
        validate_dataset(broken)


def test_clean_orders_removes_duplicates_and_invalid_rows(orders):
    dirty = orders.copy()
    dirty.loc[0, "distance_km"] = -5
    dirty.loc[1, "carrier_capacity"] = 2
    dirty = pd.concat([dirty, dirty.iloc[[5]]], ignore_index=True)

    cleaned = clean_orders_data(dirty)

    assert len(cleaned) == len(orders) - 2
    assert validate_dataset(cleaned) is True


def test_validate_order_does_not_require_target_or_id(orders):
    features = orders.drop(columns=["order_id", "order_date", "express_eligible"])

    assert validate_order(features) is True


def test_validate_order_rejects_missing_feature(orders):
    with pytest.raises(ValueError, match=r"Variables manquantes : \['distance_km'\]"):
        validate_order(orders.drop(columns="distance_km"))


def test_validate_order_rejects_out_of_range(orders):
    broken = orders.copy()
    broken.loc[0, "carrier_capacity"] = 2

    with pytest.raises(ValueError, match="capacité"):
        validate_order(broken)
