"""Jeu d'évaluation commun à tous les modèles : comparer champion et candidat à armes égales.

Un découpage aléatoire (train_test_split) change à chaque entraînement : le score du
champion et celui du candidat seraient mesurés sur des commandes différentes, et
le champion aurait pu s'entraîner sur des commandes du jeu de test du candidat.

Ici, l'appartenance au jeu d'évaluation dépend uniquement de l'identifiant de la
commande (empreinte SHA-256) :
- une commande d'évaluation le reste à chaque réentraînement : aucun modèle ne
  l'a jamais vue à l'entraînement ;
- les nouvelles commandes y entrent dans la même proportion : le jeu reste
  représentatif des données récentes.
"""

import hashlib

import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from src.domain.classifier import Classifier
from src.domain.features import FEATURE_COLUMNS, TARGET_COLUMN

ID_COLUMN = "order_id"
# Part des commandes réservées à l'évaluation (en pourcentage).
HOLDOUT_PERCENT = 20
# Enregistré avec chaque run : deux scores ne sont comparables qu'avec le même protocole.
EVALUATION_PROTOCOL = f"sha256-{ID_COLUMN}-{HOLDOUT_PERCENT}pct"


def is_holdout(order_id: object) -> bool:
    """Vrai si la commande appartient au jeu d'évaluation (stable dans le temps)."""
    digest = hashlib.sha256(str(order_id).encode()).hexdigest()
    return int(digest[:8], 16) % 100 < HOLDOUT_PERCENT


def split_holdout(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sépare les commandes d'entraînement et d'évaluation ; retourne (train, holdout)."""
    if ID_COLUMN not in df.columns:
        raise ValueError(f"Colonne {ID_COLUMN} absente : impossible de fixer le jeu d'évaluation.")

    mask = df[ID_COLUMN].map(is_holdout).astype(bool)
    train, holdout = df[~mask], df[mask]

    for name, part in (("entraînement", train), ("évaluation", holdout)):
        if part[TARGET_COLUMN].nunique() < 2:
            raise ValueError(
                f"Jeu d'{name} sans les deux classes ({len(part)} commandes) : "
                "pas assez de données pour entraîner et comparer les modèles."
            )
    return train, holdout


def evaluate(model: Classifier, holdout: pd.DataFrame) -> dict[str, float]:
    """Métriques d'un modèle sur le jeu d'évaluation."""
    y_true = holdout[TARGET_COLUMN]
    y_proba = model.predict_proba(holdout[FEATURE_COLUMNS])[:, 1]
    y_pred = (y_proba >= 0.5).astype(int)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, y_proba)),
    }


# --- Garde-fous métier (ADR-0010) -------------------------------------------------
# Seuils fixés par le métier, pas par l'équipe data : les modifier demande une mise à
# jour de l'ADR-0010. Un candidat meilleur en ROC AUC qui en viole un n'est pas promu
# automatiquement : il devient « challenger » et un humain tranche.

# Part minimale des « oui » réellement faisables : au moins 85 % des livraisons express
# promises doivent pouvoir être tenues.
MIN_PRECISION = 0.85
# Baisse maximale du ROC AUC sur un segment (zone, météo) par rapport au champion :
# un gain global ne doit pas cacher une dégradation pour une partie des clients.
MAX_SEGMENT_AUC_DROP = 0.05
SEGMENT_COLUMNS = ("delivery_zone", "weather")
# En dessous, le ROC AUC d'un segment est trop bruité pour être comparé.
MIN_SEGMENT_ROWS = 50
# Écart maximal de la part de commandes déclarées éligibles : un basculement brutal
# désorganiserait la logistique (préparateurs, transporteurs).
MAX_POSITIVE_RATE_SHIFT = 0.05


def _positive_rate(model: Classifier, holdout: pd.DataFrame) -> float:
    return float((model.predict_proba(holdout[FEATURE_COLUMNS])[:, 1] >= 0.5).mean())


def _segment_auc(model: Classifier, holdout: pd.DataFrame, column: str) -> dict[str, float]:
    """ROC AUC par valeur de `column`, pour les segments assez grands et avec deux classes."""
    scores: dict[str, float] = {}
    for value, segment in holdout.groupby(column):
        if len(segment) >= MIN_SEGMENT_ROWS and segment[TARGET_COLUMN].nunique() == 2:
            proba = model.predict_proba(segment[FEATURE_COLUMNS])[:, 1]
            scores[str(value)] = float(roc_auc_score(segment[TARGET_COLUMN], proba))
    return scores


def guardrail_failures(
    candidate: Classifier, champion: Classifier | None, holdout: pd.DataFrame
) -> list[str]:
    """Garde-fous métier violés par le candidat ; liste vide si tout passe.

    Sans champion comparable (`champion` à None), seul le seuil absolu de précision
    s'applique.
    """
    failures = []

    precision = evaluate(candidate, holdout)["precision"]
    if precision < MIN_PRECISION:
        failures.append(f"précision {precision:.3f} < {MIN_PRECISION}")

    if champion is None:
        return failures

    for column in SEGMENT_COLUMNS:
        champion_scores = _segment_auc(champion, holdout, column)
        for value, score in _segment_auc(candidate, holdout, column).items():
            if value in champion_scores and champion_scores[value] - score > MAX_SEGMENT_AUC_DROP:
                failures.append(
                    f"{column}={value} : ROC AUC {score:.3f} contre {champion_scores[value]:.3f}"
                )

    shift = _positive_rate(candidate, holdout) - _positive_rate(champion, holdout)
    if abs(shift) > MAX_POSITIVE_RATE_SHIFT:
        failures.append(f"part d'éligibles décalée de {shift:+.1%}")

    return failures
