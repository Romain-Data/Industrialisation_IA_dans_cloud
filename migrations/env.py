from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from src.config import DATABASE_URL
from src.infrastructure.order_store import Base

config = context.config

# Le code applicatif qui lance Alembic (tests, démarrage) garde sa propre
# configuration de logs : il désactive ce réglage via config.attributes.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    """URL passée par le code appelant, sinon variable DATABASE_URL (ADR-0001)."""
    return config.get_main_option("sqlalchemy.url") or DATABASE_URL


def run_migrations_offline() -> None:
    """Génère le SQL sans se connecter (alembic upgrade head --sql)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite gère mal ALTER TABLE : le mode batch recrée la table.
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
