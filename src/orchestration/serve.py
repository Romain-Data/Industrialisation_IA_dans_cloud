"""Processus d'exécution des flows : déclare les déploiements et exécute leurs runs (ADR-0009).

`serve()` : ce processus contient le code et exécute lui-même les runs planifiés par le
serveur Prefect (pas de work pool ni de worker séparé). Lancé par le mode `orchestrator`
de l'image Docker, avec PREFECT_API_URL pointant vers le serveur Prefect.
"""

from prefect import serve

from src.config import ERP_PIPELINE_CRON
from src.orchestration.flows import erp_pipeline


def main():
    """Déploie le flow ERP (planifié et manuel) et exécute ses runs."""
    serve(
        erp_pipeline.to_deployment(
            name="horaire",
            cron=ERP_PIPELINE_CRON,
            description="Import ERP, puis réentraînement s'il y a assez de nouvelles données.",
        ),
        erp_pipeline.to_deployment(
            name="reentrainement-force",
            parameters={"force_retrain": True},
            description="À lancer à la main : import ERP puis réentraînement systématique.",
        ),
    )


if __name__ == "__main__":
    main()
