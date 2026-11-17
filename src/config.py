import os
from pathlib import Path

RANDOM_STATE = 42

PROJECT_NAME = "eligibilite-livraison-express"
MODEL_VERSION = "1.0.0"
DEFAULT_THRESHOLD = 0.5

ARTIFACTS_DIR = Path("artifacts")

# SQLite en dev, PostgreSQL en prod : seul l'URL change (ADR-0001).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///orders.db")

# Snapshots d'entraînement DuckLake (ADR-0001) : catalogue SQL + fichiers Parquet.
DUCKLAKE_CATALOG_URL = os.getenv("DUCKLAKE_CATALOG_URL", "sqlite:///ducklake.sqlite")
DUCKLAKE_DATA_PATH = os.getenv("DUCKLAKE_DATA_PATH", "ducklake_data/")
# Source de l'entraînement : "synthetic" (générateur de dev) ou "ducklake" (commandes réelles).
TRAINING_SOURCE = os.getenv("TRAINING_SOURCE", "synthetic")

# Registre de modèles MLflow : SQLite en dev, PostgreSQL en prod (ADR-0002).
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
# Racine des artefacts : dossier local par défaut, URI s3:// possible plus tard.
MLFLOW_ARTIFACT_ROOT = os.getenv("MLFLOW_ARTIFACT_ROOT")
MLFLOW_EXPERIMENT = "livraison-express"
REGISTERED_MODEL_NAME = "express-delivery"
CHAMPION_ALIAS = "champion"
PROMOTION_METRIC = "roc_auc"
