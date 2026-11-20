# ADR-0013 : RabbitMQ et interface temps réel du logisticien

- Status: Accepted
- Date: 2026-11-20
- Deciders: Romain
- Tags: `architecture`, `messaging`, `temps réel`

## Context

L'ADR-0006 a découplé la collecte des commandes de leur prédiction par une file **en mémoire** (`InMemoryOrderQueue`, derrière le contrat `OrderQueue`). Elle notait deux limites : les événements non traités sont perdus à chaque redémarrage de l'API, et la file est liée au processus de l'API. Elle renvoyait le choix d'un vrai broker à la séance 6 (flux temps réel).

Le barème ajoute un bonus : une **interface de streaming pour un logisticien**. Une commande arrive, et il veut être **notifié si elle est éligible à la livraison express**.

Contraintes :
- une seule instance de l'API (ADR-0003) ;
- un VPS partagé, où la mémoire compte (ADR-0011) ;
- le contrat `OrderEvent` existe déjà (`openapi.yml`) ;
- le projet sert à la formation. Pour démontrer le flux sans attendre l'ERP, on accepte un bouton qui **génère des commandes**, ce qui sort du cas métier.

## Decision

Nous remplaçons la file en mémoire par **RabbitMQ**, et nous diffusons les prédictions vers le navigateur du logisticien en **Server-Sent Events (SSE)**.

### Messagerie (RabbitMQ)

- **File `orders`** (durable, messages persistants) : `POST /v1/orders` enregistre la commande, puis publie l'`OrderEvent` dans cette file. Le worker la consomme et calcule la prédiction. C'est la nouvelle implémentation `RabbitMQOrderQueue` du contrat `OrderQueue` ; l'API et le worker ne changent pas.
- **Échange `predictions`** (*fanout*) : après chaque prédiction enregistrée, le worker publie un **`PredictionEvent`** (`prediction.created`, la prédiction, `schema_version`). Il passe par le nouveau contrat `PredictionEvents` (`publish`, `listen`).
- **Diffusion** : chaque instance de l'API écoute l'échange par une file exclusive, supprimée à la déconnexion. Elle relaie les événements aux navigateurs connectés.
- **Sans `RABBITMQ_URL`** (développement, tests) : les implémentations en mémoire sont utilisées, avec le même comportement dans un seul processus.

### Interface du logisticien

- **`GET /v1/events/predictions`** : flux SSE (`text/event-stream`). Chaque événement `prediction.created` contient la prédiction. Un commentaire *keep-alive* part toutes les 15 s, pour que le proxy ne coupe pas la connexion.
- **`GET /v1/predictions?limit=N`** : les dernières prédictions, pour afficher l'historique à l'ouverture de la page.
- **`GET /logisticien`** : une page HTML servie par l'API, en JavaScript natif (`EventSource`), sans framework. Elle affiche les prédictions en direct, met en évidence les commandes **express** et envoie une **notification** (bannière dans la page, et notification du navigateur si le logisticien l'autorise).

### Bouton de démonstration

- **`POST /v1/demo/orders`** (`count` de 1 à 20) : génère des commandes réalistes au vocabulaire de l'ERP. Elles suivent **exactement le parcours d'une vraie commande** : enregistrement, file `orders`, worker, échange `predictions`, page du logisticien.
- Activé par **`DEMO_MODE=true`**, en préprod **et en prod** (projet de formation). Sans cette variable, la route répond 404.
- Garde-fous : 20 commandes au plus par appel, et **un appel toutes les 5 s au plus** (sinon 429). Les commandes générées sont identifiables par leur préfixe `DEMO-`.

### Exploitation

- RabbitMQ 4 (image `rabbitmq:4-alpine`, sans plugin de gestion), **un par environnement**. Il est joignable uniquement sur le réseau interne de Coolify, sans port publié. Son utilisateur et son mot de passe sont générés et stockés dans Coolify, et la mémoire est limitée à 256 Mo. Un volume conserve les messages durables, et le nom de nœud est fixe (`RABBITMQ_NODENAME`) pour que les données survivent aux redéploiements.
- **`/health/ready`** vérifie aussi le broker (`queue: reachable`). Une version qui ne joint pas RabbitMQ n'est pas mise en service.
- `scripts/coolify_power.py` éteint et rallume RabbitMQ avec le reste.

### Justification

- **RabbitMQ plutôt qu'une file en mémoire** : les commandes en attente survivent à un redémarrage de l'API. Le worker pourra être séparé de l'API, voire multiplié. La diffusion *fanout* sert la même prédiction à plusieurs consommateurs (navigateurs, et demain la supervision).
- **RabbitMQ plutôt que Kafka ou Redpanda** : quelques centaines de Mo au lieu d'un ou deux Go, pour un volume de quelques commandes par minute. La relecture d'historique de Kafka n'est pas nécessaire : l'historique est en base.
- **RabbitMQ plutôt que Redis** : files durables, *exchanges* et routage natifs, et c'est l'outil du cours.
- **SSE plutôt que WebSocket** : le flux ne va que du serveur vers le navigateur. SSE est du HTTP simple, reconnecté automatiquement par `EventSource`, et passe par le proxy de Coolify sans configuration (la compression gzip est déjà désactivée pour `text/event-stream`).
- **Bouton de démonstration** : il rend le flux démontrable à la demande, en soutenance, sans dépendre du rythme de l'ERP. Il passe par le même chemin qu'une vraie commande, donc il prouve le vrai fonctionnement.
- **Page servie par l'API** : un seul déploiement et une seule origine (pas de CORS). Le besoin est un écran de suivi, pas une application.

## Consequences

**Positives**
- Les commandes en file ne sont plus perdues quand l'API redémarre.
- Le logisticien voit chaque prédiction en moins d'une seconde, avec une notification pour les commandes express.
- La démonstration de bout en bout se fait d'un clic, en préprod comme en prod.
- Les implémentations en mémoire gardent les tests rapides. Les implémentations RabbitMQ sont testées en CI contre un vrai broker.

**Négatives**
- Un service de plus à exploiter par environnement (environ 256 Mo chacun).
- Le message est acquitté à la réception : si l'API s'arrête **pendant** le calcul d'une prédiction, ce message est perdu. La commande reste en base (ADR-0006), et le rattrapage des commandes sans prédiction reste à faire.
- Les commandes importées de l'ERP par l'ETL horaire (ADR-0007) arrivent déjà étiquetées et ne passent pas par la file : elles n'apparaissent pas sur la page du logisticien.
- Le flux SSE et la page sont **publics**, sans authentification. Ils n'exposent que des prédictions, sans donnée personnelle (ADR-0012), mais n'importe qui peut les voir.
- En prod, n'importe qui peut générer des commandes de démonstration, dans la limite du garde-fou. Elles se mêlent aux vraies données, identifiables par le préfixe `DEMO-`.

**Neutres**
- Le contrat d'API passe en version 2.1.0, avec des ajouts compatibles : `GET /v1/predictions`, `GET /v1/events/predictions`, `POST /v1/demo/orders` et le schéma `PredictionEvent`.
- Le format de transport reste JSON. `schema_version` permet de faire évoluer les deux événements.

**Mesures d'atténuation**
- Les commandes de démonstration (`DEMO-`) sont exclues de l'entraînement : elles n'ont pas de résultat réel, donc ne sont pas étiquetées.
- Limiter le débit du bouton, et le désactiver (`DEMO_MODE=false`) si l'application sortait du cadre de la formation.
- Rattrapage au démarrage (republier les commandes sans prédiction) et file des messages en échec (*dead letter*) : à faire.

## Alternatives considered

- **Garder la file en mémoire** : rien à exploiter, mais elle perd les commandes et ne répond pas à la séance 6 ; écarté.
- **Kafka ou Redpanda** : relecture des événements et très haut débit, mais trop gourmand pour le VPS ; écarté.
- **Redis (listes ou streams)** : léger, mais moins adapté au routage et aux acquittements ; écarté.
- **WebSocket** : bidirectionnel, inutile ici, et plus complexe à faire passer par le proxy ; écarté.
- **Interrogation périodique (*polling*) de `GET /v1/predictions`** : simple, mais avec une latence et une charge inutiles ; écarté (la route sert seulement à l'historique initial).
- **Front-end séparé (React, Streamlit)** : plus riche, mais un service et une origine de plus ; écarté.
- **Piloter le simulateur ERP depuis l'interface** : demanderait d'accéder à Docker ou à l'API Coolify depuis l'application (refusé dans l'ADR-0009), et ses commandes n'arrivent qu'à l'import horaire ; écarté au profit du bouton de démonstration.

## Links

- Supersedes : [[ADR-0006 - File d'attente]] (implémentation en mémoire, gardée pour le développement et les tests)
- Related ADRs : [[ADR-0003 - Choix de la plateforme de déploiement]], [[ADR-0005 - Sécurisation des entrées, sorties et accès à la donnée]], [[ADR-0007 - PostgreSQL, MongoDB ou autre]], [[ADR-0011 - Estimation budgétaire]], [[ADR-0012 - Conformité RGPD]]
- Contrat : `openapi.yml` (`OrderEvent`, `PredictionEvent`)
- External references :
  - [RabbitMQ : tutoriels](https://www.rabbitmq.com/tutorials)
  - [MDN : Server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
