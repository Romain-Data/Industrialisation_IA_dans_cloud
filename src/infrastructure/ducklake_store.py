"""Snapshots d'entraînement dans DuckLake (ADR-0001).

Les données sont des fichiers Parquet (DATA_PATH), le catalogue est une base SQL :
SQLite en dev, PostgreSQL en prod. DuckDB ne sert que de moteur pour lire et écrire
le lac : les commandes elles-mêmes restent dans la base transactionnelle.
"""

from pathlib import Path

import duckdb
from sqlalchemy.engine import make_url

from src.abstraction.training_snapshot import TrainingSnapshotStore

TABLE = "commandes_entrainement"


def ducklake_catalog(catalog_url):
    """Convertit une URL SQLAlchemy en chaîne de catalogue DuckLake.

    sqlite:///chemin.sqlite                      -> sqlite:chemin.sqlite
    postgresql+psycopg://u:p@hote:5432/base      -> postgres:dbname=base host=hote ...
    """
    url = make_url(catalog_url)

    if url.drivername.startswith("sqlite"):
        return "sqlite", f"sqlite:{url.database}"

    if url.drivername.startswith("postgresql"):
        parts = {
            "dbname": url.database,
            "host": url.host,
            "port": url.port,
            "user": url.username,
            "password": url.password,
        }
        libpq = " ".join(f"{key}={value}" for key, value in parts.items() if value)
        return "postgres", f"postgres:{libpq}"

    raise ValueError(f"Catalogue DuckLake non supporté : {url.drivername}")


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class DuckLakeSnapshotStore(TrainingSnapshotStore):
    """Snapshots d'entraînement DuckLake : une écriture = une version relisible (time travel)."""
    def __init__(self, catalog_url, data_path):
        self._extension, self._catalog = ducklake_catalog(catalog_url)
        self._data_path = str(data_path).rstrip("/") + "/"

    def _connect(self):
        Path(self._data_path).mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect()
        # Extensions préinstallées dans l'image Docker ; téléchargées au premier usage en dev.
        for extension in ("ducklake", self._extension):
            connection.install_extension(extension)
            connection.load_extension(extension)
        connection.execute(
            f"ATTACH {_quote('ducklake:' + self._catalog)} AS lake "
            f"(DATA_PATH {_quote(self._data_path)})"
        )
        return connection

    def _table_exists(self, connection):
        return bool(
            connection.execute(
                "SELECT count(*) FROM duckdb_tables() "
                "WHERE database_name = 'lake' AND table_name = ?",
                [TABLE],
            ).fetchone()[0]
        )

    def write(self, orders):
        if orders.empty:
            raise ValueError("Aucune commande à historiser.")

        connection = self._connect()
        try:
            connection.register("orders_df", orders)
            if self._table_exists(connection):
                # Remplacement complet dans une transaction : un seul nouveau snapshot.
                connection.execute("BEGIN")
                connection.execute(f"DELETE FROM lake.{TABLE}")
                connection.execute(f"INSERT INTO lake.{TABLE} SELECT * FROM orders_df")
                connection.execute("COMMIT")
            else:
                connection.execute(f"CREATE TABLE lake.{TABLE} AS SELECT * FROM orders_df")

            return self._latest_version(connection)
        finally:
            connection.close()

    def read(self, version=None):
        connection = self._connect()
        try:
            if not self._table_exists(connection):
                raise LookupError("Aucun snapshot d'entraînement n'a encore été écrit.")

            at = f" AT (VERSION => {int(version)})" if version is not None else ""
            return connection.execute(f"SELECT * FROM lake.{TABLE}{at}").df()
        finally:
            connection.close()

    def versions(self):
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT snapshot_id FROM lake.snapshots() "
                "WHERE changes IS NOT NULL ORDER BY snapshot_id"
            ).fetchall()
            return [row[0] for row in rows]
        finally:
            connection.close()

    @staticmethod
    def _latest_version(connection):
        return connection.execute("SELECT max(snapshot_id) FROM lake.snapshots()").fetchone()[0]
