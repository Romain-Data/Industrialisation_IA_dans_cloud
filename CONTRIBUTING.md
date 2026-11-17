# Contribuer

Merci de votre intérêt pour le projet ! Ce guide explique comment proposer une modification. En participant, vous acceptez de respecter le [code de conduite](CODE_OF_CONDUCT.md). Pour une faille de sécurité, n'ouvrez pas d'issue publique : suivez [SECURITY.md](SECURITY.md).

## Signaler un bug ou proposer une idée

Ouvrez une [issue](https://github.com/Romain-Data/Industrialisation_IA_dans_cloud/issues) en précisant :

- pour un bug : ce que vous avez fait, ce que vous attendiez, ce qui s'est passé (requête, réponse, logs) et l'environnement (local, preprod, prod, version) ;
- pour une idée : le besoin, et pourquoi la solution actuelle ne suffit pas.

## Mettre en place l'environnement

Prérequis : Python 3.12, [uv](https://docs.astral.sh/uv/), Docker (pour la stack complète).

```bash
git clone https://github.com/Romain-Data/Industrialisation_IA_dans_cloud.git
cd Industrialisation_IA_dans_cloud
git switch develop
uv sync                 # dépendances, y compris les outils de dev
uv run pytest           # tout doit passer avant de commencer
```

La stack complète (PostgreSQL + API) se lance avec `docker compose up -d --build` : voir le [README](README.md#démarrage-rapide).

## Branches : GitFlow

| Branche | Rôle | Créée depuis | Fusionnée dans |
|---|---|---|---|
| `main` | Versions publiées, uniquement | — | — |
| `develop` | Intégration ; déployée automatiquement en **preprod** | — | — |
| `feature/<sujet>` | Nouvelle fonctionnalité ou évolution | `develop` | `develop` |
| `release/<x.y.z>` | Préparation d'une version (corrections mineures, version, notes) | `develop` | `main` **et** `develop` |
| `hotfix/<x.y.z>` | Correction urgente de la prod | `main` | `main` **et** `develop` |

Préfixes acceptés pour les branches de travail : `feature/`, `fix/`, `docs/`, `chore/`, `ci/`, `perf/`. Nom court en minuscules, mots séparés par des tirets : `feature/model-card`.

Règles :

- on ne pousse jamais directement sur `main` ni sur `develop` : tout passe par une pull request ;
- les fusions se font sans fast-forward (`--no-ff`) pour garder la trace de chaque branche ;
- la **prod** ne se déploie qu'en publiant une **GitHub Release** `vX.Y.Z` sur `main`.

### Publier une version

```bash
git switch develop && git pull
git switch -c release/0.2.0
# derniers ajustements, puis PR release/0.2.0 -> main
# après fusion :
git switch main && git pull
git tag -a v0.2.0 -m "v0.2.0" && git push origin v0.2.0
gh release create v0.2.0 --generate-notes      # déclenche la construction et le déploiement prod
# reporter la release dans develop :
git switch develop && git merge --no-ff main && git push
```

Les versions suivent [SemVer](https://semver.org/lang/fr/) : majeure pour un changement incompatible du contrat d'API, mineure pour une fonctionnalité, correctif sinon.

## Faire une modification

1. Créez une branche depuis `develop` (voir ci-dessus).
2. Faites des commits petits et ciblés, au format [Conventional Commits](https://www.conventionalcommits.org/fr/) :
   `type: description courte à l'impératif`, avec `type` parmi `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `ci`, `chore`.
   Exemple : `feat: add GET /v1/model model card`.
3. Vérifiez localement :

   ```bash
   uv run ruff check .
   uv run pylint src
   uv run pytest
   ```

4. Ouvrez une pull request vers `develop`, en décrivant le **pourquoi** du changement et la façon de le tester. La CI doit être verte avant la fusion.

## Conventions du code

- **Couches** : `domain` (règles métier, sans dépendance technique), `abstraction` (interfaces), `infrastructure` (implémentations), `serving` et `training` (points d'entrée). Le code métier ne dépend jamais d'une technologie de stockage.
- **Accès aux données** : uniquement par la couche d'accès (`OrderStore`, `TrainingSnapshotStore`) ; pas de SQL ailleurs.
- **Configuration** : uniquement par variables d'environnement, déclarées dans `src/config.py` et documentées dans le README.
- **Contrat d'API** : toute route ou tout schéma ajouté ou modifié l'est d'abord dans [`openapi.yml`](openapi.yml). Les tests comparent le contrat et l'API générée.
- **Base de données** : tout changement de modèle SQLAlchemy s'accompagne d'une migration Alembic (`uv run alembic revision -m "..."`), **additive et rétrocompatible** (ajout avant suppression, en deux versions), car une version et la précédente doivent pouvoir tourner sur le même schéma.
- **Tests** : toute fonctionnalité ou correction est accompagnée de tests pytest.
- **Langue** : code et noms en anglais, documentation, docstrings et messages destinés aux utilisateurs en français.

## Décisions d'architecture (ADR)

Un choix structurant (technologie, stockage, déploiement, sécurité) fait l'objet d'un ADR dans [`IndusIAdansCloud/ADR/`](IndusIAdansCloud/ADR/), à partir du modèle `model.md` : contexte, décision, justification, conséquences (y compris négatives) et alternatives écartées. Proposez l'ADR dans la même pull request que le changement, ou avant.
