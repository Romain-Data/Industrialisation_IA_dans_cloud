import pandas as pd
import pytest

from src.domain.evaluation import HOLDOUT_PERCENT, is_holdout, split_holdout
from src.infrastructure.dev.collect import CollectDev


def test_holdout_membership_is_stable():
    ids = [f"CMD-{i:06d}" for i in range(200)]
    assert [is_holdout(i) for i in ids] == [is_holdout(i) for i in ids]


def test_holdout_keeps_its_orders_when_new_orders_arrive():
    """Un réentraînement sur plus de données ne fait jamais sortir une commande du holdout."""
    small = CollectDev().collect_data(n_rows=1000)
    large = CollectDev().collect_data(n_rows=3000)

    _, holdout_small = split_holdout(small)
    train_large, holdout_large = split_holdout(large)

    assert set(holdout_small["order_id"]) <= set(holdout_large["order_id"])
    assert not set(holdout_small["order_id"]) & set(train_large["order_id"])


def test_holdout_size_is_close_to_target():
    df = CollectDev().collect_data(n_rows=3000)
    _, holdout = split_holdout(df)
    assert abs(len(holdout) / len(df) * 100 - HOLDOUT_PERCENT) < 3


def test_split_requires_order_id():
    df = CollectDev().collect_data(n_rows=100).drop(columns="order_id")
    with pytest.raises(ValueError, match="order_id"):
        split_holdout(df)


def test_split_rejects_a_single_class():
    df = CollectDev().collect_data(n_rows=100)
    df["express_eligible"] = 1
    with pytest.raises(ValueError, match="deux classes"):
        split_holdout(pd.DataFrame(df))
