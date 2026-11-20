import numpy as np
import pandas as pd
import pytest

from src.domain.evaluation import (
    HOLDOUT_PERCENT,
    guardrail_failures,
    is_holdout,
    split_holdout,
)
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


class RuleModel:
    """Modèle factice : probabilité calculée par une fonction des commandes."""

    def __init__(self, rule):
        self.rule = rule

    def predict_proba(self, data):
        proba = np.asarray(self.rule(data), dtype=float)
        return np.column_stack([1 - proba, proba])


@pytest.fixture
def holdout():
    """Commandes d'évaluation dont l'étiquette est connue du « bon » modèle."""
    df = CollectDev().collect_data(n_rows=3000)
    return split_holdout(df)[1]


def perfect(data, holdout):
    return holdout.loc[data.index, "express_eligible"] * 0.8 + 0.1


def test_good_candidate_passes_all_guardrails(holdout):
    model = RuleModel(lambda data: perfect(data, holdout))
    assert guardrail_failures(model, model, holdout) == []


def test_precision_floor(holdout):
    always_yes = RuleModel(lambda data: np.full(len(data), 0.9))
    failures = guardrail_failures(always_yes, None, holdout)
    assert any("précision" in failure for failure in failures)


def test_degraded_segment_is_caught(holdout):
    champion = RuleModel(lambda data: perfect(data, holdout))
    # Parfait partout, sauf en zone rurale où il répond au hasard.
    candidate = RuleModel(lambda data: np.where(
        data["delivery_zone"] == "rural",
        np.random.default_rng(0).uniform(size=len(data)),
        perfect(data, holdout),
    ))
    failures = guardrail_failures(candidate, champion, holdout)
    assert any("delivery_zone=rural" in failure for failure in failures)


def test_positive_rate_shift_is_caught(holdout):
    champion = RuleModel(lambda data: perfect(data, holdout))
    # Même classement, mais seuil décalé : bien plus de commandes déclarées éligibles.
    candidate = RuleModel(lambda data: np.clip(perfect(data, holdout) + 0.45, 0, 1))
    failures = guardrail_failures(candidate, champion, holdout)
    assert any("part d'éligibles" in failure for failure in failures)
