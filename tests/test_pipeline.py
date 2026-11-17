import mlflow
from mlflow import MlflowClient

from src.abstraction.collect import Collect
from src.config import CHAMPION_ALIAS, REGISTERED_MODEL_NAME
from src.infrastructure.dev.collect import CollectDev
from src.serving.model_loader import load_model, load_model_card
from src.training.pipeline import run_training


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
