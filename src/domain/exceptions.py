"""Erreurs du domaine.

Les implémentations d'infrastructure traduisent les erreurs de leur bibliothèque
(pymongo, SQLAlchemy...) en ces erreurs : l'application ne connaît pas
l'infrastructure, et les messages techniques ne fuient pas vers les clients (ADR-0005).
"""


class OrderRepositoryError(Exception):
    """Erreur d'accès à un dépôt de commandes."""


class RepositoryUnavailableError(OrderRepositoryError):
    """Le système qui stocke les commandes est injoignable."""


class ReadOnlyRepositoryError(OrderRepositoryError):
    """Écriture refusée : le dépôt est en lecture seule (ERP, ADR-0007)."""
