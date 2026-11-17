"""Rechargement du champion par l'API, sans redémarrage (ADR-0009)."""

from fastapi.testclient import TestClient
from mlflow import MlflowClient

from src.config import CHAMPION_ALIAS, REGISTERED_MODEL_NAME
from src.infrastructure.dev.collect import CollectDev
from src.serving.api import create_app
from src.serving.model_loader import champion_version
from src.serving.model_reloader import ModelReloader
from src.training.pipeline import run_training


class Registry:
    """Version du champion pilotée par le test."""

    def __init__(self, version):
        self.version = version
        self.reloads = 0

    def read(self):
        if isinstance(self.version, Exception):
            raise self.version
        return self.version

    def reload(self):
        self.reloads += 1


def test_reloads_only_when_the_champion_changes():
    registry = Registry("1")
    reloader = ModelReloader(registry.read, registry.reload, interval_seconds=0)
    reloader.start("1")

    assert reloader.check_once() is False
    registry.version = "2"
    assert reloader.check_once() is True
    assert reloader.check_once() is False
    assert (registry.reloads, reloader.current_version) == (1, "2")


def test_keeps_the_served_model_when_the_registry_is_unreachable():
    registry = Registry(ConnectionError("MLflow injoignable"))
    reloader = ModelReloader(registry.read, registry.reload, interval_seconds=0)
    reloader.start("1")

    assert reloader.check_once() is False
    assert (registry.reloads, reloader.current_version) == (0, "1")


def test_no_champion_means_nothing_to_reload():
    registry = Registry(None)
    reloader = ModelReloader(registry.read, registry.reload, interval_seconds=0)
    reloader.start(None)

    assert reloader.check_once() is False


def test_running_api_serves_the_new_champion_without_restart(tmp_path, monkeypatch, database_url):
    monkeypatch.chdir(tmp_path)

    class SmallCollect(CollectDev):
        seed = 42

        def collect_data(self, n_rows=500, random_state=None):
            return super().collect_data(n_rows=n_rows, random_state=random_state or self.seed)

    class OtherSmallCollect(SmallCollect):
        seed = 7

    run_training(SmallCollect())
    app = create_app(database_url, reload_interval=0)

    with TestClient(app) as client:
        first = client.get("/v1/model").json()["trained_at"]

        # L'orchestrateur promeut un nouveau champion (ici, en forçant l'alias).
        _, _, run_id = run_training(OtherSmallCollect())
        mlflow_client = MlflowClient()
        new_version = mlflow_client.search_model_versions(
            f"name='{REGISTERED_MODEL_NAME}' and run_id='{run_id}'"
        )[0].version
        mlflow_client.set_registered_model_alias(REGISTERED_MODEL_NAME, CHAMPION_ALIAS, new_version)

        assert app.state.reloader.check_once() is True
        assert champion_version() == new_version
        assert client.get("/v1/model").json()["trained_at"] != first
        assert client.get("/health/ready").status_code == 200
