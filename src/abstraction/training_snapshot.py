"""Contrat des jeux d'entraînement historisés (snapshots), pour des entraînements reproductibles."""

from abc import ABC, abstractmethod

import pandas as pd


class TrainingSnapshotStore(ABC):
    """Jeux d'entraînement historisés : chaque écriture crée une version relisible (ADR-0001)."""

    @abstractmethod
    def write(self, orders: pd.DataFrame) -> int:
        """Remplace le jeu d'entraînement courant ; retourne le numéro de la nouvelle version."""

    @abstractmethod
    def read(self, version: int | None = None) -> pd.DataFrame:
        """Relit le jeu d'entraînement d'une version donnée (la plus récente par défaut)."""

    @abstractmethod
    def versions(self) -> list[int]:
        """Identifiants des versions disponibles, de la plus ancienne à la plus récente."""
