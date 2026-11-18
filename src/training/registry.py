"""Registre MLflow : configuration de l'expérience et promotion du champion (ADR-0002)."""

from pathlib import Path

import mlflow
import mlflow.sklearn
from mlflow import MlflowClient

from src.config import (
    CHAMPION_ALIAS,
    MLFLOW_ARTIFACT_ROOT,
    MLFLOW_EXPERIMENT,
    MLFLOW_TRACKING_URI,
    PROMOTION_METRIC,
    REGISTERED_MODEL_NAME,
)
from src.domain.evaluation import evaluate
from src.domain.features import DATA_SCHEMA_VERSION


def configure_mlflow():
    """Pointe MLflow sur le registre et crée l'expérience avec sa racine d'artefacts."""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    if mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT) is None:
        artifact_root = MLFLOW_ARTIFACT_ROOT or Path("mlartifacts").resolve().as_uri()
        mlflow.create_experiment(MLFLOW_EXPERIMENT, artifact_location=artifact_root)

    mlflow.set_experiment(MLFLOW_EXPERIMENT)


def promote_if_better(run_id, holdout):
    """Déplace l'alias champion sur la version du run si elle bat le champion.

    Les deux modèles sont notés sur le même jeu d'évaluation (`holdout`, commandes
    qu'aucun modèle n'a vues à l'entraînement) : comparer le score enregistré du
    champion, mesuré jadis sur d'autres commandes, ne serait pas équitable.

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
        if champion_run.data.params.get("data_schema") == DATA_SCHEMA_VERSION:
            champion_uri = f"models:/{REGISTERED_MODEL_NAME}/{champion.version}"
            champion_model = mlflow.sklearn.load_model(champion_uri)
            champion_score = evaluate(champion_model, holdout)[PROMOTION_METRIC]
            # Trace de la décision dans le run du candidat.
            client.log_metric(run_id, f"champion_{PROMOTION_METRIC}", champion_score)
            if candidate_score <= champion_score:
                return False

    client.set_registered_model_alias(
        REGISTERED_MODEL_NAME, CHAMPION_ALIAS, candidate.version
    )
    return True
