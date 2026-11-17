# ADR-0004 : Stratégie de déploiement

- Status: Accepted
- Date: 2026-10-09 (mise à jour le 2026-11-17 après la mise en œuvre)
- Deciders: Romain
- Tags: `infra`, `ci-cd`

## Context

L'ADR-0003 fixe la plateforme d'exécution (Coolify sur le VPS, image Docker unique `linux/amd64`) mais laisse ouvert le déclenchement des déploiements : à chaque push, sur tag, manuel ou par CI. Il laisse aussi en suspens le rechargement du modèle `champion` après un entraînement (ADR-0002).

Le dépôt ne contient pas encore de `Dockerfile` ni de pipeline CI. Le développement se fait sur Mac arm64 alors que la production est en amd64, et le VPS est partagé avec d'autres projets : un déploiement ne doit ni casser la production sans garde-fou, ni consommer des ressources inutilement. Les applications déjà présentes dans Coolify (RAG Ynov) fonctionnent avec une paire preprod / prod ; on garde la même logique.

Le schéma de base évolue avec Alembic (`migrations/`), et le modèle servi évolue indépendamment du code, par déplacement de l'alias `champion`.

## Decision

Nous déployons par une CI GitHub Actions qui déclenche Coolify uniquement quand les contrôles passent, avec deux environnements.

- **Environnements** : une application Coolify **preprod** et une application **prod**, chacune avec sa propre base PostgreSQL, ses volumes et ses variables d'environnement. Une fusion sur `develop` déploie en preprod ; une fusion de `develop` dans `main`, autorisée seulement si la preprod est vérifiée, déploie en prod (mise à jour du 2026-11-17, voir plus bas).
- **Pipeline CI/CD** : à chaque push et pull request, lint (`ruff`), qualité (`pylint`, score minimal) et tests (`pytest`, avec un MongoDB réel). Sur `develop`, les images `linux/amd64` de l'API et de l'orchestrateur sont **construites une seule fois**, testées au démarrage, scannées par Trivy (échec sur toute vulnérabilité critique corrigeable) et publiées sur GHCR avec le tag `sha-<commit>` ; puis la preprod est déployée et vérifiée. Sur `main`, ces **mêmes images** sont promues (tag `X.Y.Z`, même empreinte) et déployées en prod.
- **Auto-deploy Coolify désactivé** : Coolify ne déploie jamais de lui-même sur push ; seule la CI le déclenche. Coolify tire l'image publiée par tag, sans la reconstruire.
- **Vérification** : la CI attend la fin de chaque déploiement Coolify (qui n'aboutit que si `/health/ready` répond, sinon l'ancienne version reste en service), puis lance des tests de fumée : parcours complet en preprod (santé, model card, prédiction, commande traitée par le worker), lecture seule en prod. Le succès en preprod pose le statut **« Préprod vérifiée »** sur le commit, **obligatoire** pour fusionner dans `main`.
- **Premier déploiement d'un environnement** : tant qu'aucun modèle `champion` n'existe, `/health/ready` répond 503 et Coolify refuserait la nouvelle version. Le premier déploiement se fait donc avec le health check sur `/health`, puis on lance un entraînement, on passe le health check sur `/health/ready` et on redéploie.
- **Migrations de base** : exécutées par une commande Alembic (`alembic upgrade head`) avant le démarrage de la nouvelle version, avec des migrations rétrocompatibles d'une version à la suivante.
- **Rechargement du modèle** : ~~à la fin d'une tâche d'entraînement, si l'alias `champion` a changé, la tâche redémarre l'API de l'environnement concerné~~. **Remplacé par l'ADR-0009 (2026-11-17)** : l'API lit la version du champion chaque minute et recharge le modèle quand elle change, sans redémarrage.
- **Rollback du code** : on redéploie le tag d'image précédent depuis Coolify. Le rollback du modèle reste le déplacement manuel de l'alias `champion` (ADR-0002) et ne nécessite pas de redéploiement.
- **Secrets** : les secrets de déploiement (URL et jeton de l'API Coolify) sont des secrets GitHub Actions ; les secrets d'exécution restent dans Coolify (ADR-0003). Le jeton est limité au projet Coolify de cette application, avec les seuls droits nécessaires au déploiement (`write` pour fixer le tag d'image, `deploy`).
- **Accès à l'API Coolify** : l'API accepte les appels de toutes les IP, car les runners GitHub n'ont pas d'adresse fixe. La protection repose sur le jeton.

### Justification

- **CI avant déploiement** : un déploiement automatique sur push sans test enverrait du code cassé en production sur un VPS partagé ; la CI sert de garde-fou.
- **Image construite en CI** : le build amd64 ne dépend plus du Mac ni de la mémoire du VPS, et l'image testée est exactement celle déployée. C'est la mitigation prévue dans l'ADR-0003 contre l'écart arm64 / amd64.
- **Preprod puis prod sur release (GitFlow)** : `develop` porte le travail intégré et validé en preprod, `main` ne contient que des versions publiées. permet de valider une version sur un environnement réel avant de la promouvoir, au prix d'une application de plus sur le VPS. La promotion par tag laisse une trace claire de ce qui est en production.
- **Images taguées par SHA et par version** : rendent le rollback du code immédiat, sans reconstruction.
- **Redémarrage plutôt que rechargement à chaud** : l'API charge déjà le champion au démarrage ; redémarrer ne demande aucun code supplémentaire, et le coût (courte indisponibilité, une seule instance) est déjà accepté dans l'ADR-0003.
- **API Coolify plutôt que simple webhook** : le webhook redéploie le tag déjà configuré, sans dire quelle image prendre. Fixer le tag SHA avant de déployer garantit que l'image déployée est celle que la CI vient de tester, et garde le registre comme seule source des images. La CI reste limitée à deux appels HTTP, faciles à remplacer si la plateforme change.
- **Premier déploiement en deux temps** : garder `/health/ready` comme critère de réussite (modèle chargé, base joignable, schéma à jour) plutôt que l'affaiblir en `/health` pour tous les déploiements ; le cas « pas encore de modèle » n'arrive qu'une fois par environnement.
- **API ouverte à toutes les IP** : les plages d'adresses de GitHub Actions sont larges et changeantes ; les maintenir dans une liste blanche est fragile. Un runner auto-hébergé sur le VPS éviterait d'ouvrir l'API, mais consommerait des ressources sur une machine partagée.

### Mise à jour du 2026-11-17 : construire une fois, vérifier, promouvoir

La première version déployait la prod à la publication d'une GitHub Release, avec une image **reconstruite** à partir du tag, et la CI ne vérifiait rien après les déploiements. Nouveau parcours, demandé par Romain :

1. développement sur une branche, tests à chaque push ; fusion dans `develop` si les tests passent ;
2. construction des images de preprod, déploiement, **tests de fumée** sur l'URL de preprod ;
3. si la preprod est vérifiée, fusion de `develop` dans `main` (PR relue et fusionnée par Romain) ;
4. **promotion** des images testées en prod (pas de reconstruction), tag et release automatiques, déploiement, **check de santé** de la prod.

- **Pourquoi promouvoir plutôt que reconstruire** : une image reconstruite n'est pas celle qui a été testée (correctifs Debian appliqués au build, couches de base qui évoluent) ; retaguer la même empreinte garantit que la prod exécute exactement ce qui a passé la preprod.
- **Pourquoi un statut de commit obligatoire** : il relie mécaniquement le résultat de la preprod à l'autorisation de fusionner dans `main` ; un oubli humain ne peut pas envoyer en prod une version non vérifiée.
- **Pourquoi plus de branche `release/*` obligatoire** : `develop` vérifié en preprod est déjà la release candidate ; la version publiée est celle de `pyproject.toml`, et la CI refuse une PR vers `main` dont la version existe déjà.
- **Limite** : les tests de fumée de preprod écrivent une commande de test dans la base de preprod à chaque déploiement.

## Consequences

**Positives**
- Aucun déploiement sans lint ni tests verts ; la production n'évolue que par tag.
- Image identique de la CI à la production, construite pour la bonne architecture.
- Rollback du code rapide, par redéploiement d'une image existante.
- Le modèle servi suit l'entraînement sans intervention manuelle.

**Négatives**
- Une pipeline CI, un registre et des secrets à créer et à maintenir (il n'existe aujourd'hui ni `Dockerfile` ni workflow).
- Une application preprod de plus consomme mémoire, disque et une base PostgreSQL sur un VPS partagé.
- Le redémarrage de l'API après entraînement provoque une courte interruption, et l'entraînement doit pouvoir joindre Coolify (jeton d'API) pour la déclencher.
- Le rollback du code ne défait pas les migrations de base : un retour arrière après une migration destructive peut échouer ou perdre des données.
- Dépendance à GitHub Actions et à GitHub Container Registry en plus de Coolify.
- L'API Coolify est joignable depuis Internet : une fuite du jeton permet de modifier et de déployer les applications du projet (mais pas les autres projets du VPS, grâce à la limitation du jeton).
- Le premier déploiement de chaque environnement demande des étapes manuelles (health check, entraînement, redéploiement).
- La CI dépend du format de l'API Coolify (`PATCH /applications/{uuid}`, `POST /deploy`) : une mise à jour de Coolify peut la casser.

**Neutres**
- Les deux environnements ne se partagent ni base ni artefacts : le champion de la preprod est indépendant de celui de la prod.
- La CI peut évoluer (tests d'intégration, scan de l'image) sans changer cette décision.
- Le plan de sécurisation des secrets et des accès est traité dans l'ADR-0005.

**Mesures d'atténuation**
- Écrire des migrations additives et rétrocompatibles (ajout avant suppression, en deux déploiements) ; sauvegarder la base avant une migration en prod.
- Définir les limites de mémoire de la preprod plus basses que celles de la prod, et l'arrêter quand elle n'est pas utilisée si le VPS est sous tension.
- Limiter les droits du jeton Coolify utilisé par la CI et par la tâche d'entraînement au seul projet de l'application, et le stocker uniquement comme secret ; le renouveler régulièrement et en cas de doute.
- Vérifier la version de Coolify et la réponse de l'API (méthode HTTP, champs) avant une mise à jour de Coolify.
- Vérifier le démarrage de l'image en CI (lancement du conteneur et appel de `/health/ready`) avant publication, et la scanner (Trivy).
- Conserver les dernières versions d'image dans le registre pour garder les rollbacks possibles.

## Alternatives considered

- **Auto-deploy Coolify sur push** : le plus simple, mais déploie sans garde-fou de tests ; écarté.
- **Déploiement manuel uniquement** : aucun risque de déploiement involontaire, mais sujet aux oublis et peu reproductible ; écarté.
- **Build de l'image par Coolify depuis le dépôt** : évite le registre, mais consomme CPU et mémoire du VPS partagé pendant le build et ne garantit pas que l'image déployée est celle testée ; écarté.
- **Production seule, sans preprod** : plus léger pour le VPS, mais chaque déploiement est testé directement en production ; écarté.
- **Déploiement continu en production à chaque push sur `main`** : plus rapide, mais retire la validation en preprod et la trace des versions ; écarté.
- **Rechargement à chaud du modèle (endpoint ou lecture périodique de l'alias)** : évite l'interruption, mais ajoute du code et un état à tester pour une seule instance ; reporté.
- **Rollback par `git revert` et nouveau déploiement** : plus lent que redéployer une image existante ; écarté pour le cas courant.
- **Tag d'image mobile (`preprod`, `prod`) et webhook seul** : ne demande pas le droit `write`, mais l'image déployée n'est plus identifiable par son tag dans Coolify et un redéploiement peut prendre une image différente ; écarté.
- **Liste blanche des IP de GitHub Actions** : garderait l'API fermée, mais les plages sont nombreuses et changent ; écarté.
- **Runner GitHub auto-hébergé sur le VPS** : l'API reste fermée à Internet, mais le runner consomme des ressources sur le VPS partagé et devient un composant de plus à maintenir et à sécuriser ; reporté (à reconsidérer dans l'ADR-0005).
- **Health check sur `/health` pour tous les déploiements** : supprime l'étape manuelle du premier déploiement, mais une version qui ne charge pas le modèle ou ne joint pas la base serait mise en service ; écarté.

## Mise en œuvre (2026-11-17)

- **CI** : `.github/workflows/ci.yml`. Jobs `checks` (ruff, pylint, pytest + MongoDB, version libre sur une PR vers `main`), `build` (images api et orchestrator, test de démarrage, Trivy, publication `sha-<commit>`), `deploy-preprod` (`scripts/coolify_deploy.py` attend le résultat, `scripts/smoke_test.py --mode full`, statut « Préprod vérifiée »), `promote` (sur `main` : vérifie le statut du commit testé, retague les images en `X.Y.Z` avec `docker buildx imagetools`, crée tag et release) et `deploy-prod` (déploiement, `smoke_test.py --mode readonly`). Variables par environnement GitHub : `COOLIFY_APP_UUID`, `APP_URL`.
- **Coolify** (4.7.5) : projet « Indus IA dans le Cloud », environnements `preprod` et `production` (correspondant à l'environnement GitHub `prod`). Chacun contient une application « Docker Image » (`express-delivery-preprod` / `express-delivery-prod`, 1 Go, 1 CPU), une base PostgreSQL 17 (256 Mo, 0,5 CPU) et un volume monté sur `/app/mlartifacts`. Domaines : `express-delivery-preprod.romaincollery.com` et `express-delivery.romaincollery.com`.
- **Démarrage du conteneur** (`docker-entrypoint.sh`) : création des bases manquantes (la base `mlflow`, que Coolify ne crée pas), `alembic upgrade head`, puis lancement de l'API. Les migrations sont donc jouées au démarrage de la nouvelle version, avant qu'elle reçoive du trafic.
- **Health check** : exécuté par Coolify avec `curl` dans le conteneur (installé dans l'image), sur `/health/ready`, avec 60 s de délai au démarrage.
- **Entraînement** : tâche planifiée Coolify `train` (`/app/docker-entrypoint.sh train`) sur l'application preprod, désactivée par défaut et activée à la demande.
- **Pas encore fait** :
  - ~~le redémarrage automatique de l'API après un entraînement~~ : rechargement automatique par l'API (ADR-0009) ;
  - le premier déploiement de la prod (première release `v0.1.0`) ;
  - les sauvegardes planifiées des bases et du volume (ADR-0003).

## Links

- Related ADRs : [[ADR-0002 - Stockage des artefacts de modele]], [[ADR-0003 - Choix de la plateforme de déploiement]], [[ADR-0005 - Sécurisation des entrées, sorties et accès à la donnée]], [[ADR-0009 - Orchestration du réentraînement]]
- External references :
  - [Coolify : API](https://coolify.io/docs/api-reference/authorization)
  - [GitHub Actions](https://docs.github.com/actions)
  - [GitHub Container Registry](https://docs.github.com/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
