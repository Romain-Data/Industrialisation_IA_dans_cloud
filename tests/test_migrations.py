import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext

from src.infrastructure.migrations import (
    alembic_config,
    current_revision,
    head_revision,
    upgrade_to_head,
)
from src.infrastructure.order_store import Base, SqlAlchemyOrderStore


def make_url(tmp_path):
    return f"sqlite:///{tmp_path / 'migrations.db'}"


def test_upgrade_creates_expected_tables(tmp_path):
    url = make_url(tmp_path)

    upgrade_to_head(url)

    tables = set(sa.inspect(sa.create_engine(url)).get_table_names())
    assert {"commandes", "predictions", "alembic_version"} <= tables


def test_database_is_at_head_after_upgrade(tmp_path):
    url = make_url(tmp_path)
    engine = sa.create_engine(url)
    assert current_revision(engine) is None

    upgrade_to_head(url)

    assert current_revision(engine) == head_revision()


def test_upgrade_is_idempotent(tmp_path):
    url = make_url(tmp_path)

    upgrade_to_head(url)
    upgrade_to_head(url)

    assert SqlAlchemyOrderStore(url).schema_is_current() is True


def test_models_and_migrations_are_in_sync(tmp_path):
    """Échoue si un modèle SQLAlchemy a changé sans nouvelle migration."""
    url = make_url(tmp_path)
    upgrade_to_head(url)

    with sa.create_engine(url).connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_downgrade_removes_tables(tmp_path):
    url = make_url(tmp_path)
    upgrade_to_head(url)

    command.downgrade(alembic_config(url), "base")

    tables = set(sa.inspect(sa.create_engine(url)).get_table_names())
    assert "commandes" not in tables and "predictions" not in tables


def test_unmigrated_database_is_not_current(tmp_path):
    assert SqlAlchemyOrderStore(make_url(tmp_path)).schema_is_current() is False
