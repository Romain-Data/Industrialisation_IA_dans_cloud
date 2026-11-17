# ADR-0002 : Stockage des artefacts de modèles

- Status: Accepted
- Date: 2026-10-09
- Deciders: Romain
- Tags: `mlops`

## Context

Les artefacts de modèles doivent être stockés et versionnés pour garder un historique des performances du modèle et pouvoir revenir à une version précédente (rollback) si besoin.

Avant cette décision, l'entraînement écrasait à chaque exécution un unique fichier `artifacts/express_delivery_model.joblib` (avec `metrics.json` et `features.json`), et le service le chargeait directement depuis ce dossier : aucun historique, aucun rollback. MLflow était déjà utilisé pour journaliser les runs, mais sans registre de modèles et sans emplacement de stockage fixé (deux `mlflow.db` et deux `mlruns/` coexistaient).

Contraintes : MacBook Pro M1 en dev, une partie de VPS en prod, et une base SQLite en dev / PostgreSQL en prod déjà retenue pour les commandes (ADR-0001).

## Decision

Nous utilisons MLflow (tracking et Model Registry) comme seul lieu de stockage et de versionnement des modèles. Le backend du registre est SQLite en dev et PostgreSQL en prod, choisi par la variable d'environnement `MLFLOW_TRACKING_URI`. Les fichiers d'artefacts sont stockés sur disque (dossier `mlartifacts/` en dev, disque du VPS en prod), à l'emplacement donné par `MLFLOW_ARTIFACT_ROOT`.

Chaque entraînement enregistre une nouvelle version du modèle `express-delivery` avec ses paramètres, ses métriques et sa liste de variables (`features.json`, journalisé dans le run). L'alias `champion` désigne la version servie : il est déplacé automatiquement vers la nouvelle version uniquement si son `roc_auc` est strictement supérieur à celui du champion actuel (ou s'il n'y a pas encore de champion, ou si le champion a été entraîné sur un autre schéma de données : voir la mise à jour du 2026-11-17). Le service charge `models:/express-delivery@champion`. Un rollback consiste à replacer manuellement l'alias sur une version antérieure, sans réentraîner. Les fichiers `joblib`, `metrics.json` et `features.json` écrits à la main dans `artifacts/` sont supprimés.

### Justification

- **MLflow** : déjà présent comme dépendance et déjà appelé par l'entraînement ; il fournit versions, métriques par version et alias, ce qui couvre l'historique et le rollback sans code maison.
- **Même schéma que l'ADR-0001** : SQLite en dev, PostgreSQL en prod, bascule par URL de connexion, donc pas de nouveau mode de fonctionnement à apprendre.
- **Alias plutôt que numéro de version dans le code** : le service n'a pas à connaître la version ; changer de version ou revenir en arrière ne touche pas au code ni au déploiement des fichiers.
- **`roc_auc` comme critère de promotion** : il mesure la qualité du classement des scores indépendamment du seuil de décision, il est déjà calculé à l'entraînement et il permet de comparer deux versions de façon stable. La comparaison stricte évite de changer de champion à chaque réentraînement à performance égale.
- **Disque du VPS plutôt que MinIO** : MinIO sur la même machine n'apporterait pas de durabilité supplémentaire (même disque, même panne) et ajouterait un service, des identifiants S3 et un point de configuration, en plus de PostgreSQL. Comme la racine des artefacts MLflow est une URI, passer plus tard à `s3://` (MinIO ou S3 géré) ne demande qu'un changement de configuration.

## Consequences

**Positives**
- Historique complet des versions et de leurs métriques ; rollback par simple déplacement d'alias.
- Entraînements traçables : chaque version renvoie à son run (paramètres, métriques, variables).
- Une seule source pour le modèle servi ; plus de fichier écrasé par erreur.
- Migration vers un stockage objet possible par configuration.

**Négatives**
- Le service dépend du registre MLflow au démarrage : sans base MLflow joignable ou sans alias `champion`, le modèle n'est pas chargé (le service démarre sans modèle, comme avant, mais n'est pas prêt).
- Les artefacts sur le disque du VPS sont perdus avec la machine : une sauvegarde hors machine est nécessaire.
- Le critère `roc_auc` ignore le coût respectif des faux positifs et des faux négatifs, et peut paraître flatteur si les classes sont déséquilibrées.
- La base du registre en prod ajoute des données à sauvegarder à côté de celles des commandes.
- Écart possible de comportement entre SQLite et PostgreSQL pour le backend MLflow, comme pour l'ADR-0001.

**Neutres**
- Il faut décider combien de versions conserver (aucune purge n'est en place).
- `GET /v1/model` (séance 3) devra lire ses métriques et ses variables dans MLflow, depuis la version portant l'alias `champion`.
- Le stockage des prédictions batch (`batch_predictions.csv`) reste dans `artifacts/` : ce n'est pas un artefact de modèle.

**Mesures d'atténuation**
- Sauvegarder régulièrement hors machine le dossier d'artefacts et la base du registre (par exemple `rsync` ou `restic`).
- Vérifier la disponibilité du modèle dans la sonde `/health/ready`.
- Ajouter si nécessaire une condition sur le rappel avant promotion, si le coût des faux négatifs devient un sujet.
- Tester le registre sur PostgreSQL avant la mise en production.

## Mise à jour (2026-11-17) : schéma des données

Avec l'alignement du vocabulaire sur l'ERP (ADR-0007), un modèle entraîné sur l'ancien vocabulaire (`pluie`, `premium`...) reste techniquement chargeable, mais ne sait pas traiter les nouvelles valeurs : son `OneHotEncoder` les ignore (`handle_unknown="ignore"`) et la prédiction se dégrade **sans erreur**. Comparer son ROC AUC à celui d'un nouveau modèle n'a pas de sens, puisqu'ils ne sont pas évalués sur les mêmes données.

Chaque run enregistre donc le paramètre `data_schema` (`DATA_SCHEMA_VERSION`, défini dans `src/domain/features.py`, actuellement `erp-v1`). La règle de promotion devient :

- pas de champion, ou champion d'un **autre** `data_schema` (ou sans ce paramètre) → le nouveau modèle est promu d'office ;
- champion du **même** `data_schema` → promotion seulement si le `roc_auc` est strictement supérieur (règle inchangée).

Tout changement futur du vocabulaire ou des variables doit incrémenter `DATA_SCHEMA_VERSION`. Conséquence : un rollback manuel vers une version d'un autre schéma est possible mais à proscrire, l'API refusant désormais l'ancien vocabulaire.

## Alternatives considered

- **Dossiers versionnés à la main (`artifacts/v1.0.0/` + lien `current`)** : sans dépendance, mais l'historique des métriques, l'alias et la traçabilité seraient à coder et à maintenir ; MLflow les fournit déjà.
- **Stockage objet avec versioning (S3, MinIO)** : bonne durabilité si le stockage est hors machine, mais pas de métadonnées de modèle ni d'alias, et un service de plus à exploiter ; gardé comme évolution possible.
- **MinIO sur le VPS** : pas de gain de durabilité sur la même machine, coût d'exploitation supplémentaire ; écarté pour l'instant.
- **DVC / Git LFS** : lie les modèles à l'historique Git, peu adapté à un chargement par le service en production.
- **Promotion manuelle uniquement** : plus sûre, mais une étape humaine de plus à chaque entraînement ; la promotion automatique avec garde-fou `roc_auc` a été préférée, le rollback restant manuel.

## Links

- Related ADRs : [[ADR-0001 - Stockage des commandes]]
- Code : `src/training/registry.py`, `src/training/train.py`, `src/serving/model_loader.py`
- External references :
  - [MLflow Model Registry](https://mlflow.org/docs/latest/ml/model-registry/)
