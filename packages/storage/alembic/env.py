"""Alembic environment of the storage package: migrations track ``agent_hub.storage.db.metadata``.

The database URL comes from ``-x db_url=...`` on the command line, else from the config's
``sqlalchemy.url`` (tests set it with ``Config.set_main_option``). SQLite cannot alter most
table properties in place, so migrations run in batch mode there.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from agent_hub.storage.db import metadata

config = context.config

if config.config_file_name is not None:
    # Keep the caller's loggers (pytest's, for one) working after Alembic configures its own.
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def database_url() -> str:
    """The URL passed with ``-x db_url=...``, else the config's ``sqlalchemy.url``."""
    url = context.get_x_argument(as_dictionary=True).get("db_url")
    if url is None:
        url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("no database URL: pass -x db_url=... or set sqlalchemy.url")
    return url


def run_migrations_offline() -> None:
    """Emit the migration SQL for the URL's dialect without connecting."""
    url = database_url()
    context.configure(
        url=url,
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply the migrations."""
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
