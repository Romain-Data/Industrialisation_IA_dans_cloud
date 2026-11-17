# Éligibilité à la livraison express

[![CI](https://github.com/Romain-Data/Industrialisation_IA_dans_cloud/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/Romain-Data/Industrialisation_IA_dans_cloud/actions/workflows/ci.yml)
[![Licence : MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

API qui prédit si une commande peut partir en **livraison express**, à partir de ses caractéristiques (distance, poids, stock, météo, zone, etc.).

Ce dépôt est l'industrialisation d'un POC (notebook de régression logistique) : API, file de traitement, registre de modèles, entraînement reproductible, image Docker, CI/CD et déploiement sur un VPS avec Coolify. Il est réalisé dans le cadre du module « Industrialisation de l'IA dans le cloud ».

| Environnement | URL | Déployé depuis |
|---|---|---|
| Preprod | https://express-delivery-preprod.romaincollery.com | branche `develop` |
| Prod | https://express-delivery.romaincollery.com | GitHub Release `vX.Y.Z` |

Documentation interactive de l'API : `/docs` sur chaque environnement.

## Sommaire

- [Fonctionnement](#fonctionnement)
- [API](#api)
- [Démarrage rapide](#démarrage-rapide)
- [Entraînement du modèle](#entraînement-du-modèle)
- [Configuration](#configuration)
- [Tests et qualité](#tests-et-qualité)
- [Déploiement](#déploiement)
- [Structure du dépôt](#structure-du-dépôt)
- [Décisions d'architecture](#décisions-darchitecture)
- [Contribuer](#contribuer)

## Fonctionnement

```text
                    POST /v1/orders                       file (en mémoire)
 client ──────────────────────────────────▶ API FastAPI ───────────────────▶ worker
   │                                           │                                │ prédiction
   │  GET /v1/predictions/{id}                 ▼                                ▼
   └─────────────────────────────────▶  PostgreSQL : commandes, prédictions ◀───┘
                                               │
   PUT /v1/orders/{id}/outcome (résultat réel) │ export des commandes étiquetées
                                               ▼
                       DuckLake (snapshots Parquet versionnés) ──▶ entraînement ──▶ MLflow
                                                                                     │
                                L'API charge le modèle portant l'alias `champion` ◀──┘
```

- **Commandes** : stockées dans une base transactionnelle (SQLite en dev, PostgreSQL en prod) via SQLAlchemy, schéma versionné avec Alembic.
- **Prédictions** : calculées de façon asynchrone par un worker, ou de façon synchrone avec `POST /v1/predictions`.
- **Résultat réel** : une fois la livraison faite, `PUT /v1/orders/{id}/outcome` enregistre si elle a pu partir en express. C'est la cible d'entraînement.
- **Entraînement** : les commandes étiquetées sont figées dans un snapshot DuckLake, ce qui rend chaque entraînement reproductible. Le modèle est enregistré dans MLflow et ne devient `champion` que si son ROC AUC est meilleur que celui du champion actuel.

## API

Le contrat de l'API est [`openapi.yml`](openapi.yml) ; les tests vérifient que l'implémentation le respecte.

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/health` | Le service répond |
| `GET` | `/health/ready` | Modèle chargé, base joignable, schéma à jour, worker actif (503 sinon) |
| `POST` | `/v1/orders` | Enregistrer une commande ; sa prédiction est calculée en arrière-plan (202) |
| `GET` | `/v1/orders/{order_id}` | Relire une commande |
| `PUT` | `/v1/orders/{order_id}/outcome` | Enregistrer le résultat réel d'une commande |
| `POST` | `/v1/predictions` | Prédire immédiatement l'éligibilité d'une commande |
| `GET` | `/v1/predictions/{order_id}` | Relire la prédiction d'une commande |
| `GET` | `/v1/model` | Model card du modèle en service (métriques, variables, limites) |

Exemple :

```bash
curl -X POST https://express-delivery-preprod.romaincollery.com/v1/predictions \
  -H "Content-Type: application/json" \
  -d '{"hour": 14, "day_of_week": 2, "weekend": 0, "distance_km": 3.5,
       "order_value_eur": 89.9, "weight_kg": 2.4, "stock_available": 1,
       "preparation_time_min": 18, "carrier_capacity": 0.85,
       "weather": "normal", "delivery_zone": "centre", "customer_type": "premium"}'
```

```json
{"order_id": "CMD-1a2b3c4d", "express_eligible": true, "decision": "oui",
 "probability": 0.9377, "model_version": "1.0.0", "predicted_at": "...", "latency_ms": 24.2}
```

## Démarrage rapide

### Avec Docker Compose (recommandé)

Prérequis : Docker.

```bash
docker compose up -d --build        # PostgreSQL + API sur http://localhost:8000
docker compose run --rm train       # premier entraînement (données synthétiques)
docker compose restart api          # l'API charge le modèle champion
curl http://localhost:8000/health/ready
```

`docker compose down` arrête la stack ; ajouter `-v` efface aussi les données.

### En local avec uv

Prérequis : Python 3.12 et [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                     # dépendances, dont les outils de dev
uv run alembic upgrade head                 # schéma de la base SQLite (orders.db)
uv run python -m src.training.pipeline      # entraînement -> mlflow.db + mlartifacts/
uv run uvicorn src.serving.api:app --reload # API sur http://localhost:8000
```

Interface MLflow (runs, métriques, versions du modèle) :

```bash
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db
# avec Docker Compose :
PGPASSWORD=express uv run mlflow ui --backend-store-uri postgresql+psycopg://express@localhost:5433/mlflow
```

## Entraînement du modèle

La source des données est choisie par `TRAINING_SOURCE` :

| Valeur | Données |
|---|---|
| `synthetic` (défaut) | Générateur de commandes synthétiques (`src/infrastructure/dev/collect.py`) |
| `ducklake` | Commandes réelles avec résultat connu, figées dans un nouveau snapshot DuckLake (au moins 50) |

```bash
TRAINING_SOURCE=ducklake uv run python -m src.training.pipeline
```

Chaque run MLflow enregistre ses métriques, la liste des variables et la provenance des données (numéro de snapshot DuckLake). L'API charge le champion **au démarrage** : il faut la redémarrer après un entraînement qui le change. Pour revenir à un modèle précédent, il suffit de replacer l'alias `champion` sur une version antérieure dans MLflow, puis de redémarrer l'API.

## Configuration

Toute la configuration passe par des variables d'environnement ([`src/config.py`](src/config.py)).

| Variable | Défaut (dev) | Rôle |
|---|---|---|
| `DATABASE_URL` | `sqlite:///orders.db` | Base des commandes et prédictions |
| `MLFLOW_TRACKING_URI` | `sqlite:///mlflow.db` | Registre de modèles MLflow |
| `MLFLOW_ARTIFACT_ROOT` | `./mlartifacts` | Fichiers des modèles |
| `DUCKLAKE_CATALOG_URL` | `sqlite:///ducklake.sqlite` | Catalogue des snapshots d'entraînement |
| `DUCKLAKE_DATA_PATH` | `ducklake_data/` | Fichiers Parquet des snapshots |
| `TRAINING_SOURCE` | `synthetic` | Source de l'entraînement (`synthetic` ou `ducklake`) |
| `PORT` | `8000` | Port de l'API dans le conteneur |

En PostgreSQL, les URL utilisent le driver psycopg 3 : `postgresql+psycopg://utilisateur@hôte:5432/base`. Le mot de passe peut être fourni par la variable standard `PGPASSWORD` plutôt que dans l'URL (c'est ce que fait `docker-compose.yml`). Au démarrage, le conteneur crée les bases `mlflow` et `ducklake` si elles n'existent pas, puis applique les migrations.

## Tests et qualité

```bash
uv run pytest           # tests unitaires, d'API, de migrations et d'entraînement
uv run ruff check .     # lint
uv run pylint src       # qualité (score minimal dans pyproject.toml)
```

## Déploiement

Le dépôt suit **GitFlow** (détails dans [CONTRIBUTING.md](CONTRIBUTING.md)). La CI GitHub Actions ([`ci.yml`](.github/workflows/ci.yml)) :

1. à chaque push et pull request : `ruff`, `pylint`, `pytest` ;
2. sur `develop` et sur une GitHub Release : construit l'image `linux/amd64`, vérifie qu'elle démarre, la scanne avec Trivy, la publie sur `ghcr.io/romain-data/industrialisation_ia_dans_cloud` (tags `sha-xxxxxxx` et `X.Y.Z`) ;
3. déploie avec Coolify : `develop` → preprod, release → prod. Coolify ne met la nouvelle version en service que si `/health/ready` répond.

L'image Docker ([`Dockerfile`](Dockerfile)) est construite en deux étapes avec uv, tourne avec un utilisateur non root et sert à la fois l'API (`api`, par défaut), l'entraînement (`train`) et les migrations (`migrate`).

## Structure du dépôt

```text
src/
  domain/          règles métier : variables, nettoyage, validation
  abstraction/     interfaces (stockage des commandes, file, snapshots, collecte)
  infrastructure/  implémentations : SQLAlchemy, DuckLake, migrations, bootstrap
  serving/         API FastAPI, worker, prédiction
  training/        pipeline d'entraînement, registre MLflow
migrations/        migrations Alembic
tests/             tests pytest
IndusIAdansCloud/  notes Obsidian, dont les ADR
openapi.yml        contrat de l'API
```

## Décisions d'architecture

Les choix structurants sont documentés sous forme d'ADR dans [`IndusIAdansCloud/ADR/`](IndusIAdansCloud/ADR/) :

- [ADR-0001](IndusIAdansCloud/ADR/ADR-0001%20-%20Stockage%20commande%20clients.md) : stockage des commandes (SQLAlchemy, PostgreSQL, DuckLake)
- [ADR-0002](IndusIAdansCloud/ADR/ADR-0002%20-%20Stockage%20des%20artefacts%20de%20modele.md) : stockage des modèles (MLflow, alias `champion`)
- [ADR-0003](IndusIAdansCloud/ADR/ADR-0003%20-%20Choix%20de%20la%20plateforme%20de%20d%C3%A9ploiement.md) : plateforme de déploiement (Coolify, Docker)
- [ADR-0004](IndusIAdansCloud/ADR/ADR-0004%20-%20Strat%C3%A9gie%20de%20d%C3%A9ploiement.md) : stratégie de déploiement (CI, GitFlow, preprod / prod)
- [ADR-0005](IndusIAdansCloud/ADR/ADR-0005%20-%20S%C3%A9curisation.md) : sécurisation (secrets, image, CI, dépôt, limites connues)
- [ADR-0006](IndusIAdansCloud/ADR/ADR-0006%20-%20File%20d'attente.md) : file d'attente des commandes (en mémoire, worker)

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md). Merci de respecter le [code de conduite](CODE_OF_CONDUCT.md) et de signaler les failles de sécurité selon [SECURITY.md](SECURITY.md).

## Licence

[MIT](LICENSE)
