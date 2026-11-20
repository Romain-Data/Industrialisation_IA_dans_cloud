# ADR-0008 : Cloud, on-premise ou local ?

- Status: Accepted
- Date: 2026-11-20
- Deciders: Romain
- Tags: `infra`, `hébergement`

## Context

Le cours demande de choisir où tourne l'application : en **local**, **on-premise** (sur des serveurs que l'entreprise possède et exploite) ou dans le **cloud**. Le cloud recouvre lui-même plusieurs niveaux :
- **IaaS** : on loue une machine et on l'administre soi-même (un VPS, par exemple) ;
- **PaaS ou serverless** : le fournisseur exécute les conteneurs et gère les bases ;
- **services ML managés** : SageMaker, Vertex AI, Azure ML.

L'ADR-0003 a choisi la **plateforme** (Coolify sur un VPS, image Docker unique). Celui-ci explicite le **modèle d'hébergement** qui la sous-tend et pourquoi les autres ont été écartés.

Contraintes du projet :
- le modèle est léger (régression logistique) et le trafic faible (commandes d'un e-commerçant), avec une seule instance ;
- le budget est quasi nul : un VPS NetCup est déjà payé et partagé avec d'autres projets (ADR-0011) ;
- les données sont pseudonymisées, donc personnelles au sens du RGPD, et doivent rester dans l'UE (ADR-0012) ;
- une seule personne développe et exploite le projet ;
- il faut deux environnements (preprod et prod, ADR-0004) et un développement local sur Mac M1, alors que la prod est en `linux/amd64`.

## Decision

Nous retenons un **cloud IaaS auto-administré**, c'est-à-dire un VPS loué dans l'UE, pour la préprod et la prod. Le **local** sert au développement et aux tests. Ni on-premise, ni cloud managé.

- **Préprod et prod** : VPS NetCup à **Vienne (Autriche)**. 4 vCPU, 8 Go de RAM, 256 Go de disque, `amd64`. Coolify y orchestre des conteneurs Docker (ADR-0003). Le fournisseur gère le matériel, le réseau et le datacenter. Nous gérons le système, Docker, Coolify, les bases et les sauvegardes.
- **Local** :
  - développement et tests sur le Mac (`uv`, SQLite, MongoDB de test) ;
  - pile complète reproductible avec `docker compose` (`docker-compose.test.yml`, `docker-compose.prod.yml`) ;
  - Kubernetes pratiqué en local (`kind`) avec la même image.
- **Portabilité** : rien dans le code ne dépend du VPS ni de Coolify :
  - toute la configuration passe par des variables d'environnement ;
  - les images sont standard (GHCR) ;
  - les données sont dans PostgreSQL, les artefacts dans MLflow et les snapshots en Parquet (DuckLake).

  Changer d'hébergement (cloud managé ou serveur on-premise) revient à fournir ces services et à redéployer les mêmes images.

### Justification

- **IaaS plutôt que cloud managé** : pour une instance et un trafic faible, un cloud managé coûterait environ 90 à 120 € par mois. La quote-part du VPS revient à quelques euros (ADR-0011). Ses atouts (montée en charge automatique, haute disponibilité, bases managées) ne répondent à aucun besoin actuel.
- **IaaS plutôt qu'on-premise** : il n'y a ni serveur, ni salle, ni réseau à exploiter. Le fournisseur garantit l'alimentation, la connectivité et le remplacement du matériel, ce qu'une installation on-premise ferait porter à une personne seule.
- **Pas de service ML managé** : SageMaker, Vertex AI ou Azure ML apportent registre, entraînement et service de modèles. Mais MLflow, Prefect et FastAPI couvrent déjà ces besoins (ADR-0002, ADR-0009). Un service ML managé ajouterait un verrouillage fort et un coût sans gain pour un modèle de cette taille.
- **Hébergement dans l'UE** : les données de production restent en Autriche, sans transfert hors UE à encadrer (ADR-0012).
- **Local pour développer** : boucle de développement rapide et sans coût. `docker compose` reproduit la production pour tester l'intégration avant la CI.

## Consequences

**Positives**
- Coût minimal et prévisible (forfait annuel), sans facturation à l'usage.
- Contrôle complet de la pile, et apprentissage de l'exploitation (Docker, proxy, bases, sauvegardes), ce qui est l'objectif du cours.
- Données de production dans l'UE.
- Portabilité : la même image tourne en local, en compose, sur le VPS et sur un Kubernetes local.

**Négatives**
- Toute l'exploitation nous revient : mises à jour du système et de Coolify, sauvegardes, sécurité de la machine, surveillance.
- Pas de haute disponibilité : une panne du VPS arrête la préprod et la prod en même temps.
- VPS partagé : les autres projets se disputent la mémoire et le disque. Le disque de démarrage est un HDD, lent en écriture.
- La montée en charge est verticale et manuelle (changer d'offre de VPS) et demande une intervention.

**Neutres**
- Si le trafic ou les exigences de disponibilité augmentent, la décision est à revoir, en commençant par des bases managées puis par un PaaS de conteneurs. La portabilité de l'image rend ce passage peu coûteux.
- L'on-premise redeviendrait pertinent si l'entreprise imposait que ses données ne quittent pas ses locaux.

**Mesures d'atténuation**
- Limites de mémoire et de CPU sur chaque service (ADR-0003, ADR-0011).
- Sauvegardes planifiées des bases et des volumes (ADR-0003). Une copie hors du VPS est à prévoir pour survivre à une panne de la machine.
- Health checks et rollback par tag d'image (ADR-0004). Supervision prévue avec Prometheus et Grafana.

## Alternatives considered

- **Tout en local** (le Mac comme serveur) : gratuit, mais pas joignable en permanence, pas de HTTPS public, et la machine de développement sert alors aussi de production ; écarté.
- **On-premise** (serveur physique de l'entreprise) : maîtrise totale des données, mais matériel, réseau, électricité et astreinte à assumer, sans besoin qui le justifie ; écarté.
- **PaaS ou serverless de conteneurs** (Scaleway Serverless Containers, Azure Container Apps, Cloud Run) : peu d'exploitation, mais coût 15 à 30 fois plus élevé ici. Les conteneurs « mis en veille » sont incompatibles avec un worker et un rechargement de modèle permanents ; écarté.
- **Cloud managé complet** (conteneurs, bases et stockage objet managés chez AWS, Azure ou GCP) : haute disponibilité et sauvegardes gérées, mais coût et complexité disproportionnés ; écarté à ce stade.
- **Plateforme ML managée** (SageMaker, Vertex AI, Azure ML) : registre et service de modèles intégrés, mais verrouillage fort et coût, alors que MLflow et FastAPI suffisent ; écarté.
- **Hybride** (VPS pour l'API, cloud managé pour la base ou les artefacts) : améliorerait les sauvegardes, mais ajoute un fournisseur et des flux réseau ; reporté, à reconsidérer pour la copie hors site des sauvegardes.

## Links

- Related ADRs : [[ADR-0002 - Stockage des artefacts de modele]], [[ADR-0003 - Choix de la plateforme de déploiement]], [[ADR-0004 - Stratégie de déploiement]], [[ADR-0009 - Orchestration du réentraînement]], [[ADR-0011 - Estimation budgétaire]], [[ADR-0012 - Conformité RGPD]]
- Schéma : [architecture des composants](../schemas/architecture.svg)
