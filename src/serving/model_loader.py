import joblib

from src.config import ARTIFACTS_DIR

MODEL_FILENAME = "express_delivery_model.joblib"


def load_model(artifacts_dir=ARTIFACTS_DIR):
    """Charge le modèle entraîné depuis le dossier d'artefacts."""
    model_path = artifacts_dir / MODEL_FILENAME

    if not model_path.exists():
        raise FileNotFoundError(
            f"Modèle introuvable : {model_path}. "
            "Lancer l'entraînement avant de démarrer le service."
        )

    return joblib.load(model_path)
