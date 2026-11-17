#!/bin/sh
# Point d'entrée de l'image (ADR-0003, ADR-0004).
#   api      : applique les migrations puis lance l'API (défaut)
#   train    : lance une tâche d'entraînement ponctuelle
#   migrate  : applique seulement les migrations
#   autre    : exécute la commande telle quelle (ex. sh)
set -e

case "$1" in
  api)
    alembic upgrade head
    exec uvicorn src.serving.api:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  train)
    exec python -m src.training.pipeline
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
