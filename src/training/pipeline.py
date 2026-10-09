from src.abstraction.collect import Collect
from src.config import CHAMPION_ALIAS
from src.domain.cleaning import clean_orders_data
from src.domain.validation import validate_dataset
from src.training.registry import promote_if_better
from src.training.train import train_model


def run_training(collector: Collect):
    """Collecte, valide, nettoie les données, entraîne puis sauvegarde le modèle."""
    raw_orders = collector.collect_data()
    validate_dataset(raw_orders)

    orders_clean = clean_orders_data(raw_orders)
    validate_dataset(orders_clean)

    model_pipeline, metrics, run_id = train_model(orders_clean)
    promoted = promote_if_better(run_id)

    print("Entraînement terminé.")
    print(f"Run MLflow : {run_id}")
    print(f"Alias {CHAMPION_ALIAS} {'déplacé' if promoted else 'inchangé'}")
    print(f"Métriques : {metrics}")

    return model_pipeline, metrics, run_id


if __name__ == "__main__":
    from src.infrastructure.dev.collect import CollectDev

    run_training(CollectDev())
