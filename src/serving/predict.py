"""Prédiction d'une commande : validation, probabilité et décision selon le seuil."""

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from src.config import DEFAULT_THRESHOLD, MODEL_VERSION
from src.domain.classifier import Classifier
from src.domain.features import FEATURE_COLUMNS
from src.domain.validation import validate_order


def predict_order_eligibility(
    order_data: dict[str, Any], model: Classifier, threshold: float = DEFAULT_THRESHOLD
) -> dict[str, Any]:
    """
    Effectue une prédiction pour une commande.

    Parameters
    ----------
    order_data : dict
        Données d'une commande.
    model : Classifier
        Modèle entraîné (pipeline scikit-learn en pratique).
    threshold : float
        Seuil à partir duquel la commande est considérée comme éligible.

    Returns
    -------
    dict
        Résultat de la prédiction.
    """
    order_df = pd.DataFrame([order_data])
    validate_order(order_df)

    input_df = order_df[FEATURE_COLUMNS]

    probability = float(model.predict_proba(input_df)[0, 1])
    eligible = probability >= threshold

    return {
        "express_eligible": bool(eligible),
        "decision": "oui" if eligible else "non",
        "probability": round(probability, 4),
        "model_version": MODEL_VERSION,
        "prediction_timestamp": datetime.now(UTC).isoformat(),
    }
