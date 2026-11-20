"""Contrat minimal d'un modèle de classification, indépendant de la bibliothèque de ML.

Le domaine (évaluation, garde-fous) et le service n'utilisent qu'une méthode du modèle :
`predict_proba`. Ce protocole la décrit sans importer scikit-learn ; un pipeline
scikit-learn le respecte sans en hériter (typage structurel).
"""

from typing import Protocol

import numpy as np
import pandas as pd


class Classifier(Protocol):
    """Modèle qui donne, pour chaque ligne, la probabilité de chaque classe."""

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:  # pylint: disable=invalid-name  (convention scikit-learn)
        """Probabilités des classes, une ligne par commande (colonne 1 : éligible)."""
        ...
