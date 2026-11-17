from pathlib import Path

import mlflow
from mlflow import MlflowClient

from src.config import (
    CHAMPION_ALIAS,
    MLFLOW_ARTIFACT_ROOT,
    MLFLOW_EXPERIMENT,
    MLFLOW_TRACKING_URI,
    PROMOTION_METRIC,
    REGISTERED_MODEL_NAME,
)
from src.domain.features import DATA_SCHEMA_VERSION


def configure_mlflow():
    """Pointe MLflow sur le registre et crée l'expérience avec sa racine d'artefacts."""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    if mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT) is None:
        artifact_root = MLFLOW_ARTIFACT_ROOT or Path("mlartifacts").resolve().as_uri()
        mlflow.create_experiment(MLFLOW_EXPERIMENT, artifact_location=artifact_root)

    mlflow.set_experiment(MLFLOW_EXPERIMENT)


def promote_if_better(run_id):
    """Déplace l'alias champion sur la version du run si son ROC AUC est meilleur.

    Retourne True si la version est promue. Elle l'est d'office s'il n'y a pas de
    champion, ou si le champion a été entraîné sur un autre schéma de données
    (vocabulaire différent) : ses scores ne sont pas comparables, et il ne saurait
    pas traiter les données actuelles.
    """
    client = MlflowClient()

    candidate = client.search_model_versions(
        f"name='{REGISTERED_MODEL_NAME}' and run_id='{run_id}'"
    )[0]
    candidate_score = client.get_run(run_id).data.metrics[PROMOTION_METRIC]

    try:
        champion = client.get_model_version_by_alias(
            REGISTERED_MODEL_NAME, CHAMPION_ALIAS
        )
    except mlflow.MlflowException:
        champion = None

    if champion is not None:
        champion_run = client.get_run(champion.run_id)
        same_schema = champion_run.data.params.get("data_schema") == DATA_SCHEMA_VERSION
        if same_schema and candidate_score <= champion_run.data.metrics[PROMOTION_METRIC]:
            return False

    client.set_registered_model_alias(
        REGISTERED_MODEL_NAME, CHAMPION_ALIAS, candidate.version
    )
    return True
