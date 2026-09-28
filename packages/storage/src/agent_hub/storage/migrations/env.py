"""Alembic environment of the storage package: migrations track ``agent_hub.storage.db.metadata``.

The config is built in code by ``agent_hub.storage.migration.alembic_config`` (there is no
``alembic.ini``), which puts the database URL in ``sqlalchemy.url``. SQLite cannot alter most
table properties in place, so migrations run in batch mode there.
"""

from alembic import context
from sqlalchemy import create_engine, pool

from agent_hub.storage.db import metadata

config = context.config


def database_url() -> str:
    """The config's ``sqlalchemy.url``, set by ``alembic_config``."""
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("no database URL: build the config with alembic_config")
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
