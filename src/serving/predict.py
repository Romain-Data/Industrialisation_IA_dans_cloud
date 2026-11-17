from datetime import UTC, datetime

import pandas as pd

from src.config import DEFAULT_THRESHOLD, MODEL_VERSION
from src.domain.features import FEATURE_COLUMNS
from src.domain.validation import validate_order


def predict_order_eligibility(order_data, model, threshold=DEFAULT_THRESHOLD):
    """
    Effectue une prédiction pour une commande.

    Parameters
    ----------
    order_data : dict
        Données d'une commande.
    model : Pipeline
        Pipeline scikit-learn entraînée.
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
