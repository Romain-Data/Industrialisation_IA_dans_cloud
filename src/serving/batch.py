"""Prédiction par lot sur un DataFrame de commandes, avec export CSV."""

import numpy as np

from src.config import ARTIFACTS_DIR, DEFAULT_THRESHOLD
from src.domain.features import FEATURE_COLUMNS
from src.domain.validation import validate_order

PREDICTIONS_FILENAME = "batch_predictions.csv"


def batch_predict_orders(input_df, model, threshold=DEFAULT_THRESHOLD):
    """
    Réalise une prédiction batch sur plusieurs commandes.
    """
    validate_order(input_df)

    result = input_df.copy()
    result["eligibility_probability"] = model.predict_proba(
        input_df[FEATURE_COLUMNS]
    )[:, 1]

    result["express_eligible"] = (
        result["eligibility_probability"] >= threshold
    ).astype(int)

    result["decision"] = np.where(
        result["express_eligible"] == 1,
        "oui",
        "non"
    )

    return result


def save_batch_predictions(predictions, artifacts_dir=ARTIFACTS_DIR):
    """Écrit les prédictions batch au format CSV et retourne le chemin."""
    artifacts_dir.mkdir(exist_ok=True)
    predictions_path = artifacts_dir / PREDICTIONS_FILENAME

    predictions.to_csv(predictions_path, index=False)

    return predictions_path
