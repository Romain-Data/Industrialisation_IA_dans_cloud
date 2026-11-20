"""Collecte des données d'entraînement via un snapshot DuckLake (ADR-0001)."""

import pandas as pd

from src.abstraction.collect import Collect
from src.abstraction.order_store import OrderStore
from src.abstraction.training_snapshot import TrainingSnapshotStore

# En dessous, le découpage train/test et les métriques n'ont pas de sens.
MIN_LABELED_ORDERS = 50


class CollectDuckLake(Collect):
    """Fige les commandes étiquetées dans un nouveau snapshot, ou relit un snapshot existant.

    Le numéro du snapshot utilisé est exposé dans `tracking_params` pour être
    enregistré avec le run MLflow : l'entraînement est ainsi reproductible.
    """

    def __init__(
        self,
        order_store: OrderStore,
        snapshot_store: TrainingSnapshotStore,
        version: int | None = None,
    ) -> None:
        self._order_store = order_store
        self._snapshot_store = snapshot_store
        self._version = version
        self.tracking_params: dict[str, int] = {}

    def collect_data(self) -> pd.DataFrame:
        version = self._version

        if version is None:
            labeled = self._order_store.export_labeled_orders()
            if len(labeled) < MIN_LABELED_ORDERS:
                raise ValueError(
                    f"{len(labeled)} commandes avec un résultat connu : "
                    f"il en faut au moins {MIN_LABELED_ORDERS} pour entraîner."
                )
            version = self._snapshot_store.write(labeled)

        orders = self._snapshot_store.read(version)
        self.tracking_params = {"data_source": "ducklake", "ducklake_snapshot": version}
        return orders
