# Image unique : API, worker et entraînement (ADR-0003).
# Construire pour le VPS depuis le Mac M1 :
#   docker build --platform linux/amd64 -t express-delivery .

ARG PYTHON_VERSION=3.12

# --- Étape 1 : installation des dépendances avec uv ---------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dépendances seules d'abord : cette couche reste en cache tant que le lock ne change pas.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# --- Étape 2 : image d'exécution, sans uv ni cache ----------------------------
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000 \
    GIT_PYTHON_REFRESH=quiet \
    MLFLOW_DISABLE_AGENT_HINT=1

# curl : utilisé par le health check de Coolify (ADR-0003).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app src ./src
COPY --chown=app:app docker-entrypoint.sh ./

# /app/mlartifacts : racine des artefacts MLflow (volume en prod, ADR-0003).
# /app/ducklake    : fichiers Parquet des snapshots d'entraînement (volume en prod, ADR-0001).
RUN chmod +x docker-entrypoint.sh \
    && mkdir -p /app/mlartifacts /app/ducklake \
    && chown app:app /app /app/mlartifacts /app/ducklake

USER app

# Extensions DuckDB installées au build : aucun téléchargement au démarrage en prod.
# Catalogue DuckLake PostgreSQL en prod : l'extension sqlite (dev) n'est pas embarquée.
RUN python -c "import duckdb; c = duckdb.connect(); [c.install_extension(e) for e in ('ducklake', 'postgres')]"

ENV DUCKLAKE_DATA_PATH=/app/ducklake/

EXPOSE 8000

# /health/ready répond 503 tant qu'aucun modèle champion n'est enregistré.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health/ready', timeout=4)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["api"]
