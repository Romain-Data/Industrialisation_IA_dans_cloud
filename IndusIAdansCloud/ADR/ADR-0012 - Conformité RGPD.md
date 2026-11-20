# ADR-0012 : Conformité RGPD

- Status: Accepted
- Date: 2026-11-20
- Deciders: Romain
- Tags: `conformité`, `données`, `sécurité`

## Context

Le barème demande de prendre en compte les normes, en premier lieu le RGPD. Dans le cadre du cours, les données sont **simulées** (simulateur d'ERP). Cette décision raisonne comme si elles étaient réelles.

**Données traitées par l'application.** Une commande contient : identifiant métier (`order_id`), heure, jour, week-end, distance, montant, poids, disponibilité du stock, temps de préparation, capacité du transporteur, météo, zone de livraison (trois zones larges), type de client (`individual` / `business`), date de création. S'y ajoutent le résultat réel (`express_eligible`) et la prédiction (probabilité, décision, version du modèle). Ces données sont stockées dans PostgreSQL, dans les snapshots DuckLake utilisés pour l'entraînement, et dans les métriques MLflow.

**Aucune donnée directement identifiante** : ni nom, ni adresse, ni e-mail, ni téléphone. Le contrat d'API refuse tout champ inconnu (`extra="forbid"`). Mais `order_id` permet, **chez le client**, de retrouver la commande dans l'ERP, donc la personne qui l'a passée lorsque `customer_type = individual`. Ce sont des **données pseudonymisées**, qui restent des données personnelles au sens du RGPD (considérant 26).

**Autres données personnelles** :
- adresses IP des appelants dans les journaux du proxy de Coolify et d'uvicorn ;
- comptes GitHub des contributeurs.

**Hébergement et transferts.**
- Le VPS (NetCup) est à **Vienne, en Autriche**, dans l'Union européenne (ADR-0011).
- GitHub (États-Unis) héberge le code, la CI et les images Docker. Les images ne contiennent aucune donnée : le `.dockerignore` exclut les bases, les artefacts et les notebooks. La CI ne manipule que des données de test.

**Décision automatisée.** La prédiction décide si une commande peut partir en livraison express. Cette décision porte sur l'organisation logistique, pas sur un droit ou une situation de la personne. Elle n'a pas d'effet juridique ni d'effet « significatif » au sens de l'article 22. Les garde-fous métier et la décision humaine de promotion (ADR-0010) encadrent en plus l'évolution du modèle.

## Decision

Nous traitons les commandes comme des **données personnelles pseudonymisées**, avec les principes et mesures suivants.

- **Rôles** :
  - l'entreprise cliente (l'e-commerçant) est **responsable de traitement** ;
  - le prestataire qui exploite l'application est **sous-traitant** (article 28), avec un contrat qui encadre le traitement ;
  - NetCup est **sous-traitant ultérieur**, via son accord de traitement des données (DPA).
- **Finalités** : prédire l'éligibilité d'une commande à la livraison express, et entraîner et évaluer le modèle qui la prédit. Aucune autre utilisation : ni profilage marketing, ni revente.
- **Base légale** : **intérêt légitime** du responsable de traitement, qui veut optimiser ses livraisons. Le traitement porte sur des données peu sensibles et non directement identifiantes, ce qui joue en faveur de cet équilibre.
- **Minimisation** : le contrat d'API (`openapi.yml`, schémas Pydantic avec `extra="forbid"`) **refuse tout champ** en dehors des variables utiles au modèle. L'ETL ne lit que ces colonnes dans l'ERP (ADR-0007). Ajouter une variable personnelle (adresse, nom) demande une modification du contrat, donc une PR relue, et une mise à jour de cet ADR.
- **Localisation** : les données de production (PostgreSQL, volumes MLflow et DuckLake) restent sur le VPS, **dans l'UE**. Aucune donnée de production n'est envoyée sur GitHub : ni dans le dépôt, ni dans les images, ni dans les journaux de CI.
- **Durées de conservation** (à appliquer par une purge automatique, voir plus bas) :
  - commandes et prédictions : **3 ans** après la création, le temps de constituer un historique d'entraînement. Au-delà, suppression ou agrégation anonyme ;
  - snapshots DuckLake : on garde ceux **référencés par un modèle encore enregistré** dans MLflow (reproductibilité, ADR-0001). Les autres sont expirés après 1 an ;
  - journaux contenant des IP : **6 mois** au plus, et seulement pour la sécurité.
- **Droits des personnes** (accès, rectification, effacement, opposition) : les demandes arrivent chez le responsable de traitement. Il fournit l'`order_id` concerné, et le sous-traitant supprime ou extrait les lignes dans PostgreSQL. Les snapshots déjà figés sont **immuables** : une ligne effacée en sort au plus tard à l'expiration du snapshot, et elle n'entre plus dans les entraînements suivants.
- **Sécurité (article 32)** : mesures de l'ADR-0005 :
  - secrets dans Coolify et dans les secrets GitHub ;
  - ports publiés seulement en `127.0.0.1` ;
  - conteneurs sans root, images scannées par Trivy ;
  - HTTPS via le proxy de Coolify ;
  - ERP lu en lecture seule ;
  - bases propres à chaque environnement.
- **Registre des traitements (article 30)** : le responsable de traitement y inscrit le traitement « prédiction de l'éligibilité à la livraison express ». Le sous-traitant tient son propre registre des traitements effectués pour le compte du client.
- **Analyse d'impact (AIPD)** : **non requise**. Les données ne sont ni sensibles ni directement identifiantes, il n'y a pas de surveillance systématique, et la décision automatisée n'a pas d'effet significatif sur la personne. Elle redevient nécessaire si une donnée identifiante ou de localisation précise (adresse, coordonnées GPS) entre dans le modèle.
- **Transparence** : la *model card* exposée par l'API (version, métriques, date d'entraînement) documente le modèle utilisé. La politique de confidentialité de l'e-commerçant mentionne l'usage d'un modèle prédictif pour organiser les livraisons.
- **Règlement européen sur l'IA (AI Act)** : un modèle d'aide à la logistique ne fait pas partie des usages classés « à haut risque ». Nous appliquons quand même ses bonnes pratiques : traçabilité des versions (MLflow), données d'entraînement versionnées (DuckLake), contrôle humain de la promotion (ADR-0010).

### Justification

- **Données pseudonymisées plutôt qu'anonymes** : `order_id` permet de réidentifier la personne en croisant avec l'ERP. Considérer les données comme anonymes ferait sortir à tort le traitement du RGPD.
- **Intérêt légitime plutôt que consentement** : le consentement n'est pas adapté à une étape logistique interne, et il serait impossible à recueillir pour l'historique de l'ERP.
- **Minimisation par le contrat d'API** : c'est le point de contrôle le plus sûr, car une donnée qui n'entre pas dans l'application n'a pas besoin d'être protégée, conservée ou effacée.
- **Hébergement dans l'UE** : aucun transfert hors UE à encadrer pour les données de production.

## Consequences

**Positives**
- Les données du projet sont peu sensibles et minimisées par construction : le risque RGPD est faible.
- Aucun transfert des données de production hors de l'UE.
- La traçabilité déjà en place (MLflow, DuckLake, ADR-0010) sert aussi la conformité.

**Négatives**
- **La purge automatique n'existe pas encore** : aujourd'hui, les commandes, les prédictions et les snapshots sont conservés sans limite. Les durées ci-dessus sont des décisions qui restent à implémenter.
- L'immuabilité des snapshots retarde l'effacement effectif d'une ligne jusqu'à l'expiration du snapshot.
- Les journaux du proxy de Coolify contiennent des IP, et leur durée de conservation dépend de la configuration de Coolify, pas du code du projet.
- Pas de procédure outillée pour les demandes d'accès ou d'effacement : ce sont aujourd'hui des requêtes SQL manuelles.

**Neutres**
- Les smoke tests de la preprod écrivent des commandes de test fictives (ADR-0004), sans donnée personnelle.
- Si le projet passait chez un fournisseur cloud non européen, il faudrait réexaminer les transferts (clauses contractuelles types, *Data Privacy Framework*).

**Mesures d'atténuation**
- Ajouter une tâche Prefect de purge (commandes et prédictions de plus de 3 ans, snapshots expirés non référencés). Elle sera tracée dans une future mise à jour de cet ADR.
- Régler la rotation des journaux du proxy et des conteneurs dans Coolify (6 mois au plus).
- Écrire une courte procédure (requêtes SQL par `order_id`) pour les demandes d'accès et d'effacement.
- Relire cet ADR à chaque ajout de variable au contrat d'API.

## Alternatives considered

- **Considérer les données comme anonymes** : plus simple, mais faux tant que `order_id` permet de remonter à la personne ; écarté.
- **Hacher `order_id` avant stockage** : renforce la pseudonymisation, mais casse le lien avec l'ERP, nécessaire pour enregistrer le résultat réel (`PUT /v1/orders/{id}/outcome`) ; écarté.
- **Consentement comme base légale** : inadapté à un traitement logistique interne ; écarté.
- **Conservation illimitée pour maximiser l'historique d'entraînement** : contraire au principe de limitation de la conservation ; écarté.
- **Snapshots modifiables pour effacer immédiatement** : casserait la reproductibilité des entraînements (ADR-0001) ; écarté au profit de l'expiration.

## Links

- Related ADRs : [[ADR-0001 - Stockage des commandes]], [[ADR-0005 - Sécurisation des entrées, sorties et accès à la donnée]], [[ADR-0007 - PostgreSQL, MongoDB ou autre]], [[ADR-0010 - Garde-fous métier et contrôle humain de la promotion]], [[ADR-0011 - Estimation budgétaire]]
- External references :
  - [Règlement (UE) 2016/679 (RGPD), EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
  - [Règlement (UE) 2024/1689 (AI Act), EUR-Lex](https://eur-lex.europa.eu/eli/reg/2024/1689/oj)
  - [CNIL](https://www.cnil.fr)
