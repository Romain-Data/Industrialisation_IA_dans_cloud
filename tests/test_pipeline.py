import json

from src.abstraction.collect import Collect
from src.infrastructure.dev.collect import CollectDev
from src.training.pipeline import run_training


class SmallCollect(Collect):
    def collect_data(self):
        return CollectDev().collect_data(n_rows=500)


def test_training_pipeline_saves_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    model, metrics, run_id = run_training(SmallCollect())

    artifacts = tmp_path / "artifacts"
    assert (artifacts / "express_delivery_model.joblib").exists()
    assert json.loads((artifacts / "metrics.json").read_text()) == metrics
    assert "features" in json.loads((artifacts / "features.json").read_text())
    assert set(metrics) == {"accuracy", "precision", "recall", "f1_score", "roc_auc"}
    assert 0 <= metrics["roc_auc"] <= 1
    assert run_id
