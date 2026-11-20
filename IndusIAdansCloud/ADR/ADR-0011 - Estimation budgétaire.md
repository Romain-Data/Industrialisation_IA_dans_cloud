# ADR-0011 : Estimation budgétaire

- Status: Accepted
- Date: 2026-11-20
- Deciders: Romain
- Tags: `infra`, `budget`

## Context

Le barème demande une estimation du coût du projet. L'application tourne sur un VPS **déjà payé et partagé** avec d'autres projets (ADR-0003). Il s'agit d'un VPS NetCup (4 vCPU, 8 Go de RAM, 256 Go de disque) hébergé à **Vienne (Autriche)**. Le contrat coûte **141,84 € par an**, dont **13,80 € par an** pour le nom de domaine `romaincollery.com`, soit **128,04 € par an** pour le serveur seul (environ 10,67 € par mois).

Le projet tourne sur ce VPS sous forme de conteneurs gérés par Coolify, avec des limites de ressources :

| Service | Environnement | Mémoire max. | CPU max. |
|---|---|---|---|
| API + worker (`express-delivery-*`) | preprod et prod | 1 Go chacun | 1 chacun |
| PostgreSQL 17 | preprod et prod | 256 Mo chacun | 0,5 chacun |
| Serveur Prefect (ADR-0009) | prod | 512 Mo | 0,5 |
| Orchestrateur Prefect (ETL + entraînement) | prod | 1,5 Go | 1 |
| ERP simulé : MongoDB, PostgreSQL, simulateur (ADR-0009) | prod | 512 Mo + 256 Mo + 128 Mo | 0,5 + 0,5 + 0,25 |

Les autres services utilisés sont gratuits pour un dépôt public : GitHub, GitHub Actions et GitHub Container Registry. C'est aussi le cas de Coolify (auto-hébergé), MLflow, Prefect et DuckLake (open source, auto-hébergés).

Il faut aussi chiffrer le temps humain : la construction du projet, puis son exploitation.

## Decision

Nous retenons comme budget de référence **la quote-part du VPS partagé**, calculée sur la mémoire réservée. La mémoire est la ressource limitante sur ce VPS. Nous y ajoutons une **estimation en jours de travail**. Un hébergement cloud managé sert de point de comparaison, pas de cible.

### Coût de l'infrastructure

La quote-part est la mémoire maximale réservée par le projet, rapportée aux 8 Go du VPS, appliquée au prix annuel du serveur (128,04 €).

| Périmètre | Mémoire réservée | Part du VPS | Coût annuel | Coût mensuel |
|---|---|---|---|---|
| Initial (17/11) : API + PostgreSQL en preprod et en prod | 2,5 Go | 31 % | ≈ 40 € | ≈ 3,3 € |
| Actuel (20/11) : + Prefect et ERP simulé en prod | 5,4 Go | 67 % | ≈ 86 € | ≈ 7,2 € |
| Nom de domaine (sous-domaines `express-delivery*`) | — | — | 0 € de plus (13,80 € déjà payés) | — |
| GitHub, Actions, GHCR, logiciels open source | — | — | 0 € | 0 € |

Le coût marginal réel est **nul** : le VPS et le domaine étaient déjà payés avant le projet. La quote-part mesure ce que le projet « consomme » de la machine. Si le projet utilisait la machine seul, le coût total serait de **141,84 € par an** (≈ 11,80 € par mois).

Ces montants supposent que tout tourne en permanence. Entre deux vérifications, le projet est éteint (`scripts/coolify_power.py off all`) : la mémoire revient aux autres projets du VPS, et les données restent dans les volumes.

### Point de comparaison : cloud managé

Ordres de grandeur, relevés en novembre 2026, à revérifier sur les calculateurs des fournisseurs avant toute décision :

- **Conteneurs serverless** : chez Scaleway, la seconde de vCPU coûte 0,00001 € et la seconde par Go de mémoire 0,000002 €. Un conteneur toujours actif (1 vCPU, 1 Go) revient donc à environ **31 € par mois**, avant la franchise gratuite. Il en faut deux (preprod et prod), plus l'orchestrateur : **≈ 60 à 90 € par mois**.
- **PostgreSQL managé** : une petite instance (type AWS RDS `db.t4g.micro`) coûte environ **11 à 15 $ par mois** en Europe. Il en faut deux : **≈ 25 à 30 € par mois**.
- **Stockage des artefacts et des snapshots** (objet, quelques Go) : quelques euros par mois.

Soit **≈ 90 à 120 € par mois** (≈ 1 100 à 1 450 € par an) pour un service équivalent, avec en plus la haute disponibilité et les sauvegardes managées. C'est **15 à 30 fois** la quote-part actuelle.

### Coût humain

Estimation, en jours de travail d'une personne :

| Lot | Jours |
|---|---|
| Analyse du notebook, domaine métier, contrat d'API (OpenAPI) | 3 |
| API FastAPI, file d'attente et worker, stockage (SQLAlchemy, Alembic) | 5 |
| Entraînement, MLflow, DuckLake, promotion champion / challenger, garde-fous | 5 |
| ETL depuis l'ERP (MongoDB), orchestration Prefect | 4 |
| Docker, CI/CD GitHub Actions, Coolify (preprod et prod), sécurité | 6 |
| Tests, documentation (README, ADR, schémas) | 4 |
| **Total de construction** | **≈ 27 jours** |
| **Exploitation** : mises à jour, surveillance, réentraînements à valider, rollbacks | **≈ 1 à 2 jours par mois** |

Avec une hypothèse de **400 € par jour** (taux journalier d'un profil data / MLOps junior en prestation, à adapter), on obtient environ **10 800 €** pour la construction et **400 à 800 € par mois** pour l'exploitation. Le temps humain représente l'essentiel du coût, très loin devant l'infrastructure.

### Justification

- **Quote-part sur la mémoire** : sur ce VPS, la mémoire est la ressource rare (le CPU est rarement saturé). Les limites Coolify et compose donnent une borne haute mesurable.
- **Garder le VPS partagé** : pour un modèle léger (régression logistique) et un trafic faible, la différence de coût avec le cloud managé ne se justifie pas. Les manques (une seule instance, sauvegardes à configurer soi-même) sont acceptés dans l'ADR-0003.
- **Chiffrer le temps humain** : c'est le poste principal. Ignorer ce coût ferait croire que le projet coûte 3 € par mois.

## Consequences

**Positives**
- Un coût d'infrastructure très faible et prévisible : un forfait annuel, sans facturation à l'usage ni mauvaise surprise.
- Aucun coût de licence : toute la pile est open source ou gratuite pour un dépôt public.
- Une base chiffrée pour comparer, si le projet grossit, le passage à un cloud managé.

**Négatives**
- La quote-part est une convention : un pic de mémoire d'un autre projet du VPS peut pénaliser celui-ci, et inversement.
- La gratuité de GitHub Actions et de GHCR dépend du **dépôt public**. Un dépôt privé ferait entrer en jeu les quotas gratuits, puis une facturation.
- Le temps d'exploitation (1 à 2 jours par mois) est une estimation : il n'est pas mesuré.
- Les prix du cloud évoluent (par exemple, hausse du prix de la mémoire des conteneurs serverless Scaleway au 1er juin 2026) : la comparaison vieillit vite.

**Neutres**
- Les sauvegardes planifiées (ADR-0003) restent sur le disque du VPS. Une copie hors site (stockage objet) ajouterait quelques euros par mois.

**Mesures d'atténuation**
- Garder les limites de mémoire de chaque service et arrêter la preprod quand elle ne sert pas (ADR-0004).
- Revoir cette estimation à chaque changement de plateforme ou de dimensionnement, et à chaque renouvellement du contrat NetCup.

## Alternatives considered

- **Cloud managé** (Scaleway, AWS, Azure) : haute disponibilité et services managés, mais un coût 15 à 30 fois plus élevé pour un trafic faible ; écarté à ce stade.
- **VPS dédié au projet** : isole le projet des autres, mais double le coût du serveur (≈ 128 € par an de plus) sans besoin de performance ; écarté.
- **Ne chiffrer que l'infrastructure** : plus simple, mais ignore le poste principal ; écarté.

## Links

- Related ADRs : [[ADR-0003 - Choix de la plateforme de déploiement]], [[ADR-0004 - Stratégie de déploiement]], [[ADR-0009 - Orchestration du réentraînement]], [[ADR-0012 - Conformité RGPD]]
- External references :
  - [Scaleway : prix des Serverless Containers](https://www.scaleway.com/en/pricing/serverless/)
  - [Scaleway : mise à jour des prix (2026)](https://www.scaleway.com/en/blog/a-transparent-update-on-scaleway-pricing/)
  - [Bytebase : prix de RDS db.t4g.micro](https://www.bytebase.com/dbcost/rds/instance/db.t4g.micro/)
