"""Pipeline d'entraînement : collecte, validation, nettoyage, entraînement, promotion."""

from src.abstraction.collect import Collect
from src.config import (
    CHAMPION_ALIAS,
    DATABASE_URL,
    DUCKLAKE_CATALOG_URL,
    DUCKLAKE_DATA_PATH,
    TRAINING_SOURCE,
)
from src.domain.cleaning import clean_orders_data
from src.domain.evaluation import split_holdout
from src.domain.validation import validate_columns, validate_dataset
from src.training.registry import promote_if_better
from src.training.train import train_model


def run_training(collector: Collect):
    """Collecte, nettoie puis valide les données, entraîne et promeut le modèle.

    La structure est vérifiée avant le nettoyage ; le nettoyage écarte les lignes
    invalides (le nombre est enregistré dans le run) ; la validation stricte vient après.
    """
    raw_orders = collector.collect_data()
    validate_columns(raw_orders)

    orders_clean = clean_orders_data(raw_orders)
    validate_dataset(orders_clean)
    dropped = len(raw_orders) - len(orders_clean)
    if dropped:
        print(f"Nettoyage : {dropped} lignes écartées sur {len(raw_orders)}.")

    params = {**(getattr(collector, "tracking_params", None) or {}), "rows_dropped": dropped}
    # Même jeu d'évaluation pour le candidat et le champion (src/domain/evaluation.py).
    train, holdout = split_holdout(orders_clean)
    model_pipeline, metrics, run_id = train_model(train, holdout, params=params)
    promoted = promote_if_better(run_id, holdout)

    print("Entraînement terminé.")
    print(f"Run MLflow : {run_id}")
    print(f"Alias {CHAMPION_ALIAS} {'déplacé' if promoted else 'inchangé'}")
    print(f"Métriques : {metrics}")

    return model_pipeline, metrics, run_id


def build_collector(source=None):
    """Choisit la source d'entraînement (variable TRAINING_SOURCE)."""
    source = source or TRAINING_SOURCE

    if source == "synthetic":
        from src.infrastructure.dev.collect import CollectDev

        return CollectDev()

    if source == "ducklake":
        from src.infrastructure.collect_ducklake import CollectDuckLake
        from src.infrastructure.ducklake_store import DuckLakeSnapshotStore
        from src.infrastructure.order_store import SqlAlchemyOrderStore

        return CollectDuckLake(
            SqlAlchemyOrderStore(DATABASE_URL),
            DuckLakeSnapshotStore(DUCKLAKE_CATALOG_URL, DUCKLAKE_DATA_PATH),
        )

    raise ValueError(f"TRAINING_SOURCE inconnue : {source} (synthetic ou ducklake)")


if __name__ == "__main__":
    run_training(build_collector())
