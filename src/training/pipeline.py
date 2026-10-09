import json

import joblib

from src.abstraction.collect import Collect
from src.config import ARTIFACTS_DIR, MODEL_VERSION
from src.domain.cleaning import clean_orders_data
from src.domain.features import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
)
from src.domain.validation import validate_dataset
from src.training.train import train_model


def save_artifacts(model_pipeline, metrics):
    """Sauvegarde le modèle, les métriques et la configuration des variables."""
    ARTIFACTS_DIR.mkdir(exist_ok=True)

    model_path = ARTIFACTS_DIR / "express_delivery_model.joblib"
    metrics_path = ARTIFACTS_DIR / "metrics.json"
    features_path = ARTIFACTS_DIR / "features.json"

    joblib.dump(model_pipeline, model_path)

    with open(metrics_path, "w", encoding="utf-8") as file:
        json.dump(metrics, file, indent=2)

    with open(features_path, "w", encoding="utf-8") as file:
        json.dump(
            {
                "model_version": MODEL_VERSION,
                "target": TARGET_COLUMN,
                "features": FEATURE_COLUMNS,
                "numeric_features": NUMERIC_FEATURES,
                "categorical_features": CATEGORICAL_FEATURES,
            },
            file,
            indent=2
        )

    print(f"Modèle sauvegardé dans : {model_path}")
    print(f"Métriques sauvegardées dans : {metrics_path}")
    print(f"Configuration sauvegardée dans : {features_path}")


def run_training(collector: Collect):
    """Collecte, valide, nettoie les données, entraîne puis sauvegarde le modèle."""
    raw_orders = collector.collect_data()
    validate_dataset(raw_orders)

    orders_clean = clean_orders_data(raw_orders)
    validate_dataset(orders_clean)

    model_pipeline, metrics, run_id = train_model(orders_clean)
    save_artifacts(model_pipeline, metrics)

    print("Entraînement terminé.")
    print(f"Run MLflow : {run_id}")
    print(f"Métriques : {metrics}")

    return model_pipeline, metrics, run_id


if __name__ == "__main__":
    from src.infrastructure.dev.collect import CollectDev

    run_training(CollectDev())
