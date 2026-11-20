"""Calcul d'une prédiction au format du contrat Prediction (avec la latence)."""

import time
from datetime import datetime
from typing import Any

from src.domain.classifier import Classifier
from src.serving.predict import predict_order_eligibility


def compute_prediction(
    order_id: str, order_data: dict[str, Any], model: Classifier
) -> dict[str, Any]:
    """Calcule la prédiction d'une commande, au format du contrat Prediction."""
    started = time.perf_counter()
    result = predict_order_eligibility(order_data, model)

    return {
        "order_id": order_id,
        "express_eligible": result["express_eligible"],
        "decision": result["decision"],
        "probability": result["probability"],
        "model_version": result["model_version"],
        "predicted_at": datetime.fromisoformat(result["prediction_timestamp"]),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }
