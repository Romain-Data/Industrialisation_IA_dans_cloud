"""Configuration de l'application : constantes et variables d'environnement, sans secret."""

import os
from pathlib import Path

RANDOM_STATE = 42

PROJECT_NAME = "eligibilite-livraison-express"
# 2.0.0 : vocabulaire des données aligné sur l'ERP (ADR-0007), incompatible avec 1.x.
MODEL_VERSION = "2.0.0"
DEFAULT_THRESHOLD = 0.5

ARTIFACTS_DIR = Path("artifacts")

# SQLite en dev, PostgreSQL en prod : seul l'URL change (ADR-0001).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///orders.db")

# Snapshots d'entraînement DuckLake (ADR-0001) : catalogue SQL + fichiers Parquet.
DUCKLAKE_CATALOG_URL = os.getenv("DUCKLAKE_CATALOG_URL", "sqlite:///ducklake.sqlite")
DUCKLAKE_DATA_PATH = os.getenv("DUCKLAKE_DATA_PATH", "ducklake_data/")
# Source de l'entraînement : "synthetic" (générateur de dev) ou "ducklake" (commandes réelles).
TRAINING_SOURCE = os.getenv("TRAINING_SOURCE", "synthetic")

# Source des commandes ERP : base analytique MongoDB, en lecture seule (ADR-0007).
ERP_MONGO_URI = os.getenv("ERP_MONGO_URI", "mongodb://localhost:27017")
ERP_MONGO_DATABASE = os.getenv("ERP_MONGO_DATABASE", "livraison_express")
ERP_MONGO_COLLECTION = os.getenv("ERP_MONGO_COLLECTION", "orders")
ERP_IMPORT_BATCH_SIZE = int(os.getenv("ERP_IMPORT_BATCH_SIZE", "1000"))

# Orchestration Prefect (ADR-0009) : import ERP toutes les heures, réentraînement dès
# qu'assez de nouvelles commandes étiquetées sont arrivées.
ERP_PIPELINE_CRON = os.getenv("ERP_PIPELINE_CRON", "0 * * * *")
RETRAIN_MIN_NEW_ORDERS = int(os.getenv("RETRAIN_MIN_NEW_ORDERS", "500"))

# Registre de modèles MLflow : SQLite en dev, PostgreSQL en prod (ADR-0002).
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
# Racine des artefacts : dossier local par défaut, URI s3:// possible plus tard.
MLFLOW_ARTIFACT_ROOT = os.getenv("MLFLOW_ARTIFACT_ROOT")
MLFLOW_EXPERIMENT = "livraison-express"
REGISTERED_MODEL_NAME = "express-delivery"
CHAMPION_ALIAS = "champion"
# Candidat meilleur en ROC AUC mais qui viole un garde-fou métier : un humain tranche (ADR-0010).
CHALLENGER_ALIAS = "challenger"
# Intervalle de vérification du champion par l'API (0 = pas de rechargement automatique).
MODEL_RELOAD_INTERVAL_SECONDS = int(os.getenv("MODEL_RELOAD_INTERVAL_SECONDS", "60"))
PROMOTION_METRIC = "roc_auc"
