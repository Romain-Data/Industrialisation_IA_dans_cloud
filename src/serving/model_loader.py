"""Chargement du modèle champion et de sa model card depuis le registre MLflow (ADR-0002)."""

from datetime import UTC, datetime

import mlflow
import mlflow.sklearn
from mlflow import MlflowClient

from src.config import (
    CHAMPION_ALIAS,
    DEFAULT_THRESHOLD,
    MLFLOW_TRACKING_URI,
    MODEL_VERSION,
    PROJECT_NAME,
    REGISTERED_MODEL_NAME,
)
from src.domain.features import TARGET_COLUMN

MODEL_URI = f"models:/{REGISTERED_MODEL_NAME}@{CHAMPION_ALIAS}"

LIMITATIONS = [
    "La décision ne doit pas être utilisée sans validation des règles métier.",
    "Les performances peuvent varier sur des données réelles.",
    "Le modèle ne remplace pas une analyse des contraintes opérationnelles.",
]


def champion_version():
    """Numéro de version du champion dans le registre, ou None s'il n'y en a pas."""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    try:
        return MlflowClient().get_model_version_by_alias(REGISTERED_MODEL_NAME, CHAMPION_ALIAS).version
    except mlflow.MlflowException:
        return None


def load_model():
    """Charge la version du modèle portant l'alias champion dans le registre MLflow."""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    try:
        return mlflow.sklearn.load_model(MODEL_URI)
    except mlflow.MlflowException as error:
        raise FileNotFoundError(
            f"Modèle introuvable : {MODEL_URI}. "
            "Lancer l'entraînement avant de démarrer le service."
        ) from error


def load_model_card():
    """Model card du champion (cellule 55 du notebook), à partir du registre MLflow.

    Retourne None s'il n'y a pas encore de champion.
    """
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = MlflowClient()

    try:
        version = client.get_model_version_by_alias(REGISTERED_MODEL_NAME, CHAMPION_ALIAS)
    except mlflow.MlflowException:
        return None

    run = client.get_run(version.run_id)
    features = mlflow.artifacts.load_dict(f"runs:/{version.run_id}/features.json")

    limitations = list(LIMITATIONS)
    if run.data.params.get("data_source", "synthetic") == "synthetic":
        limitations.insert(0, "Le jeu de données utilisé est synthétique.")

    return {
        "project": PROJECT_NAME,
        "model_version": MODEL_VERSION,
        "model_type": run.data.params.get("model_type", "LogisticRegression"),
        "task": "binary classification",
        "target": features.get("target", TARGET_COLUMN),
        "threshold": DEFAULT_THRESHOLD,
        "trained_at": datetime.fromtimestamp(run.info.start_time / 1000, UTC),
        "features": features["features"],
        "metrics": run.data.metrics,
        "limitations": limitations,
    }
