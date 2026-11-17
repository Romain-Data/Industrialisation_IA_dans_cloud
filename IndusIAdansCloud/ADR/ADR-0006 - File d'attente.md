# ADR-0006 : File d'attente des commandes

- Status: Accepted
- Date: 2026-11-17
- Deciders: Romain
- Tags: `architecture`, `messaging`

## Context

`POST /v1/orders` enregistre une commande, puis sa prédiction doit être calculée et stockée pour être relue par `GET /v1/predictions/{order_id}`. Le contrat d'API (`openapi.yml`) prévoit ce découplage : la création répond `202 Accepted` sans attendre la prédiction, et un événement `OrderEvent` (`order.created`, `schema_version`) décrit le message échangé entre le producteur et le consommateur. Le contrat annonce un vrai flux temps réel pour la séance 6, dont le format de transport est libre.

Aujourd'hui, l'application tourne en **une seule instance** (ADR-0003) sur un VPS partagé, avec un volume faible. Ajouter un broker (Redis, RabbitMQ, Kafka) ajouterait un service à exploiter et de la mémoire consommée, alors que le besoin réel de distribution n'existe pas encore.

## Decision

Nous découplons la collecte de la prédiction par une file d'attente derrière une abstraction, implémentée pour l'instant **en mémoire, dans le processus de l'API**, avec un worker en thread.

- **Abstraction** : `OrderQueue` (`publish(event)`, `consume(timeout)`) dans `src/abstraction/`. Le code de l'API et du worker ne connaît que cette interface.
- **Implémentation** : `InMemoryOrderQueue` (`queue.Queue` de Python), créée au démarrage de l'API (`lifespan`).
- **Producteur** : `POST /v1/orders` **enregistre d'abord la commande en base**, puis publie un `OrderEvent` (`event_id` UUID, `order.created`, `occurred_at`, la commande, `schema_version: 1`) et répond `202`.
- **Consommateur** : `OrderWorker`, un thread démon démarré avec l'API et arrêté proprement à son extinction. Il consomme les événements un par un, calcule la prédiction avec le modèle `champion` chargé et l'enregistre (`save_prediction`, qui remplace une prédiction existante).
- **Erreurs** : si le modèle n'est pas chargé ou si la commande est invalide, l'événement est journalisé et abandonné ; une exception inattendue est journalisée sans arrêter le worker.
- **Supervision** : `/health/ready` vérifie que le thread du worker est vivant (`worker: running`).

### Justification

- **Découplage dès maintenant** : le contrat impose déjà le `202` et l'événement ; écrire le producteur et le consommateur séparément rend le passage à un vrai broker local à l'implémentation de `OrderQueue`.
- **En mémoire pour une instance unique** : aucun service supplémentaire, latence négligeable, et suffisant tant que l'API ne tourne qu'en un exemplaire.
- **Commande en base avant l'événement** : la base reste la source de vérité (ADR-0001). Si l'événement est perdu, la commande, elle, ne l'est pas.
- **Contrat d'événement versionné** : `schema_version` permet de faire évoluer le message sans casser un consommateur, ce qui servira avec un broker partagé.

## Consequences

**Positives**
- `POST /v1/orders` répond vite, indépendamment du temps de prédiction.
- Aucun service d'infrastructure en plus sur le VPS.
- Le remplacement par un broker ne touche ni l'API ni le worker, seulement l'implémentation de `OrderQueue`.

**Négatives**
- **Les événements non traités sont perdus au redémarrage** (déploiement, crash, redémarrage après entraînement). La commande reste en base, mais sa prédiction n'est jamais calculée, et rien ne la rattrape aujourd'hui.
- Un événement reçu quand le modèle n'est pas chargé est abandonné, sans nouvelle tentative.
- File et worker sont liés au processus de l'API : impossible de passer à plusieurs instances, ou de séparer le worker, sans changer d'implémentation.
- Pas de file des messages en échec (*dead letter queue*) : une commande invalide n'est visible que dans les logs.

**Neutres**
- Le traitement est séquentiel (un seul worker) : suffisant au volume actuel, à revoir si la latence de prédiction devient un goulot.
- Les tests utilisent la même file en mémoire, ce qui les rend rapides et déterministes.

**Mesures d'atténuation**
- Rattrapage au démarrage, à faire : republier les commandes enregistrées qui n'ont pas de prédiction (la base permet de les retrouver).
- `/health/ready` signale un worker arrêté, et Coolify ne met pas en service une version dont le worker ne démarre pas.
- Choix du broker à la séance 6, dans un nouvel ADR qui remplacera celui-ci.

## Alternatives considered

- **Prédiction synchrone dans `POST /v1/orders`** : plus simple, mais contraire au contrat (`202`) et couple la latence de la collecte à celle du modèle ; écarté. Une prédiction synchrone reste disponible par `POST /v1/predictions`.
- **`BackgroundTasks` de FastAPI** : même perte au redémarrage, sans abstraction ni contrat d'événement réutilisable avec un broker ; écarté.
- **PostgreSQL comme file (`SELECT … FOR UPDATE SKIP LOCKED`, `LISTEN/NOTIFY`)** : durable, sans service supplémentaire puisque PostgreSQL est déjà là ; bonne candidate pour le rattrapage, mais plus de code et de requêtes à maintenir ; reporté.
- **Redis (listes ou streams) / RQ** : léger et durable, mais un service de plus sur le VPS ; à évaluer à la séance 6.
- **RabbitMQ / Celery** : robuste (acquittements, *dead letter*), mais lourd à exploiter pour ce volume ; écarté pour l'instant.
- **Kafka / Redpanda** : adapté au flux temps réel et à la relecture des événements, mais très gourmand pour un VPS partagé ; à évaluer à la séance 6.

## Links

- Related ADRs : [[ADR-0001 - Stockage des commandes]], [[ADR-0003 - Choix de la plateforme de déploiement]], [[ADR-0005 - Sécurisation des entrées, sorties et accès à la donnée]]
- Contrat : `openapi.yml` (`OrderEvent`, `POST /v1/orders`)
- Code : `src/abstraction/order_queue.py`, `src/infrastructure/dev/order_queue.py`, `src/serving/worker.py`
