# ADR-0005 : Sécurisation

- Status: Accepted
- Date: 2026-11-17
- Deciders: Romain
- Tags: `security`, `infra`, `ci-cd`

## Context

L'application est publique sur Internet (preprod et prod en HTTPS), son dépôt GitHub est public, et elle tourne sur un VPS partagé avec d'autres projets. Elle manipule des données de commandes, des modèles entraînés et des secrets d'infrastructure : mots de passe PostgreSQL, jeton de l'API Coolify.

Les surfaces à protéger sont : le dépôt (fuite de secrets, modification non relue), la chaîne de livraison (CI, registre d'images, déploiement), l'image Docker (vulnérabilités, privilèges), l'infrastructure (bases, API Coolify, réseau) et l'application elle-même (entrées, modèles chargés).

Contraintes : projet de formation porté par une seule personne, ressources limitées sur le VPS, et pas de budget pour des services payants. Les mesures doivent être proportionnées, automatisées quand c'est possible, et les limites assumées doivent être écrites.

## Decision

Nous appliquons une défense en profondeur proportionnée, en automatisant les contrôles dans la CI et dans GitHub, et en gardant les secrets hors du dépôt et de l'image.

- **Secrets** : aucun secret dans le dépôt ni dans l'image. `.env` est ignoré par git et par Docker (`.dockerignore`). Les secrets d'exécution (URL de base avec mot de passe) sont des variables d'environnement Coolify ; les mots de passe PostgreSQL sont générés aléatoirement à la création (`secrets.token_urlsafe`), et personne n'a besoin de les connaître. Les secrets de déploiement (`COOLIFY_URL`, `COOLIFY_TOKEN`) sont des secrets GitHub Actions. En local, les identifiants ne figurent pas dans les URL (`PGPASSWORD`).
- **Jeton Coolify** : limité au seul projet « Indus IA dans le Cloud », avec les droits `write` et `deploy`. L'API Coolify accepte toutes les IP (ADR-0004) : la protection repose sur ce jeton.
- **Détection de fuite** : l'application GitGuardian analyse chaque pull request ; son check est obligatoire sur `main` et `develop`.
- **Dépôt** : `main` et `develop` sont protégées (pull request et checks « Lint & tests » + GitGuardian obligatoires, pas de push direct ni de force push, règles appliquées aussi aux administrateurs). Seul Romain fusionne vers `main`, donc vers la prod. Le signalement privé de vulnérabilités GitHub est activé et décrit dans `SECURITY.md`.
- **Image Docker** : image de base `python:3.12-slim` avec les correctifs de sécurité Debian appliqués au build, construction en deux étapes (ni uv ni outils de build dans l'image finale), dépendances de prod réduites au nécessaire (`mlflow-skinny`), exécution avec un utilisateur non root `app`.
- **Scan de l'image** : Trivy analyse chaque image avant publication ; la CI échoue sur toute vulnérabilité **critique** corrigeable, et liste les vulnérabilités hautes.
- **Dépendances** : versions figées par `uv.lock` (`uv sync --frozen` en CI et au build).
- **Réseau** : HTTPS assuré par le proxy de Coolify. Les bases PostgreSQL ne sont pas exposées publiquement : elles ne sont joignables que sur le réseau Docker de Coolify. En local, Docker Compose n'expose ses ports que sur `127.0.0.1`.
- **Application** : validation stricte des entrées par Pydantic (bornes, valeurs autorisées, champs inconnus refusés) ; les erreurs internes renvoient un message générique, sans trace. Les modèles sont sérialisés au format skops et non pickle : le chargement d'un modèle n'exécute pas de code arbitraire.

### Justification

- **Secrets hors du dépôt et de l'image** : un dépôt public et une image publique sur GHCR sont lisibles par tous ; un secret qui y entre doit être considéré comme compromis.
- **Jeton limité au projet** : en cas de fuite, l'attaquant ne peut agir que sur cette application, pas sur les autres projets du VPS (RAG, VélÔToulouse).
- **Contrôles automatisés** : sur un projet tenu par une seule personne, un contrôle qui dépend de la vigilance humaine finit par être oublié ; un check obligatoire, non.
- **Non root et image minimale** : limitent ce qu'un attaquant peut faire s'il exploite une faille de l'application, et réduisent le nombre de paquets vulnérables.
- **Seuil Trivy sur « critique corrigeable »** : bloquer sur toutes les vulnérabilités hautes, y compris sans correctif, rendrait la CI rouge en permanence sans action possible.
- **skops plutôt que pickle** : un modèle est un fichier téléchargé depuis le stockage d'artefacts ; avec pickle, quiconque peut écrire un artefact peut exécuter du code dans l'API.

## Consequences

**Positives**
- Une fuite de secret par le code est détectée avant la fusion, et un secret de prod n'est jamais manipulé à la main.
- Aucune version ne part en prod sans relecture de Romain, tests verts et image scannée.
- Une compromission du jeton de CI reste cantonnée à ce projet.
- Les vulnérabilités critiques des dépendances et du système de l'image sont bloquées avant publication.

**Négatives**
- **L'API n'a pas d'authentification** : n'importe qui peut enregistrer des commandes et, surtout, des résultats réels (`PUT /v1/orders/{id}/outcome`). Des résultats falsifiés empoisonneraient les données d'entraînement DuckLake. C'est le risque principal aujourd'hui ; il est acceptable tant que `TRAINING_SOURCE=synthetic` en prod.
- Pas de limitation de débit : un client peut saturer l'API ou remplir la base.
- L'API Coolify est exposée à Internet : la sécurité du VPS dépend d'un seul jeton.
- L'utilisateur PostgreSQL de l'application est le superutilisateur de son conteneur (il crée les bases `mlflow` et `ducklake` au démarrage) : pas de moindre privilège.
- Les actions GitHub sont référencées par tag de version et non par SHA : une action compromise pourrait être republiée sous le même tag.
- `/docs` et le contrat OpenAPI sont publics, ce qui facilite la découverte de l'API.

**Neutres**
- Trivy ne voit que les vulnérabilités connues ; une faille du code de l'application n'est pas détectée.
- Les vulnérabilités hautes sans correctif restent présentes tant que l'amont ne les corrige pas.

**Mesures d'atténuation (prévues, pas encore en place)**
- Clé d'API (en-tête `X-API-Key`, secret Coolify) obligatoire sur les routes d'écriture, en priorité `PUT /v1/orders/{id}/outcome`, avant de passer `TRAINING_SOURCE=ducklake` en prod.
- Limitation de débit au niveau du proxy de Coolify ou de l'application.
- Dependabot (ou Renovate) pour les mises à jour de dépendances et d'actions, et référencement des actions par SHA.
- Rôles PostgreSQL séparés : un rôle d'administration pour le bootstrap et les migrations, un rôle applicatif limité aux tables.
- Rotation périodique du jeton Coolify et des mots de passe.
- Sauvegardes chiffrées hors du VPS (ADR-0003).

## Alternatives considered

- **Scan de secrets par ggshield en pre-commit** : détecte encore plus tôt, mais demande une installation sur chaque poste ; l'application GitGuardian sur les PR suffit pour une personne ; reporté.
- **Blocage Trivy sur HIGH et CRITICAL** : plus strict, mais bloque sur des vulnérabilités sans correctif disponible ; écarté.
- **Image distroless ou Chainguard** : surface encore plus réduite, mais plus de shell (scripts d'entrée, health check `curl`) et dépendances natives (DuckDB, psycopg) plus délicates ; écarté pour l'instant.
- **Liste blanche d'IP sur l'API Coolify** : plus sûr, mais incompatible avec les runners GitHub (ADR-0004) ; écarté.
- **Gestionnaire de secrets dédié (Vault, Infisical)** : un service de plus à exploiter sur un VPS partagé, pour une poignée de secrets déjà gérés par Coolify et GitHub ; écarté.
- **Authentification OAuth2 / JWT** : adaptée à des utilisateurs multiples ; une clé d'API suffit pour des appels de service ; reporté au profit de la clé d'API.

## Links

- Related ADRs : [[ADR-0002 - Stockage des artefacts de modele]], [[ADR-0003 - Choix de la plateforme de déploiement]], [[ADR-0004 - Stratégie de déploiement]], [[ADR-0006 - File d'attente]]
- `SECURITY.md` à la racine du dépôt
- External references :
  - [Trivy](https://trivy.dev/)
  - [GitGuardian](https://docs.gitguardian.com/)
  - [skops : sérialisation sûre des modèles scikit-learn](https://skops.readthedocs.io/en/stable/persistence.html)
  - [Protection des branches GitHub](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
