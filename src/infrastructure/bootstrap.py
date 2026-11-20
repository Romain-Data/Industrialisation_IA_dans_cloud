"""Prépare les bases PostgreSQL au démarrage du conteneur (ADR-0003).

Un seul conteneur PostgreSQL héberge des bases distinctes pour les commandes, le
registre MLflow et le catalogue DuckLake. Coolify ne crée que la première : les
autres sont créées ici si elles n'existent pas. Sans effet pour SQLite ou un serveur MLflow distant.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from src.config import DATABASE_URL, DUCKLAKE_CATALOG_URL, MLFLOW_TRACKING_URI


def ensure_database(url: str) -> bool:
    """Crée la base PostgreSQL de l'URL si besoin. Retourne True si elle a été créée."""
    try:
        parsed = make_url(url)
    except ArgumentError:
        return False

    if not parsed.drivername.startswith("postgresql") or not parsed.database:
        return False

    # Connexion à la base d'administration : la base cible n'existe peut-être pas.
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": parsed.database},
            ).scalar()

            if exists:
                return False

            quoted = parsed.database.replace('"', '""')
            connection.execute(text(f'CREATE DATABASE "{quoted}"'))
            return True
    finally:
        admin.dispose()


def main() -> None:
    """Crée les bases PostgreSQL manquantes (commandes, MLflow, DuckLake) au démarrage."""
    for url in (DATABASE_URL, MLFLOW_TRACKING_URI, DUCKLAKE_CATALOG_URL):
        if ensure_database(url):
            print(f"Base créée : {make_url(url).database}")


if __name__ == "__main__":
    main()
