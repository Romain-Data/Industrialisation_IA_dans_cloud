import mlflow
import pytest
from mlflow import MlflowClient

from src.abstraction.collect import Collect
from src.config import CHALLENGER_ALIAS, CHAMPION_ALIAS, REGISTERED_MODEL_NAME
from src.domain.evaluation import EVALUATION_PROTOCOL
from src.domain.features import TARGET_COLUMN
from src.infrastructure.dev.collect import CollectDev
from src.serving.model_loader import load_model, load_model_card
from src.training.pipeline import run_training
from src.training.registry import promote_version


class SmallCollect(Collect):
    def collect_data(self):
        return CollectDev().collect_data(n_rows=500)


def test_training_registers_model_and_sets_champion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    _, metrics, run_id = run_training(SmallCollect())

    assert set(metrics) == {"accuracy", "precision", "recall", "f1_score", "roc_auc"}
    assert 0 <= metrics["roc_auc"] <= 1
    assert run_id

    champion = MlflowClient().get_model_version_by_alias(
        REGISTERED_MODEL_NAME, CHAMPION_ALIAS
    )
    assert champion.run_id == run_id
    assert hasattr(load_model(), "predict_proba")


def test_worse_model_does_not_replace_champion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, _, first_run = run_training(SmallCollect())

    # Mêmes données, même ROC AUC : pas de promotion (comparaison stricte).
    _, _, second_run = run_training(SmallCollect())

    client = MlflowClient()
    champion = client.get_model_version_by_alias(REGISTERED_MODEL_NAME, CHAMPION_ALIAS)
    assert second_run != first_run
    assert champion.run_id == first_run
    assert len(client.search_model_versions(f"name='{REGISTERED_MODEL_NAME}'")) == 2


def test_features_are_logged_with_the_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, _, run_id = run_training(SmallCollect())

    features = mlflow.artifacts.load_dict(f"runs:/{run_id}/features.json")

    assert "features" in features


def test_model_card_reflects_the_champion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_model_card() is None

    _, metrics, _ = run_training(SmallCollect())
    card = load_model_card()

    assert card["metrics"] == metrics
    assert "distance_km" in card["features"]
    assert card["trained_at"] is not None
    assert "Le jeu de données utilisé est synthétique." in card["limitations"]


class ShuffledLabelsCollect(Collect):
    """Mêmes commandes, étiquettes mélangées : le modèle obtenu ne vaut rien."""

    def collect_data(self):
        df = CollectDev().collect_data(n_rows=500)
        df[TARGET_COLUMN] = df[TARGET_COLUMN].sample(frac=1, random_state=0).to_numpy()
        return df


def disable_guardrails(monkeypatch):
    """Isole la règle du ROC AUC : garde-fous métier neutralisés."""
    monkeypatch.setattr("src.domain.evaluation.MIN_PRECISION", 0.0)
    monkeypatch.setattr("src.domain.evaluation.MAX_SEGMENT_AUC_DROP", 1.0)
    monkeypatch.setattr("src.domain.evaluation.MAX_POSITIVE_RATE_SHIFT", 1.0)


def test_champion_is_rescored_on_the_same_holdout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    disable_guardrails(monkeypatch)

    # Champion médiocre dont le score enregistré (0.99) est flatteur : mesuré jadis,
    # sur d'autres commandes. Ce chiffre ne doit pas compter dans la décision.
    _, _, weak_run = run_training(ShuffledLabelsCollect())
    client = MlflowClient()  # après l'entraînement, qui pointe MLflow sur le registre du test
    client.log_metric(weak_run, "roc_auc", 0.99)

    _, metrics, good_run = run_training(SmallCollect())

    champion = client.get_model_version_by_alias(REGISTERED_MODEL_NAME, CHAMPION_ALIAS)
    assert champion.run_id == good_run
    champion_score = client.get_run(good_run).data.metrics["champion_roc_auc"]
    assert champion_score < metrics["roc_auc"]


def test_run_records_the_evaluation_protocol(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, _, run_id = run_training(SmallCollect())

    params = MlflowClient().get_run(run_id).data.params
    assert params["evaluation_protocol"] == EVALUATION_PROTOCOL
    assert 0 < int(params["holdout_rows"]) < int(params["training_rows"])


def aliases():
    client = MlflowClient()
    versions = client.search_model_versions(f"name='{REGISTERED_MODEL_NAME}'")
    return {
        alias: int(v.version)
        for v in versions
        for alias in client.get_model_version(REGISTERED_MODEL_NAME, v.version).aliases
    }


def test_first_model_below_precision_floor_is_not_served(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.domain.evaluation.MIN_PRECISION", 0.99)

    _, _, run_id = run_training(SmallCollect())

    assert aliases() == {CHALLENGER_ALIAS: 1}
    tags = MlflowClient().get_run(run_id).data.tags
    assert tags["promotion_decision"] == "challenger"
    assert "précision" in tags["guardrail_failures"]


def test_better_candidate_violating_a_guardrail_becomes_challenger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    disable_guardrails(monkeypatch)
    run_training(ShuffledLabelsCollect())  # champion médiocre, version 1

    monkeypatch.setattr("src.domain.evaluation.MIN_PRECISION", 0.99)
    run_training(SmallCollect())  # meilleur ROC AUC, mais précision insuffisante

    assert aliases() == {CHAMPION_ALIAS: 1, CHALLENGER_ALIAS: 2}


def test_human_validates_the_challenger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.domain.evaluation.MIN_PRECISION", 0.99)
    _, _, run_id = run_training(SmallCollect())

    assert promote_version() == 1

    assert aliases() == {CHAMPION_ALIAS: 1}
    tags = MlflowClient().get_run(run_id).data.tags
    assert tags["promotion_decision"] == "champion (décision humaine)"


def test_human_rollback_to_a_previous_version(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    disable_guardrails(monkeypatch)
    run_training(ShuffledLabelsCollect())
    run_training(SmallCollect())
    assert aliases() == {CHAMPION_ALIAS: 2}

    promote_version(1)

    assert aliases() == {CHAMPION_ALIAS: 1}


def test_promoting_without_challenger_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_training(SmallCollect())

    with pytest.raises(ValueError, match="challenger"):
        promote_version()
