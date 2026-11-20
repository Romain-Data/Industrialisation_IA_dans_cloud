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
- le projet sert à la formation : on accepte que le logisticien **active lui-même le flux des commandes de l'ERP** en prenant son poste, ce qui simplifie le cas métier réel.

## Decision

Nous remplaçons la file en mémoire par **RabbitMQ**, et nous diffusons les prédictions vers le navigateur du logisticien en **Server-Sent Events (SSE)**.

### Messagerie (RabbitMQ)

- **File `orders`** (durable, messages persistants) : `POST /v1/orders` enregistre la commande, puis publie l'`OrderEvent` dans cette file. Le worker la consomme et calcule la prédiction. C'est la nouvelle implémentation `RabbitMQOrderQueue` du contrat `OrderQueue` ; l'API et le worker ne changent pas.
- **Échange `predictions`** (*fanout*) : après chaque prédiction enregistrée, le worker publie un **`PredictionEvent`** (`prediction.created`, la prédiction, `schema_version`). Il passe par le nouveau contrat `PredictionEvents` (`publish`, `listen`).
- **Diffusion** : chaque instance de l'API écoute l'échange par une file exclusive, supprimée à la déconnexion. Elle relaie les événements aux navigateurs connectés.
- **Sans `RABBITMQ_URL`** (développement, tests) : les implémentations en mémoire sont utilisées, avec le même comportement dans un seul processus.

### Interface du logisticien

- **`GET /v1/events/predictions`** : flux SSE (`text/event-stream`). Chaque événement `prediction.created` contient la prédiction. Un commentaire *keep-alive* part toutes les 15 s, pour que le proxy ne coupe pas la connexion.
- **`GET /v1/predictions?limit=N`** : les dernières prédictions (historique, consultation).
- **`GET /logisticien`** : une page HTML servie par l'API, en JavaScript natif (`EventSource`), sans framework.

### Poste du logisticien et flux ERP

Le logisticien **prend son poste en activant le flux**. Il est notifié de chaque nouvelle commande express et la traite au fil de l'eau ; il peut afficher aussi les commandes standard.

- **`PUT /v1/erp-stream`** (`active: true` ou `false`) et **`GET /v1/erp-stream`** (état, date d'activation, dernière commande lue, commandes reçues). À l'activation, un **connecteur** (`ErpStream`) lit le MongoDB de l'ERP toutes les 2 s (`ERP_STREAM_POLL_SECONDS`), en commençant **après la dernière commande existante** : ni l'historique ni le stock accumulé ne sont relus.
- Chaque nouvelle commande est nettoyée et validée **comme par l'import horaire** (`validated_row`), enregistrée avec sa cible, puis publiée dans la file `orders`. Elle suit ensuite le parcours d'une commande reçue : worker, prédiction, échange `predictions`, page. L'import horaire suivant la trouve « déjà présente » : pas de doublon, et la cible sert à l'entraînement.
- Flux coupé : rien n'est lu en temps réel. Les commandes de l'ERP arrivent à l'import horaire, sans notification. Si l'ERP ne répond pas, l'activation est refusée (503) et la page l'indique (c'est le cas en préprod, qui n'a pas d'ERP).
- **Page** : interrupteur « Prendre mon poste » ; compteurs **depuis l'activation** (commandes reçues, éligibles express, express à traiter) ; liste des **nouvelles commandes express seulement**, chacune avec une notification (bannière, et notification du navigateur si autorisée) et un bouton **« Traitée »** ; case « Afficher aussi les commandes standard » ; bouton **« Vider la liste »**. Le traitement est **local à la page** (non enregistré), ce qui suffit au cadre pédagogique.
- L'ERP simulé produit 5 commandes toutes les 5 s (`INTERVAL_SECONDS=5`) quand il tourne.

### Exploitation

- RabbitMQ 4 (image `rabbitmq:4-alpine`, sans plugin de gestion), **un par environnement**. Il est joignable uniquement sur le réseau interne de Coolify, sans port publié. Son utilisateur et son mot de passe sont générés et stockés dans Coolify, et la mémoire est limitée à 256 Mo. Un volume conserve les messages durables, et le nom de nœud est fixe (`RABBITMQ_NODENAME`) pour que les données survivent aux redéploiements.
- **`/health/ready`** vérifie aussi le broker (`queue: reachable`). Une version qui ne joint pas RabbitMQ n'est pas mise en service.
- `scripts/coolify_power.py` éteint et rallume RabbitMQ avec le reste.

### Justification

- **RabbitMQ plutôt qu'une file en mémoire** : les commandes en attente survivent à un redémarrage de l'API. Le worker pourra être séparé de l'API, voire multiplié. La diffusion *fanout* sert la même prédiction à plusieurs consommateurs (navigateurs, et demain la supervision).
- **RabbitMQ plutôt que Kafka ou Redpanda** : quelques centaines de Mo au lieu d'un ou deux Go, pour un volume de quelques commandes par minute. La relecture d'historique de Kafka n'est pas nécessaire : l'historique est en base.
- **RabbitMQ plutôt que Redis** : files durables, *exchanges* et routage natifs, et c'est l'outil du cours.
- **SSE plutôt que WebSocket** : le flux ne va que du serveur vers le navigateur. SSE est du HTTP simple, reconnecté automatiquement par `EventSource`, et passe par le proxy de Coolify sans configuration (la compression gzip est déjà désactivée pour `text/event-stream`).
- **Connecteur ERP piloté par le logisticien** : les commandes viennent du vrai ERP (simulé) et passent par le même chemin qu'une commande reçue, ce qui prouve le fonctionnement réel. L'activation au poste évite de notifier un écran vide ou de relire l'historique.
- **Même préparation que l'ETL** : une seule règle de nettoyage et de validation, et des données d'entraînement identiques, que la commande arrive par le flux ou par l'import horaire.
- **Page servie par l'API** : un seul déploiement et une seule origine (pas de CORS). Le besoin est un écran de suivi, pas une application.

## Consequences

**Positives**
- Les commandes en file ne sont plus perdues quand l'API redémarre.
- Le logisticien voit chaque prédiction en moins d'une seconde, avec une notification pour les commandes express.
- La démonstration de bout en bout se fait en activant le flux, avec les vraies commandes de l'ERP simulé.
- Les implémentations en mémoire gardent les tests rapides. Les implémentations RabbitMQ sont testées en CI contre un vrai broker.

**Négatives**
- Un service de plus à exploiter par environnement (environ 256 Mo chacun).
- Le message est acquitté à la réception : si l'API s'arrête **pendant** le calcul d'une prédiction, ce message est perdu. La commande reste en base (ADR-0006), et le rattrapage des commandes sans prédiction reste à faire.
- Flux coupé, les commandes de l'ERP n'arrivent qu'à l'import horaire, sans prédiction en temps réel ni notification.
- Le flux n'existe qu'en prod : la préprod n'a pas d'ERP.
- L'ERP simulé produit en continu tant qu'il tourne (5 commandes toutes les 5 s, environ 3 600 par heure), même flux coupé : il faut l'éteindre entre deux sessions (`scripts/coolify_power.py`).
- Le flux SSE et la page sont **publics**, sans authentification. Ils n'exposent que des prédictions, sans donnée personnelle (ADR-0012), mais n'importe qui peut les voir.
- N'importe qui peut activer ou couper le flux (pas d'authentification) ; acceptable pour la formation. L'état « traitée » d'une commande est perdu au rechargement de la page.

**Neutres**
- Le contrat d'API passe en version 2.1.0, avec des ajouts compatibles : `GET /v1/predictions`, `GET /v1/events/predictions`, `GET` et `PUT /v1/erp-stream`, et le schéma `PredictionEvent`.
- Le format de transport reste JSON. `schema_version` permet de faire évoluer les deux événements.

**Mesures d'atténuation**
- Éteindre l'ERP simulé et le reste du projet entre deux sessions (`scripts/coolify_power.py off all`).
- Hors formation : réserver l'activation du flux à un rôle authentifié, et enregistrer le traitement des commandes en base.
- Rattrapage au démarrage (republier les commandes sans prédiction) et file des messages en échec (*dead letter*) : à faire.

## Alternatives considered

- **Garder la file en mémoire** : rien à exploiter, mais elle perd les commandes et ne répond pas à la séance 6 ; écarté.
- **Kafka ou Redpanda** : relecture des événements et très haut débit, mais trop gourmand pour le VPS ; écarté.
- **Redis (listes ou streams)** : léger, mais moins adapté au routage et aux acquittements ; écarté.
- **WebSocket** : bidirectionnel, inutile ici, et plus complexe à faire passer par le proxy ; écarté.
- **Interrogation périodique (*polling*) de `GET /v1/predictions`** : simple, mais avec une latence et une charge inutiles ; écarté (la route sert seulement à l'historique initial).
- **Front-end séparé (React, Streamlit)** : plus riche, mais un service et une origine de plus ; écarté.
- **Piloter le simulateur ERP (démarrer ou arrêter son conteneur) depuis l'interface** : demanderait d'accéder à Docker ou à l'API Coolify depuis l'application (refusé dans l'ADR-0009) ; écarté. L'interrupteur pilote le connecteur, pas la production de l'ERP.
- **Bouton générant des commandes fictives** (première version de cet ADR) : démontrable sans ERP, mais hors cas métier ; remplacé par le flux de l'ERP.
- **Enregistrer en base le traitement des commandes express** : utile en conditions réelles (plusieurs postes, reprise), inutile pour la démonstration ; reporté.

## Links

- Supersedes : [[ADR-0006 - File d'attente]] (implémentation en mémoire, gardée pour le développement et les tests)
- Related ADRs : [[ADR-0003 - Choix de la plateforme de déploiement]], [[ADR-0005 - Sécurisation des entrées, sorties et accès à la donnée]], [[ADR-0007 - PostgreSQL, MongoDB ou autre]], [[ADR-0011 - Estimation budgétaire]], [[ADR-0012 - Conformité RGPD]]
- Contrat : `openapi.yml` (`OrderEvent`, `PredictionEvent`)
- External references :
  - [RabbitMQ : tutoriels](https://www.rabbitmq.com/tutorials)
  - [MDN : Server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
