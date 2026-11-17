"""Quand réentraîner : dès qu'il y a assez de nouvelles données étiquetées (ADR-0009).

Le cours : « on entraîne dès qu'on a suffisamment de nouvelles données ; la fréquence
de réentraînement dépend du projet ». Réentraîner à chaque import horaire produirait
des modèles presque identiques et encombrerait le registre ; on attend donc un nombre
minimal de nouvelles commandes étiquetées depuis le dernier entraînement.
"""

import mlflow
from mlflow import MlflowClient

from src.config import MLFLOW_EXPERIMENT, MLFLOW_TRACKING_URI
from src.infrastructure.collect_ducklake import MIN_LABELED_ORDERS


def should_retrain(labeled_orders, last_trained_on, min_new_orders):
    """Décide du réentraînement.

    - `labeled_orders` : commandes étiquetées disponibles aujourd'hui ;
    - `last_trained_on` : commandes vues par le dernier entraînement sur ces données
      (None s'il n'y en a jamais eu) ;
    - `min_new_orders` : nouvelles commandes nécessaires pour réentraîner.
    """
    if labeled_orders < MIN_LABELED_ORDERS:
        return False
    if last_trained_on is None:
        return True
    return labeled_orders - last_trained_on >= min_new_orders


def orders_seen_by_last_training(data_source="ducklake"):
    """Commandes lues par le dernier entraînement de cette source (gardées + écartées)."""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    experiment = mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT)
    if experiment is None:
        return None

    runs = MlflowClient().search_runs(
        [experiment.experiment_id],
        filter_string=f"params.data_source = '{data_source}'",
        order_by=["attributes.start_time DESC"],
        max_results=1,
    )
    if not runs:
        return None
    params = runs[0].data.params
    return int(params.get("training_rows", 0)) + int(params.get("rows_dropped", 0))
