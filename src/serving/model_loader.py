import mlflow
import mlflow.sklearn

from src.config import CHAMPION_ALIAS, MLFLOW_TRACKING_URI, REGISTERED_MODEL_NAME

MODEL_URI = f"models:/{REGISTERED_MODEL_NAME}@{CHAMPION_ALIAS}"


def load_model():
    """Charge la version du modèle portant l'alias champion dans le registre MLflow."""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    try:
        return mlflow.sklearn.load_model(MODEL_URI)
    except mlflow.MlflowException as error:
        raise FileNotFoundError(
            f"Modèle introuvable : {MODEL_URI}. "
            "Lancer l'entraînement avant de démarrer le service."
        ) from error
