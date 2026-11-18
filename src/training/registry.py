"""Registre MLflow : configuration de l'expérience et promotion du champion (ADR-0002)."""

from pathlib import Path

import mlflow
import mlflow.sklearn
from mlflow import MlflowClient

from src.config import (
    CHALLENGER_ALIAS,
    CHAMPION_ALIAS,
    MLFLOW_ARTIFACT_ROOT,
    MLFLOW_EXPERIMENT,
    MLFLOW_TRACKING_URI,
    PROMOTION_METRIC,
    REGISTERED_MODEL_NAME,
)
from src.domain.evaluation import evaluate, guardrail_failures
from src.domain.features import DATA_SCHEMA_VERSION


def configure_mlflow():
    """Pointe MLflow sur le registre et crée l'expérience avec sa racine d'artefacts."""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    if mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT) is None:
        artifact_root = MLFLOW_ARTIFACT_ROOT or Path("mlartifacts").resolve().as_uri()
        mlflow.create_experiment(MLFLOW_EXPERIMENT, artifact_location=artifact_root)

    mlflow.set_experiment(MLFLOW_EXPERIMENT)


def promote_if_better(run_id, holdout):
    """Décide du sort de la version du run ; retourne "champion", "challenger" ou "rejected".

    1. Le champion est noté sur le même jeu d'évaluation que le candidat (`holdout`,
       commandes qu'aucun modèle n'a vues à l'entraînement) : comparer son score
       enregistré, mesuré jadis sur d'autres commandes, ne serait pas équitable.
       Un candidat qui ne fait pas strictement mieux est écarté ("rejected").
    2. Un candidat meilleur doit encore respecter les garde-fous métier (ADR-0010) :
       sinon il reçoit l'alias challenger et un humain décide (src/training/promote.py).
    3. Sinon il devient champion, et l'API le charge d'elle-même.

    Sans champion, ou avec un champion d'un autre schéma de données (vocabulaire
    différent, scores non comparables), seul le seuil absolu de précision s'applique.
    """
    client = MlflowClient()

    candidate = client.search_model_versions(
        f"name='{REGISTERED_MODEL_NAME}' and run_id='{run_id}'"
    )[0]
    candidate_score = client.get_run(run_id).data.metrics[PROMOTION_METRIC]
    candidate_model = _load_version(candidate.version)

    champion_model = None
    champion = _version_by_alias(client, CHAMPION_ALIAS)
    if champion is not None:
        champion_run = client.get_run(champion.run_id)
        if champion_run.data.params.get("data_schema") == DATA_SCHEMA_VERSION:
            champion_model = _load_version(champion.version)
            champion_score = evaluate(champion_model, holdout)[PROMOTION_METRIC]
            # Trace de la décision dans le run du candidat.
            client.log_metric(run_id, f"champion_{PROMOTION_METRIC}", champion_score)
            if candidate_score <= champion_score:
                return _record(client, run_id, "rejected")

    failures = guardrail_failures(candidate_model, champion_model, holdout)
    if failures:
        client.set_registered_model_alias(
            REGISTERED_MODEL_NAME, CHALLENGER_ALIAS, candidate.version
        )
        return _record(client, run_id, "challenger", failures)

    client.set_registered_model_alias(
        REGISTERED_MODEL_NAME, CHAMPION_ALIAS, candidate.version
    )
    # Un challenger plus ancien est dépassé par ce nouveau champion.
    if _version_by_alias(client, CHALLENGER_ALIAS) is not None:
        client.delete_registered_model_alias(REGISTERED_MODEL_NAME, CHALLENGER_ALIAS)
    return _record(client, run_id, "champion")


def promote_version(version=None):
    """Décision humaine : place l'alias champion sur `version` (par défaut, le challenger).

    Sert à valider un challenger après examen, ou à revenir à une version antérieure
    (rollback). L'API charge le nouveau champion d'elle-même. Retourne la version promue.
    """
    configure_mlflow()
    client = MlflowClient()

    if version is None:
        challenger = _version_by_alias(client, CHALLENGER_ALIAS)
        if challenger is None:
            raise ValueError("Aucun challenger en attente de décision.")
        version = challenger.version

    model_version = client.get_model_version(REGISTERED_MODEL_NAME, str(version))
    client.set_registered_model_alias(REGISTERED_MODEL_NAME, CHAMPION_ALIAS, model_version.version)
    challenger = _version_by_alias(client, CHALLENGER_ALIAS)
    if challenger is not None and challenger.version == model_version.version:
        client.delete_registered_model_alias(REGISTERED_MODEL_NAME, CHALLENGER_ALIAS)
    client.set_tag(model_version.run_id, "promotion_decision", "champion (décision humaine)")
    return int(model_version.version)


def _load_version(version):
    return mlflow.sklearn.load_model(f"models:/{REGISTERED_MODEL_NAME}/{version}")


def _version_by_alias(client, alias):
    try:
        return client.get_model_version_by_alias(REGISTERED_MODEL_NAME, alias)
    except mlflow.MlflowException:
        return None


def _record(client, run_id, decision, failures=()):
    """Enregistre la décision (et les garde-fous violés) dans le run du candidat."""
    client.set_tag(run_id, "promotion_decision", decision)
    if failures:
        client.set_tag(run_id, "guardrail_failures", " ; ".join(failures))
    return decision
