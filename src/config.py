import os
from pathlib import Path

RANDOM_STATE = 42

PROJECT_NAME = "eligibilite-livraison-express"
MODEL_VERSION = "1.0.0"
DEFAULT_THRESHOLD = 0.5

ARTIFACTS_DIR = Path("artifacts")

# SQLite en dev, PostgreSQL en prod : seul l'URL change (ADR-0001).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///orders.db")
