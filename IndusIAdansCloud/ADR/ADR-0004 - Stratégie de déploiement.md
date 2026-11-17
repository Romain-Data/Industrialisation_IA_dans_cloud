# ADR-0004 : Stratégie de déploiement

- Status: Accepted
- Date: 2026-10-09
- Deciders: Romain
- Tags: `infra`, `ci-cd`

## Context

L'ADR-0003 fixe la plateforme d'exécution (Coolify sur le VPS, image Docker unique `linux/amd64`) mais laisse ouvert le déclenchement des déploiements : à chaque push, sur tag, manuel ou par CI. Il laisse aussi en suspens le rechargement du modèle `champion` après un entraînement (ADR-0002).

Le dépôt ne contient pas encore de `Dockerfile` ni de pipeline CI. Le développement se fait sur Mac arm64 alors que la production est en amd64, et le VPS est partagé avec d'autres projets : un déploiement ne doit ni casser la production sans garde-fou, ni consommer des ressources inutilement. Les applications déjà présentes dans Coolify (RAG Ynov) fonctionnent avec une paire preprod / prod ; on garde la même logique.

Le schéma de base évolue avec Alembic (`migrations/`), et le modèle servi évolue indépendamment du code, par déplacement de l'alias `champion`.

## Decision

Nous déployons par une CI GitHub Actions qui déclenche Coolify uniquement quand les contrôles passent, avec deux environnements.

- **Environnements** : une application Coolify **preprod** et une application **prod**, chacune avec sa propre base PostgreSQL, son volume d'artefacts et ses variables d'environnement. Un push sur `main` déploie en preprod ; un tag `vX.Y.Z` déploie en prod.
- **Pipeline CI** : à chaque push et pull request, lint (`ruff`) et tests (`pytest`). Sur `main` et sur tag, si tout est vert, la CI construit l'image `linux/amd64`, la publie dans un registre (GitHub Container Registry) avec deux tags, le SHA du commit et, pour un tag, la version, puis appelle le webhook de déploiement Coolify de l'environnement concerné.
- **Auto-deploy Coolify désactivé** : Coolify ne déploie jamais de lui-même sur push ; seule la CI le déclenche. Coolify tire l'image publiée par tag, sans la reconstruire.
- **Vérification** : un déploiement est considéré réussi quand `/health/ready` répond après le démarrage ; sinon Coolify garde l'ancienne version en service.
- **Migrations de base** : exécutées par une commande Alembic (`alembic upgrade head`) avant le démarrage de la nouvelle version, avec des migrations rétrocompatibles d'une version à la suivante.
- **Rechargement du modèle** : à la fin d'une tâche d'entraînement, si l'alias `champion` a changé, la tâche redémarre l'API de l'environnement concerné pour qu'elle charge le nouveau modèle. Il n'y a pas de rechargement à chaud.
- **Rollback du code** : on redéploie le tag d'image précédent depuis Coolify. Le rollback du modèle reste le déplacement manuel de l'alias `champion` (ADR-0002) et ne nécessite pas de redéploiement.
- **Secrets** : les secrets de déploiement (webhook et jeton Coolify, accès au registre) sont des secrets GitHub Actions ; les secrets d'exécution restent dans Coolify (ADR-0003).

### Justification

- **CI avant déploiement** : un déploiement automatique sur push sans test enverrait du code cassé en production sur un VPS partagé ; la CI sert de garde-fou.
- **Image construite en CI** : le build amd64 ne dépend plus du Mac ni de la mémoire du VPS, et l'image testée est exactement celle déployée. C'est la mitigation prévue dans l'ADR-0003 contre l'écart arm64 / amd64.
- **Preprod puis prod sur tag** : permet de valider une version sur un environnement réel avant de la promouvoir, au prix d'une application de plus sur le VPS. La promotion par tag laisse une trace claire de ce qui est en production.
- **Images taguées par SHA et par version** : rendent le rollback du code immédiat, sans reconstruction.
- **Redémarrage plutôt que rechargement à chaud** : l'API charge déjà le champion au démarrage ; redémarrer ne demande aucun code supplémentaire, et le coût (courte indisponibilité, une seule instance) est déjà accepté dans l'ADR-0003.
- **Webhook Coolify** : garde la CI indépendante des détails internes de Coolify, qui reste remplaçable.

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

**Neutres**
- Les deux environnements ne se partagent ni base ni artefacts : le champion de la preprod est indépendant de celui de la prod.
- La CI peut évoluer (tests d'intégration, scan de l'image) sans changer cette décision.
- Le plan de sécurisation des secrets et des accès est traité dans l'ADR-0005.

**Mesures d'atténuation**
- Écrire des migrations additives et rétrocompatibles (ajout avant suppression, en deux déploiements) ; sauvegarder la base avant une migration en prod.
- Définir les limites de mémoire de la preprod plus basses que celles de la prod, et l'arrêter quand elle n'est pas utilisée si le VPS est sous tension.
- Limiter les droits du jeton Coolify utilisé par la CI et par la tâche d'entraînement, et le stocker uniquement comme secret.
- Vérifier le démarrage de l'image en CI (lancement du conteneur et appel de `/health/ready`) avant publication.
- Conserver les dernières versions d'image dans le registre pour garder les rollbacks possibles.

## Alternatives considered

- **Auto-deploy Coolify sur push** : le plus simple, mais déploie sans garde-fou de tests ; écarté.
- **Déploiement manuel uniquement** : aucun risque de déploiement involontaire, mais sujet aux oublis et peu reproductible ; écarté.
- **Build de l'image par Coolify depuis le dépôt** : évite le registre, mais consomme CPU et mémoire du VPS partagé pendant le build et ne garantit pas que l'image déployée est celle testée ; écarté.
- **Production seule, sans preprod** : plus léger pour le VPS, mais chaque déploiement est testé directement en production ; écarté.
- **Déploiement continu en production à chaque push sur `main`** : plus rapide, mais retire la validation en preprod et la trace des versions ; écarté.
- **Rechargement à chaud du modèle (endpoint ou lecture périodique de l'alias)** : évite l'interruption, mais ajoute du code et un état à tester pour une seule instance ; reporté.
- **Rollback par `git revert` et nouveau déploiement** : plus lent que redéployer une image existante ; écarté pour le cas courant.

## Links

- Related ADRs : [[ADR-0002 - Stockage des artefacts de modele]], [[ADR-0003 - Choix de la plateforme de déploiement]], [[ADR-0005 - Sécurisation]]
- External references :
  - [Coolify : déploiement par webhook](https://coolify.io/docs)
  - [GitHub Actions](https://docs.github.com/actions)
  - [GitHub Container Registry](https://docs.github.com/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
