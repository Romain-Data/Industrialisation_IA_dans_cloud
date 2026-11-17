"""Contrat de collecte : d'où viennent les commandes étiquetées qui servent à l'entraînement."""

from abc import ABC, abstractmethod

import pandas as pd


class Collect(ABC):
    """Source de commandes étiquetées (synthétique, DuckLake...) pour l'entraînement."""

    @abstractmethod
    def collect_data(self) -> pd.DataFrame:
        """Retourne un lot de commandes brutes """
