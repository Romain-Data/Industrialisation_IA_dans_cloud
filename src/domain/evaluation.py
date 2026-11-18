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

from src.domain.features import FEATURE_COLUMNS, TARGET_COLUMN

ID_COLUMN = "order_id"
# Part des commandes réservées à l'évaluation (en pourcentage).
HOLDOUT_PERCENT = 20
# Enregistré avec chaque run : deux scores ne sont comparables qu'avec le même protocole.
EVALUATION_PROTOCOL = f"sha256-{ID_COLUMN}-{HOLDOUT_PERCENT}pct"


def is_holdout(order_id):
    """Vrai si la commande appartient au jeu d'évaluation (stable dans le temps)."""
    digest = hashlib.sha256(str(order_id).encode()).hexdigest()
    return int(digest[:8], 16) % 100 < HOLDOUT_PERCENT


def split_holdout(df):
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


def evaluate(model, holdout: pd.DataFrame):
    """Métriques d'un modèle sur le jeu d'évaluation."""
    y_true = holdout[TARGET_COLUMN]
    y_proba = model.predict_proba(holdout[FEATURE_COLUMNS])[:, 1]
    y_pred = (y_proba >= 0.5).astype(int)
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1_score": f1_score(y_true, y_pred, zero_division=0),
        "roc_auc": roc_auc_score(y_true, y_proba),
    }
