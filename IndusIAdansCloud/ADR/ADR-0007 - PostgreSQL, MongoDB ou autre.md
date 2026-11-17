# ADR-0007 : PostgreSQL, MongoDB ou autre ? Source des données ERP

- Status: Accepted
- Date: 2026-11-17
- Deciders: Romain
- Tags: `data`, `integration`, `etl`

## Context

L'entreprise utilise un ERP (« ERP Pro 2015 ») dont les commandes doivent alimenter notre application : entraînement du modèle, prédiction et API. Deux bases contiennent ces commandes :

- **PostgreSQL, base de production de l'ERP** : échange bilatéral en temps réel avec l'ERP. Elle existe depuis 2015, son schéma a changé en 2017 et en 2023, elle n'est plus administrée depuis 2023 (l'administrateur a démissionné et n'a pas été remplacé) et **elle sert aussi une autre application critique** pour l'entreprise.
- **MongoDB, base analytique** : alimentée en temps réel et à sens unique par un ETL depuis PostgreSQL. Elle a été montée en 2023 **pour les Data Analysts**, parce qu'ils cassaient la base de production. L'historique antérieur à 2023 n'y a pas été copié. Elle est maintenue par un alternant dont le contrat se termine bientôt, et n'a pas d'authentification.

Les mesures faites sur le simulateur fourni (`erp_simulator/`) confirment ces différences :

| | PostgreSQL | MongoDB |
|---|---|---|
| Période | 2015 → aujourd'hui | 2023 → aujourd'hui |
| Volume par défaut | ~11 000 commandes + flux | ~1 000 commandes + flux |
| `weekend` vide | oui, avant le 01/07/2015 | jamais |
| `preparation_time_min` vide | oui, avant le 01/07/2017 | jamais |
| Accès | utilisateur et mot de passe (faibles, fournis par le cours) | sans authentification |
| Format | table `public.orders`, `order_date` en `DATE` | collection `orders`, `order_date` en `datetime`, index unique sur `order_id` |

Dans les deux bases, les commandes **n'ont pas de cible** (`express_eligible`) et utilisent un **vocabulaire différent** de notre contrat d'API : météo `clear/rain/wind/snow`, 3 zones `centre/suburb/rural`, clients `individual/business`, `carrier_capacity` de 5 à 50. Le cours impose d'en choisir une seule et de ne pas faire confiance à la qualité des données.

## Decision

Nous intégrons les données de l'ERP depuis **MongoDB**, la base analytique, en **lecture seule**, par un **ETL** : l'application ne lit jamais l'ERP directement.

- **Lecture** : une implémentation `MongoOrderRepository` du contrat `OrderRepository` lit la collection `livraison_express.orders` (`get`, `get_all`, lecture incrémentale à partir du dernier `order_id` importé). Elle n'écrit jamais dans la base de l'ERP.
- **ETL** : toutes les heures, une tâche importe les nouvelles commandes, les **valide** (types, bornes, valeurs autorisées) et les **nettoie** avant de les écrire dans notre base, puis dans un snapshot DuckLake pour l'entraînement (ADR-0001). Les commandes rejetées sont comptées et journalisées, pas importées.
- **Vocabulaire** : l'ERP est le système de référence de l'entreprise ; nous **alignons** le contrat `openapi.yml`, la validation et le modèle sur ses valeurs, et réentraînons le modèle.
- **Orchestration** : l'ETL et le réentraînement sont des flows **Prefect** (ADR à venir), pas des étapes de la CI/CD : l'entraînement est un processus d'exécution, pas de construction de l'application.
- **Cible** : l'étiquette `express_eligible`, absente du jeu fourni, est calculée par la règle du notebook adaptée à l'ERP (voir Mise en œuvre).

### Justification

- **Ne pas toucher à la base de production** : PostgreSQL sert l'ERP et une autre application critique, et personne ne l'administre. Des lectures d'entraînement (requêtes longues, parcours complets) peuvent la ralentir ou y poser des verrous, et aucun administrateur ne peut créer un compte en lecture seule ni nous prévenir d'un changement de schéma. C'est précisément le risque que la base analytique a été créée pour éviter.
- **La base analytique est faite pour nous** : elle est destinée aux services Data, et une erreur de notre côté ne peut pas modifier la production (échange à sens unique).
- **Des données plus utiles, malgré moins d'historique** : les données de 2023 à aujourd'hui ont un schéma homogène, sans valeurs vides, et ressemblent davantage aux commandes que le modèle devra prédire. Les années 2015-2022 sont anciennes (dérive possible) et incomplètes. Pour un modèle de régression logistique à 12 variables, un millier de commandes par an suffit.
- **ETL plutôt que lecture directe** : l'application ne dépend pas de la disponibilité de l'ERP, la validation se fait en un seul endroit avant l'entrée des données, et chaque entraînement reste reproductible grâce aux snapshots DuckLake.
- **Aligner le vocabulaire sur l'ERP** : traduire les valeurs (une 4e zone, `wind` sans équivalent, une échelle de capacité différente) inventerait de l'information ; mieux vaut que le modèle apprenne sur les données réelles de l'entreprise.

## Consequences

**Positives**
- Aucun risque de ralentir ou de casser la base de production de l'ERP et de l'application critique qui la partage.
- Données d'entrée homogènes depuis 2023 : moins de nettoyage, moins de cas particuliers.
- Application découplée de l'ERP : une panne de MongoDB retarde l'import suivant, sans arrêter l'API.

**Négatives**
- **Pérennité** : la base est maintenue par un alternant sur le départ. Si l'ETL PostgreSQL → MongoDB s'arrête, nos données cessent d'être à jour sans que nous en soyons prévenus.
- **Sécurité** : MongoDB n'a pas d'authentification ; quiconque y accède peut lire ou modifier les données que nous importons.
- **Fraîcheur** : nos données ont jusqu'à une heure de retard (import horaire), plus le délai de l'ETL de l'ERP.
- **Moins d'historique** : pas de données avant 2023.
- **Changement incompatible** : aligner le vocabulaire modifie le contrat d'API (valeurs `weather`, `delivery_zone`, `customer_type`, bornes de `carrier_capacity`) ; le modèle actuel, entraîné sur l'ancien vocabulaire, doit être remplacé. Version majeure de l'API.
- **Nouvelle dépendance** : `pymongo`, et un service MongoDB à faire tourner dans nos environnements de test.

**Neutres**
- MongoDB n'impose pas de schéma : toute la validation repose sur notre ETL, qui doit être strict (le cours : « ne pas faire confiance à la qualité des données »).
- Les dates futures produites par le simulateur (flux qui avance d'un jour par lot) sont un artefact du jeu de test, à ne pas filtrer comme une erreur dans cet environnement.

**Mesures d'atténuation**
- Surveiller la fraîcheur : alerte si l'import horaire ne trouve aucune nouvelle commande pendant une durée anormale (signe que l'ETL de l'ERP est arrêté).
- Demander à l'entreprise, avant le départ de l'alternant, la reprise de la base analytique (propriétaire, sauvegardes) et un compte en lecture seule avec mot de passe ; en attendant, n'y accéder que depuis un réseau privé.
- Validation stricte et comptage des rejets dans l'ETL ; import idempotent (clé `order_id`), donc rejouable sans doublon.
- Si l'historique 2015-2022 devenait nécessaire, l'importer **une seule fois** depuis PostgreSQL, hors des heures de production, plutôt que de lire la production en continu.

## Alternatives considered

- **PostgreSQL de production** : historique complet et technologie déjà maîtrisée, mais lecture d'une base critique partagée, sans administrateur ni compte en lecture seule, et données 2015-2017 incomplètes ; écarté.
- **Réplica PostgreSQL dédié aux services Data** : la meilleure option à terme (données complètes, schéma relationnel, aucun impact sur la production), mais elle demande un administrateur pour mettre en place la réplication, ce qui n'existe pas aujourd'hui ; à proposer à l'entreprise.
- **Lecture directe de MongoDB par l'application** : plus simple, mais l'entraînement et l'API dépendraient de la disponibilité de l'ERP, et la validation serait dispersée ; écarté au profit de l'ETL.
- **Traduire le vocabulaire ERP vers notre contrat** : préserve l'API, mais impose des correspondances arbitraires (`wind`, 4e zone, échelle de capacité) ; écarté.
- **Deux sources combinées** (historique PostgreSQL + flux MongoDB) : plus de données, mais deux connexions, deux formats et toujours la lecture de la production ; écarté pour l'instant.

## Mise en œuvre (2026-11-17)

- **Lecture** : contrat `OrderRepository` (`src/abstraction/order_repository.py`) **aligné sur la correction de l'enseignant** : `save`, `get`, `get_all`, `count`, `get_training_data` (commandes et cibles séparées, la cible ne faisant pas partie de l'entité), plus `get_labeled_after` (import incrémental) et `ping`. Il manipule des entités du domaine (`OrderEntity`, `src/domain/entities.py`) et ne lève que des erreurs du domaine (`src/domain/exceptions.py`) : `save` lève `ReadOnlyRepositoryError` (lecture seule), une panne de MongoDB devient `RepositoryUnavailableError`. `MongoOrderRepository` est testé contre un vrai MongoDB 8 alimenté par le simulateur ; un service MongoDB tourne dans la CI.
- **Cible** : l'oubli du jeu fourni est corrigé (confirmé par l'enseignant). La règle de calcul du notebook (cellule 8, identique dans la correction) est extraite dans `src/domain/eligibility.py`, adaptée au vocabulaire de l'ERP, et le simulateur en applique une copie (tirage déterministe par commande) : `express_eligible` est présente dans PostgreSQL et MongoDB. Un test vérifie que les deux règles concordent. Les commandes écrites avant cet ajout n'ont pas de cible : elles sont exclues de l'entraînement.
- **Vocabulaire** : défini une seule fois dans le domaine (`src/domain/features.py` : `WEATHER_VALUES`, `DELIVERY_ZONE_VALUES`, `CUSTOMER_TYPE_VALUES`), repris par le schéma Pydantic, le contrat `openapi.yml` (version **2.0.0**) et la validation du domaine, qui refuse toute catégorie inconnue. `carrier_capacity` n'est plus borné à 1, seulement positif.
- **Données synthétiques** : le générateur de dev produit le vocabulaire et l'échelle de l'ERP ; ses coefficients (`wind` 0,15, `suburb` 0,20, `business` +0,15, capacité ramenée sur 50) sont des hypothèses de simulation, à remplacer si l'intervenant fournit une règle d'étiquetage.
- **Modèles** : chaque run enregistre `data_schema = erp-v1` ; un champion entraîné sur l'ancien vocabulaire est remplacé d'office au premier entraînement (ADR-0002, mise à jour du 2026-11-17).
- **Données existantes** : les quelques commandes de test enregistrées en preprod avec l'ancien vocabulaire seraient refusées par la validation lors d'un entraînement `TRAINING_SOURCE=ducklake` ; preprod et prod restent en `synthetic`.
- **Reste à faire** : l'ETL (validation, nettoyage, import horaire), les compose Test et Prod, l'orchestration Prefect.

## Links

- Related ADRs : [[ADR-0001 - Stockage des commandes]], [[ADR-0005 - Sécurisation des entrées, sorties et accès à la donnée]], [[ADR-0006 - File d'attente]]
- Simulateur : `erp_simulator/` (`docker-compose.erp.yml`, `storage.py`, `generator.py`)
- Cours « Industrialisation de l'IA dans le cloud #4 » : base analytique, réplication, intégration d'une base au projet
- External references :
  - [PyMongo](https://pymongo.readthedocs.io/)
  - [Prefect](https://docs.prefect.io/)
