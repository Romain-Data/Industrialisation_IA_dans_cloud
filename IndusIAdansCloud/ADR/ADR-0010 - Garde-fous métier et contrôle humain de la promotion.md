# ADR-0010 : Garde-fous métier et contrôle humain de la promotion

- Status: Accepted
- Date: 2026-11-18
- Deciders: Romain
- Tags: `mlops`, `gouvernance`, `qualité`

## Context

Le modèle est réentraîné en prod dès que `RETRAIN_MIN_NEW_ORDERS` (500) nouvelles commandes étiquetées sont arrivées (ADR-0009). Jusqu'ici, la promotion était **entièrement automatique** : un candidat au `roc_auc` strictement supérieur à celui du champion, mesuré sur le même jeu d'évaluation (ADR-0002, mise à jour du 2026-11-18), devenait champion, et l'API le chargeait dans la minute. L'humain n'intervenait qu'après coup, par un rollback.

Or le `roc_auc` mesure la qualité du **classement** des commandes, pas les décisions prises **au seuil** (0,5), qui sont celles que voit le métier. Un modèle peut gagner en `roc_auc` et pourtant :

- promettre davantage de livraisons express impossibles (faux positifs) : clients déçus, coûts de livraison ;
- se dégrader sur un segment (zone rurale, neige) en compensant ailleurs ;
- changer brutalement la part de commandes déclarées éligibles, et désorganiser la préparation et les transporteurs.

Il faut donc décider de la place de l'humain : valider chaque modèle (sûr mais lourd, toutes les 500 commandes), ou ne rien valider (rapide mais aveugle au métier).

## Decision

L'humain est **« sur la boucle »** plutôt que « dans la boucle » : **il fixe les règles, l'automatisation les applique, et elle lui rend la main hors du cadre.**

1. **Garde-fous métier**, vérifiés sur le jeu d'évaluation commun (`src/domain/evaluation.py`) :

   | Garde-fou | Seuil | Raison métier |
   |---|---|---|
   | Précision minimale | `MIN_PRECISION = 0.85` | au moins 85 % des express promis doivent être tenables |
   | Baisse maximale du ROC AUC par segment (`delivery_zone`, `weather`) | `MAX_SEGMENT_AUC_DROP = 0.05` | un gain global ne doit pas cacher une dégradation pour une partie des clients |
   | Écart maximal de la part d'éligibles | `MAX_POSITIVE_RATE_SHIFT = 0.05` | pas de basculement brutal de la charge logistique |

   Les segments de moins de `MIN_SEGMENT_ROWS = 50` commandes, ou sans les deux classes, ne sont pas comparés (score trop bruité). Sans champion comparable (premier modèle, ou changement de schéma de données), seul le seuil de précision s'applique.

2. **Trois issues** pour chaque candidat (`promote_if_better`, `src/training/registry.py`), enregistrées dans son run MLflow (tags `promotion_decision` et `guardrail_failures`) :
   - pas meilleur que le champion → `rejected` ;
   - meilleur et tous les garde-fous respectés → `champion`, promotion automatique ;
   - meilleur mais un garde-fou violé → alias **`challenger`** : le modèle **n'est pas servi**, un humain tranche.

3. **Décision humaine** par une commande, dans un conteneur qui voit le registre (l'orchestrateur) :
   ```bash
   python -m src.training.promote               # valider le challenger
   python -m src.training.promote --version 3   # rollback vers la version 3
   ```
   Le run promu reçoit le tag `promotion_decision = champion (décision humaine)`. L'API charge le nouveau champion d'elle-même (ADR-0009).

### Justification

- **Les seuils sont une décision métier, pas un réglage technique.** Ils sont écrits dans le code du domaine et dans cet ADR, pas en variables d'environnement : les changer passe par une PR relue, et l'historique dit qui a changé quoi et pourquoi.
- **Le cas courant reste automatique.** Un réentraînement ordinaire (500 commandes de plus, distribution stable) respecte les garde-fous : personne n'est sollicité pour rien, et les validations restent attentives quand elles ont lieu.
- **Le doute bloque, il ne promeut pas.** Un candidat douteux reste hors service jusqu'à une décision explicite ; le champion en place continue de répondre.
- **Les valeurs actuelles sont des propositions** calées sur le modèle de base (précision mesurée autour de 0,88 à 0,90 sur les données synthétiques). Elles sont à confirmer par le métier (responsable logistique) avant la mise en production réelle.

## Consequences

**Positives**
- Un meilleur score ne suffit plus : la promotion respecte des critères compréhensibles par le métier.
- Chaque décision est traçable dans MLflow : score du champion sur le même jeu, garde-fous violés, décision automatique ou humaine.
- Le rollback, prévu par l'ADR-0002 mais manuel, devient une commande documentée et testée.

**Négatives**
- Un challenger peut attendre longtemps si personne ne surveille : les données récentes ne profitent pas au modèle servi entre-temps.
- Les garde-fous restent **hors ligne** : ils jugent le candidat sur des commandes passées, pas sur son comportement réel en production.
- Les seuils fixes peuvent devenir inadaptés si l'activité change (nouvelle zone, saisonnalité forte).

**Mesures d'atténuation**
- Notifier l'équipe quand un challenger apparaît (tâche Prefect ou alerte sur le tag `promotion_decision`) : évolution prévue avec le déploiement de l'orchestrateur.
- Revoir les seuils à chaque revue trimestrielle du modèle, ou lors d'un changement d'activité.
- Le mode shadow (ci-dessous) répond à la limite « hors ligne ».

## Alternatives considered

- **Validation humaine de chaque modèle (« dans la boucle »)** : contrôle maximal, mais une validation toutes les 500 commandes devient une formalité vite expédiée, et retarde tous les modèles, y compris les bons. Écartée.
- **Promotion entièrement automatique sur le `roc_auc` (« hors de la boucle »)** : l'état précédent, aveugle au coût métier des erreurs. Écartée.
- **Un seul critère métier à la place du `roc_auc`** (par exemple, coût total des erreurs) : plus juste en théorie, mais il faudrait chiffrer le coût d'un faux positif et d'un faux négatif, ce que l'entreprise ne sait pas encore faire. Gardé comme évolution possible.
- **Mode shadow** : voir ci-dessous. Non retenu aujourd'hui pour des raisons de ressources, mais recommandé en conditions réelles.

### Le mode shadow : non retenu ici, recommandé en conditions réelles

**Principe.** Le challenger est déployé **à côté** du champion. Chaque commande reçue par l'API est prédite par les deux modèles, mais **seule la réponse du champion est renvoyée** à l'ERP. La prédiction du challenger est enregistrée en base avec l'identifiant de la commande. Quand le résultat réel de la commande arrive (livrée en express ou non), on compare les deux modèles sur ce qu'ils auraient décidé **en conditions réelles**.

```
commande ──▶ API ──▶ champion ──▶ réponse à l'ERP
               └───▶ challenger ──▶ table shadow_predictions (jamais renvoyée)

plus tard : résultat réel ──▶ comparaison champion / challenger ──▶ décision de promotion
```

**Ce qu'il apporte, que nos garde-fous n'ont pas :**
- une évaluation sur les **vraies commandes du moment**, pas sur un jeu d'évaluation passé : il détecte une dérive des données que le jeu d'évaluation ne contient pas encore ;
- une mesure du **comportement en production** : latence, erreurs, valeurs inattendues envoyées par l'ERP ;
- une décision humaine fondée sur des chiffres réels (« sur 2 000 commandes réelles, le challenger aurait évité 40 promesses non tenues ») plutôt que sur une estimation ;
- **aucun risque pour le client** : le challenger ne décide jamais rien tant qu'il n'est pas promu.

**Pourquoi nous ne l'avons pas mis en place :**
- **mémoire** : l'API charge deux modèles et les recharge à chaque nouveau challenger, sur un VPS partagé où l'API est limitée à 1 Go (ADR-0003) ;
- **calcul** : chaque commande est prédite deux fois ;
- **stockage et code** : une table de prédictions shadow, une tâche qui rapproche prédictions et résultats réels, un rapport de comparaison ;
- **délai** : il faut attendre que les résultats réels arrivent, donc des jours ou des semaines avant de pouvoir conclure, ce qui est disproportionné pour un projet de cours sur données simulées.

**Mise en place, le jour où ce sera justifié :**
1. l'API charge aussi l'alias `challenger` s'il existe (le `ModelReloader` surveille déjà le registre) ;
2. après la réponse du champion, une tâche de fond prédit avec le challenger et écrit dans `shadow_predictions` (identifiant de commande, version, probabilité), sans allonger la réponse à l'ERP ;
3. l'orchestrateur rapproche ces prédictions des résultats importés de l'ERP, et calcule les mêmes garde-fous sur les commandes réelles ;
4. au-delà d'un volume suffisant (par exemple 1 000 commandes avec résultat), le rapport est présenté à l'humain, qui promeut ou écarte le challenger avec `python -m src.training.promote`.

Une étape intermédiaire possible est le **déploiement canari** : le challenger répond réellement pour une petite part des commandes (5 %). Il donne des résultats plus vite que le mode shadow, mais il expose des clients à un modèle non validé ; il ne convient donc qu'une fois les garde-fous hors ligne passés.

## Links

- Related ADRs : [[ADR-0002 - Stockage des artefacts de modele]], [[ADR-0009 - Orchestration du réentraînement]], [[ADR-0003 - Choix de la plateforme de déploiement]]
- Code : `src/domain/evaluation.py`, `src/training/registry.py`, `src/training/promote.py`
- Tests : `tests/test_evaluation.py`, `tests/test_pipeline.py`
- External references :
  - [Google : Rules of Machine Learning (règle 24, mesurer l'écart entre modèles avant de les déployer)](https://developers.google.com/machine-learning/guides/rules-of-ml)
  - [MLflow : alias de modèles](https://mlflow.org/docs/latest/ml/model-registry/)
