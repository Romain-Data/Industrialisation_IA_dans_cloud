"""Accès, pour les tests, au code du simulateur ERP fourni par le cours.

Le simulateur importe ses modules à plat (`from config import ...`) et vit hors du
paquet `src` : on charge ses fichiers directement. Les tests utilisent ainsi les
mêmes commandes et la même écriture MongoDB que l'ERP simulé.
"""

import importlib.util
import sys
from datetime import date
from pathlib import Path

ERP_SOURCES = Path(__file__).parent.parent / "erp_simulator" / "src" / "erp_simulator"
TODAY = date(2026, 11, 17)


def load_erp_module(name):
    """Charge un module du simulateur ERP (`generator`, `storage`...)."""
    module_name = f"erp_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, ERP_SOURCES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def erp_orders(count, first_sequence=1):
    """Commandes ERP récentes (schéma complet, depuis 2023), comme dans MongoDB."""
    generator = load_erp_module("generator").OrderGenerator()
    return generator.recent_history(count, TODAY, first_sequence=first_sequence)
