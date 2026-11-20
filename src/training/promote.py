"""Décision humaine sur le modèle servi (ADR-0010) : valider le challenger, ou revenir en arrière.

Usage (dans un conteneur qui voit le registre, par exemple l'orchestrateur) :
    python -m src.training.promote               # le challenger devient champion
    python -m src.training.promote --version 3   # rollback : la version 3 redevient champion

Avant de valider, comparer les deux runs dans MLflow : le tag `guardrail_failures`
du challenger indique quel garde-fou métier il a violé.
"""

import argparse

from src.training.registry import promote_version


def main() -> None:
    """Point d'entrée en ligne de commande."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--version", type=int, help="version à servir (défaut : le challenger)")
    args = parser.parse_args()
    version = promote_version(args.version)
    print(f"Version {version} promue champion ; l'API la chargera d'elle-même.")


if __name__ == "__main__":
    main()
