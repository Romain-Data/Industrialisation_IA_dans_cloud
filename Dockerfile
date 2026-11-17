# Une base commune, deux images (ADR-0003, ADR-0009) :
#   - api (cible par défaut) : API, worker, entraînement, ETL. Sans Prefect.
#   - orchestrator           : la même, plus Prefect, pour exécuter les flows planifiés.
# Construire pour le VPS depuis le Mac M1 :
#   docker build --platform linux/amd64 -t express-delivery .
#   docker build --platform linux/amd64 --target orchestrator -t express-delivery-orchestrator .

ARG PYTHON_VERSION=3.12

# --- Dépendances (uv) ------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dépendances seules d'abord : cette couche reste en cache tant que le lock ne change pas.
# Aucun groupe (ni dev, ni orchestration) : l'image de l'API reste minimale.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-default-groups --no-install-project

# Même environnement, plus le groupe `orchestration` (Prefect).
FROM builder AS builder-orchestrator
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-default-groups --group orchestration --no-install-project

# --- Base d'exécution commune, sans uv ni cache ------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000 \
    GIT_PYTHON_REFRESH=quiet \
    MLFLOW_DISABLE_AGENT_HINT=1 \
    DUCKLAKE_DATA_PATH=/app/ducklake/

# Correctifs de sécurité Debian (scan Trivy en CI) + curl, utilisé par le health check de Coolify.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

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

ENTRYPOINT ["./docker-entrypoint.sh"]

# --- Image de l'orchestrateur (Prefect serve) ----------------------------------------
FROM runtime AS orchestrator

COPY --from=builder-orchestrator --chown=app:app /app/.venv /app/.venv

# Extensions DuckDB installées au build : aucun téléchargement au démarrage en prod.
RUN python -c "import duckdb; c = duckdb.connect(); [c.install_extension(e) for e in ('ducklake', 'postgres')]"

# Processus d'exécution des flows : pas d'API HTTP, donc pas de health check HTTP.
HEALTHCHECK NONE
CMD ["orchestrator"]

# --- Image de l'API (cible par défaut : la dernière) ---------------------------------
FROM runtime AS api

COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Extensions DuckDB installées au build : aucun téléchargement au démarrage en prod.
# Catalogue DuckLake PostgreSQL en prod : l'extension sqlite (dev) n'est pas embarquée.
RUN python -c "import duckdb; c = duckdb.connect(); [c.install_extension(e) for e in ('ducklake', 'postgres')]"

EXPOSE 8000

# /health/ready répond 503 tant qu'aucun modèle champion n'est enregistré.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health/ready', timeout=4)"

CMD ["api"]
