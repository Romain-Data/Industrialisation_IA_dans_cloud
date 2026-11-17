#!/bin/sh
# Point d'entrée de l'image (ADR-0003, ADR-0004).
#   api      : applique les migrations puis lance l'API (défaut)
#   train    : lance une tâche d'entraînement ponctuelle
#   etl      : importe les nouvelles commandes de l'ERP (MongoDB) dans notre base
#   migrate  : applique seulement les migrations
#   autre    : exécute la commande telle quelle (ex. sh)
set -e

case "$1" in
  api)
    python -m src.infrastructure.bootstrap
    alembic upgrade head
    exec uvicorn src.serving.api:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  train)
    python -m src.infrastructure.bootstrap
    exec python -m src.training.pipeline
    ;;
  etl)
    python -m src.infrastructure.bootstrap
    alembic upgrade head
    exec python -m src.etl.erp_import
    ;;
  migrate)
    python -m src.infrastructure.bootstrap
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
