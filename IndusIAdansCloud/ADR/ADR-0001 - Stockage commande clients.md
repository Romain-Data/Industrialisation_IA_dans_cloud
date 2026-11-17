# ADR-0001 : Stockage des commandes clients

- Status: Accepted
- Date: 2026-10-06
- Deciders: Romain
- Tags: `database`

## Context

Les données des commandes clients doivent être stockés pour permettre d'entraîner le modèle de prédiction et afficher l'état de la commande. La technologie de stockage est libre, limitée uniquement par les ressources de la machine (MacBook Pro M1) pour la dev et une partie de VPS pour la prod.


## Decision

Nous stockons les commandes dans une seule table `commandes` (une ligne par commande), accessible uniquement via une couche d'accès aux données (interface de type repository, implémentée avec SQLAlchemy). En dev, la base est SQLite ; en prod, PostgreSQL. Le changement de base ne passe que par l'URL de connexion, fournie par variable d'environnement, et le schéma est versionné avec Alembic. Pour l'entraînement du modèle, la couche d'accès exporte la table vers une table DuckLake : les données sont stockées en fichiers Parquet, l'historique est géré par les snapshots DuckLake (time travel), et DuckDB sert de moteur d'accès. Le catalogue DuckLake utilise SQLite en dev et PostgreSQL en prod, mais il ne contient que les métadonnées du lac, pas les commandes. DuckLake n'est pas une source de vérité : la base transactionnelle reste la référence pour l'état des commandes.

### Justification

- **Une seule table** : les commandes sont gérées une par une, avec un seul article ou groupe d'articles (la colonne booléenne `stock_available` indique sa présence en stock). Il n'y a ni agrégation par client ou par date, ni lignes de commande, ni historique de statut à modéliser.
- **Base transactionnelle pour l'état des commandes** : l'affichage et la mise à jour du statut demandent des écritures ligne par ligne, ce que CSV et Parquet gèrent mal (réécriture du fichier).
- **SQLite en dev** : aucune installation, base réinitialisable en supprimant un fichier, adaptée aux ressources d'un MacBook Pro M1.
- **PostgreSQL en prod** : accès concurrent, types stricts et contraintes, standard de l'industrie, adapté à une partie de VPS. Le besoin du relationnel est faible aujourd'hui, mais le coût d'exploitation est acceptable.
- **Parquet pour l'entraînement** : format typé, compact et directement lisible en DataFrame (pandas, polars) pour la régression logistique. Le produire comme export évite de lui confier des mises à jour qu'il gère mal.
- **DuckLake pour l'historique des snapshots** : il remplace des fichiers Parquet datés gérés à la main par de vrais snapshots versionnés, interrogeables à une date ou une version donnée, ce qui rend l'entraînement reproductible. Ses métadonnées vivent dans une base SQL déjà présente dans l'architecture (SQLite en dev, PostgreSQL en prod), donc aucun service supplémentaire.
- **Commandes hors DuckLake** : DuckLake est pensé pour l'analytique. Y mettre directement les commandes (option envisagée) exposerait à de nombreuses petites modifications de statut, donc à beaucoup de snapshots et de petits fichiers, avec un comportement non évalué à notre échelle. La base transactionnelle reste donc le stockage des commandes.
- **Abstraction** : l'exercice porte sur la mise en production d'un POC. Séparer le code de la techno de stockage rend le changement de base peu coûteux et fait partie de ce qu'on veut pratiquer.
- **DuckDB retenu uniquement comme moteur de DuckLake** : il n'y a pas de requêtes analytiques complexes à faire, et le snapshot est chargé en mémoire par pandas ou polars. DuckDB n'intervient pas dans l'accès aux commandes (SQLAlchemy reste la seule voie) ; il sert à écrire et à lire les snapshots.

## Consequences

**Positives**
- Démarrage du dev sans service à installer.
- Changement de base limité à la configuration, ce qui permet de pratiquer l'abstraction.
- Entraînement reproductible et historisé grâce aux snapshots DuckLake (time travel sur les jeux d'entraînement).
- Schéma versionné et appliqué de la même façon sur les deux bases.

**Négatives**
- Risque d'écart de comportement entre SQLite et PostgreSQL : typage permissif de SQLite, booléen stocké en 0/1, clés étrangères désactivées par défaut, `ALTER TABLE` limité, un seul écrivain à la fois.
- Dépendance à SQLAlchemy et Alembic, et coût de maintenir une abstraction pour une seule table.
- Dans cette version, pas d'historique du suivi de commande possible
- PostgreSQL en prod ajoute un service à exploiter (sauvegardes, mises à jour, supervision) sur le VPS.
- Deux nouvelles dépendances (DuckDB et son extension DuckLake) pour une fonction d'historique. Je n'ai pas vérifié leur niveau de maturité ni leur lecture directe par pandas ou polars : à contrôler avant adoption.
- Le catalogue DuckLake en dev (SQLite) et en prod (PostgreSQL) reproduit le risque d'écart de comportement entre les deux bases.

**Neutres**
- Les snapshots DuckLake sont une copie des commandes : il faut décider quand les produire (à la demande ou planifié) et combien en conserver.
- Le catalogue DuckLake peut partager le serveur PostgreSQL de la prod, mais dans une base ou un schéma distinct de celui des commandes.
- Si le schéma s'étend (plusieurs articles, données client), le passage à plusieurs tables sera à refaire dans les migrations.

**Mesures d'atténuation**
- Exécuter les tests, ou au moins une vérification avant déploiement, sur PostgreSQL.
- Activer les contraintes côté SQLite (clés étrangères, `CHECK` sur le booléen).
- Ne jamais écrire de SQL en dehors de la couche d'accès.
- Faire un petit essai (spike) de DuckLake avec un catalogue SQLite puis PostgreSQL avant de figer le choix.

## Alternatives considérées

| Techno | Famille | Schéma | Mises à jour (état de commande) | Lecture analytique / entraînement ML | Accès concurrent | Mise en place / ops | Ressources |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CSV | Fichier plat | Aucun (types non conservés) | Réécriture du fichier entier | Lent, tout est parsé en texte | Aucun | Aucune | Très faibles |
| Parquet | Fichier colonnaire | Intégré au fichier | Immuable : réécriture de fichier/partition | Très rapide (colonnes, compression) | Lecture oui, écriture non | Aucune | Faibles |
| SQLite | SGBD embarqué | Oui | Oui (ACID) | Correct à moyen volume | Un seul écrivain à la fois | Aucune (fichier unique) | Très faibles |
| DuckDB | SGBD embarqué analytique | Oui | Possible, pas conçu pour l'OLTP | Très rapide, lit Parquet/CSV directement | Un seul processus écrivain | Aucune | Faibles |
| PostgreSQL | SGBD relationnel serveur | Oui, strict | Oui (MVCC, ACID) | Bon avec index/partitionnement | Excellent | Service à installer, sauvegardes, supervision | Moyennes |
| MySQL / MariaDB | SGBD relationnel serveur | Oui | Oui (ACID avec InnoDB) | Correct | Très bon | Service à installer | Moyennes |
| MongoDB | Base documents | Flexible | Oui, au niveau du document | Correct, agrégations moins naturelles | Très bon | Service à installer | Moyennes à élevées |
| Redis | Clé-valeur en mémoire | Aucun | Très rapide | Inadapté aux gros historiques | Très bon | Service simple | Limitées par la RAM |
| ClickHouse | SGBD colonnaire serveur | Oui | Faible (insertion en masse) | Excellent à grande échelle | Bon en lecture | Service plus lourd à exploiter | Moyennes à élevées |
| Delta Lake / Iceberg | Format de table sur Parquet | Oui, versionné | Oui (transactions, time travel) | Très bon | Bon | Dépend d'un moteur (Spark, DuckDB…) | Variables |
| DuckLake | Format de table sur Parquet, métadonnées dans une base SQL | Oui, versionné | Oui (transactions, time travel), mais pensé pour l'analytique | Très bon (via DuckDB) | Bon (ACID, isolation par snapshot) | Catalogue SQL (SQLite, PostgreSQL, MySQL, DuckDB) + fichiers Parquet | Faibles à moyennes |

Combinaisons courantes : SGBD transactionnel pour l'état des commandes + export Parquet pour l'entraînement ; SQLite ou PostgreSQL + DuckDB pour les requêtes analytiques ; Redis en cache devant une base principale.

Deux options ont été envisagées pour DuckLake :
1. **Retenue** : base transactionnelle pour les commandes, DuckLake pour les snapshots d'entraînement.
2. **Écartée** : commandes directement dans une table DuckLake, car le format n'est pas conçu pour des mises à jour fréquentes de statut.

## Mise en œuvre (2026-11-17)

- **Cible d'entraînement** : la table `commandes` ne contenait que les caractéristiques, pas le résultat. La migration `0002` ajoute `express_eligible` (0/1, nullable) et `outcome_recorded_at`. Le résultat observé est enregistré par `PUT /v1/orders/{order_id}/outcome` ; seules les commandes qui en ont un sont exportées.
- **Export** : `OrderStore.export_labeled_orders()` (SQLAlchemy, aucun SQL hors de la couche d'accès) produit un DataFrame au format d'entraînement, avec `created_at` comme `order_date`.
- **Snapshots** : `DuckLakeSnapshotStore` (abstraction `TrainingSnapshotStore`) remplace le contenu de la table `commandes_entrainement` dans une transaction ; chaque écriture crée un snapshot relisible avec `AT (VERSION => n)`. Catalogue configuré par `DUCKLAKE_CATALOG_URL` (URL SQLAlchemy : SQLite en dev, base `ducklake` du PostgreSQL du projet en prod, créée au démarrage), fichiers Parquet dans `DUCKLAKE_DATA_PATH` (volume `/app/ducklake` en prod).
- **Entraînement** : `TRAINING_SOURCE=ducklake` fige les commandes étiquetées dans un nouveau snapshot puis entraîne dessus ; le numéro du snapshot est enregistré dans le run MLflow (`ducklake_snapshot`), ce qui permet de rejouer un entraînement à l'identique. `TRAINING_SOURCE=synthetic` (par défaut) garde le générateur de dev. Au moins 50 commandes étiquetées sont exigées.
- **Spike réalisé** : DuckDB 2.0 + DuckLake, catalogue SQLite et PostgreSQL, time travel vérifié. Les extensions DuckDB sont installées au build de l'image (pas de téléchargement en prod). La lecture des dates avec fuseau demande `pytz`, absent avec pandas 3 : les dates sont stockées en UTC sans fuseau.
- **Pas encore fait** : politique de rétention des snapshots, planification de l'export.

## Links

- External references :
  - [DuckLake](https://ducklake.select)
  - [DuckLake FAQ](https://ducklake.select/faq.html)
  - [The Essential Guide to DuckLake](https://motherduck.com/learn-more/ducklake-guide/)