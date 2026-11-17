"""Pilotage d'Alembic depuis le code : migrations du schéma et révision courante."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url=None):
    """Configuration Alembic, éventuellement pointée sur une autre base que DATABASE_URL."""
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["configure_logger"] = False

    if database_url:
        # '%' est un caractère spécial pour le parseur de configuration.
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

    return config


def upgrade_to_head(database_url=None):
    """Applique toutes les migrations (équivalent de `alembic upgrade head`)."""
    command.upgrade(alembic_config(database_url), "head")


def head_revision():
    """Dernière révision connue du code."""
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine):
    """Révision appliquée à la base, ou None si aucune migration n'a été jouée."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()
