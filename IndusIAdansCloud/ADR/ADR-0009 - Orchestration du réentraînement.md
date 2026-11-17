# ADR-0009 : Orchestration de l'import ERP et du réentraînement

- Status: Accepted
- Date: 2026-11-17
- Deciders: Romain
- Tags: `mlops`, `orchestration`

## Context

Les commandes de l'ERP arrivent en continu dans sa base analytique MongoDB (ADR-0007). Il faut les importer régulièrement (ETL horaire) et réentraîner le modèle quand assez de nouvelles données sont disponibles. Le cours le rappelle : **l'entraînement est un processus d'exécution, pas de construction de l'application** ; il ne doit donc pas passer par la CI/CD, et sa fréquence dépend du projet (« on entraîne dès qu'on a suffisamment de nouvelles données »).

Jusqu'ici, l'entraînement en preprod et en prod était une tâche planifiée Coolify, désactivée et lancée à la main : pas de dépendance entre étapes (import puis entraînement), pas de reprise sur erreur, pas d'historique des exécutions. L'ADR-0004 prévoyait aussi que la tâche d'entraînement **redémarre l'API** quand le champion change, ce qui demandait à l'orchestrateur un jeton Coolify, ou l'accès au socket Docker dans un docker-compose.

Contraintes : VPS partagé (mémoire comptée), même code que l'application (ETL, entraînement), mêmes environnements (local, compose, Coolify). Romain utilise déjà Prefect sur un autre projet (VélÔToulouse), où une incompatibilité entre Prefect 3.8 et SQLAlchemy 2.1 empêchait le planificateur de créer les runs.

## Decision

Nous orchestrons l'import ERP et le réentraînement avec **Prefect 3.9.3**, auto-hébergé, et l'API **recharge seule** le nouveau champion.

- **Flow `erp-pipeline`** (`src/orchestration/flows.py`), trois tâches enchaînées :
  1. `import-erp` : import incrémental de l'ERP (ADR-0007), **3 reprises** espacées d'une minute en cas d'échec (MongoDB indisponible) ;
  2. `decide-retraining` : réentraîner si au moins `RETRAIN_MIN_NEW_ORDERS` (500 par défaut) nouvelles commandes étiquetées sont arrivées depuis le dernier entraînement sur ces données (lu dans MLflow), ou si aucun entraînement n'a encore eu lieu ;
  3. `train` : entraînement sur un snapshot DuckLake, promotion selon l'ADR-0002 (**1 reprise**).
  Si l'import échoue, l'entraînement n'a pas lieu.
- **Déploiements** : `horaire` (cron `ERP_PIPELINE_CRON`, `0 * * * *` par défaut) et `reentrainement-force` (lancé à la main depuis l'interface, réentraîne sans condition).
- **Exécution** : un serveur Prefect (image officielle `prefecthq/prefect:3.9.3-python3.12`, API, interface et planificateur, base SQLite sur un volume) et un processus `serve()` qui contient notre code et exécute les runs (mode `orchestrator` de l'image). Pas de work pool ni de worker séparé.
- **Image** : Prefect est dans un groupe de dépendances `orchestration` et une **cible Docker séparée** `orchestrator` ; l'image de l'API n'en contient pas.
- **Rechargement du modèle** : l'API lit la version du champion toutes les `MODEL_RELOAD_INTERVAL_SECONDS` (60 s) et recharge le modèle et sa model card quand elle change (`ModelReloader`). Si MLflow est injoignable, le modèle en service est conservé. Cela **remplace** le redémarrage de l'API prévu par l'ADR-0004.

### Justification

- **Prefect plutôt qu'Airflow** : un serveur et un processus Python suffisent ; Airflow (scheduler, webserver, base de métadonnées, plus d'1 Go de mémoire) est disproportionné pour un flow horaire sur un VPS partagé. Prefect est en Python pur, testable avec `prefect_test_harness`, et déjà connu de Romain.
- **Prefect plutôt que des tâches planifiées Coolify** : dépendances entre étapes, reprises automatiques, historique et durée de chaque run, déclenchement manuel paramétré ; et le même orchestrateur fonctionne en local, en compose et sur le VPS.
- **Version 3.9.3** : l'incompatibilité avec SQLAlchemy 2.1 (PrefectHQ/prefect#23199) est corrigée depuis octobre 2026. Vérifié le 2026-11-17 avec le serveur officiel 3.9.3 : les runs planifiés sont créés et exécutés.
- **Réentraîner sur un seuil de nouvelles données** : réentraîner à chaque import horaire produirait des modèles presque identiques et encombrerait le registre ; ne réentraîner qu'à la main ferait vieillir le modèle.
- **`serve()`** : le processus qui contient le code exécute lui-même les runs ; pas de work pool à configurer, une seule image à construire pour notre code.
- **SQLite pour le serveur Prefect** : sa base ne contient que l'historique des runs ; une base PostgreSQL de plus n'apporterait rien à cette échelle (un seul serveur).
- **Rechargement par l'API plutôt que redémarrage** : aucun privilège à donner à l'orchestrateur (ni jeton Coolify, ni socket Docker), aucune coupure de service, et le même mécanisme partout. Le coût (une requête au registre par minute) est négligeable.

## Consequences

**Positives**
- Les nouvelles commandes de l'ERP sont importées toutes les heures, et le modèle suit les données sans intervention.
- Chaque exécution est visible (durée, état, logs, motif de la décision de réentraîner) dans l'interface Prefect.
- Un nouveau champion est servi en moins d'une minute, sans redémarrage.
- L'image de l'API ne grossit pas.

**Négatives**
- Deux services de plus à faire tourner (serveur Prefect et orchestrateur) et une deuxième image à construire, scanner et publier.
- Le seuil de réentraînement (500) est un choix arbitraire, à ajuster avec l'expérience.
- Un champion moins bon peut être servi automatiquement si la règle de promotion le permet (schéma de données différent, ADR-0002) : il n'y a pas de validation humaine avant la mise en service.
- Pendant au plus une minute après une promotion, l'API sert encore l'ancien modèle.
- L'interface Prefect ne doit pas être exposée sur Internet : elle n'a pas d'authentification dans la version auto-hébergée.

**Neutres**
- Le flow peut aussi être lancé sans serveur (`python -m src.etl.erp_import`, puis l'entraînement) : l'orchestration n'est pas indispensable au fonctionnement de l'application.
- L'historique des runs vit dans la base SQLite du serveur Prefect ; le perdre ne perd aucune donnée métier (le journal `erp_imports` et MLflow restent la référence).

**Mesures d'atténuation**
- Interface Prefect publiée seulement en local (`127.0.0.1`) ; accès par tunnel SSH sur le VPS.
- Limites de mémoire sur les deux services ; l'entraînement reste court (régression logistique).
- Le seuil, la planification et l'intervalle de rechargement sont des variables d'environnement.

## Alternatives considered

- **Airflow** (exemple du cours) : référence du marché, mais lourd pour un VPS partagé ; écarté.
- **Tâches planifiées Coolify** : déjà en place, mais pas un orchestrateur (ni dépendances, ni reprises, ni historique) ; gardées seulement comme secours manuel.
- **Entraînement dans la CI/CD** : contraire au principe du cours (l'entraînement est une exécution, pas une construction) ; écarté.
- **Cron dans un conteneur** : léger, mais sans reprises, historique ni interface ; écarté.
- **Dagster** : bonne modélisation des données (assets), mais nouvel outil à apprendre pour un seul flow ; écarté.
- **Redémarrer l'API après une promotion** (ADR-0004) : demande un jeton Coolify ou le socket Docker, et coupe le service ; remplacé par le rechargement.
- **Endpoint de rechargement appelé par l'orchestrateur** : immédiat, mais il faudrait le sécuriser (l'API n'a pas d'authentification, ADR-0005) ; écarté au profit de la lecture périodique.

## Links

- Related ADRs : [[ADR-0002 - Stockage des artefacts de modele]], [[ADR-0004 - Stratégie de déploiement]], [[ADR-0007 - PostgreSQL, MongoDB ou autre]]
- Code : `src/orchestration/flows.py`, `src/orchestration/serve.py`, `src/training/retraining.py`, `src/serving/model_reloader.py`
- External references :
  - [Prefect : serve()](https://docs.prefect.io/v3/deploy/run-flows-in-local-processes)
  - [PrefectHQ/prefect#23199 : SQLAlchemy 2.1 et le planificateur](https://github.com/PrefectHQ/prefect/issues/23199)
