import pytest

from src.infrastructure.bootstrap import ensure_database


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///orders.db",
        "http://mlflow.example.com:5000",
        "file:///tmp/mlruns",
        "postgresql+psycopg://user:pwd@host",  # pas de nom de base
    ],
)
def test_ensure_database_ignores_non_postgres_urls(url):
    assert ensure_database(url) is False
