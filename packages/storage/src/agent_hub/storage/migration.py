"""The Alembic configuration, built in code, and the migrations' command line for contributors.

The scripts and revisions live in the installed package (``migrations/``), so an installed hub
can create and upgrade its own database; there is no ``alembic.ini``. ``make migrations``, the
tests and ``hub collect`` all build their config with ``alembic_config``.

Contributors run the usual Alembic sub-commands through ``main``, with the database URL passed
as ``-x db_url=...`` (default: an in-memory database, so nothing touches the real hub database)::

    uv run --locked --all-packages python -m agent_hub.storage.migration \\
        -x db_url=sqlite:///<file> upgrade head
"""

from argparse import Namespace
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import CommandLine, Config
from alembic.util import CommandError
from sqlalchemy.exc import SQLAlchemyError

from agent_hub.storage.engine import create_sqlite_engine
from agent_hub.storage.errors import MigrationError, describe_database_error

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
DEFAULT_DATABASE_URL = "sqlite://"
PROG = "python -m agent_hub.storage.migration"


def alembic_config(database_url: str, *, cmd_opts: Namespace | None = None) -> Config:
    """An Alembic config for the packaged migrations, pointed at ``database_url``."""
    config = Config(cmd_opts=cmd_opts)
    config.set_main_option("script_location", _escape(str(MIGRATIONS_DIR)))
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", _escape(database_url))
    return config


def upgrade_to_head(path: Path) -> None:
    """Upgrade the SQLite file at ``path`` to the latest revision; a no-op when already there.

    The upgrade runs on a ``write_lock`` connection (``BEGIN IMMEDIATE``), so when several
    processes open a fresh file together, one migrates and the others then find it at head.
    """
    engine = create_sqlite_engine(path)
    try:
        with (
            engine.connect().execution_options(write_lock=True) as connection,
            connection.begin(),
        ):
            config = alembic_config(str(engine.url))
            # env.py migrates on this connection instead of opening its own (Alembic's
            # "sharing a connection" recipe); the URL above is then only informational.
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    except (CommandError, SQLAlchemyError) as error:
        msg = f"cannot upgrade the database to the latest schema: {describe_database_error(error)}"
        raise MigrationError(msg) from error
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    """Run an Alembic sub-command (``upgrade``, ``check``, ``revision``...) for contributors."""
    cli = CommandLine(prog=PROG)
    options = cli.parser.parse_args(argv)
    if not hasattr(options, "cmd"):
        cli.parser.error("too few arguments")
    config = alembic_config(_database_url(options), cmd_opts=options)
    # New revisions come out formatted like the rest of the repo (only here, never for users).
    config.set_section_option("post_write_hooks", "hooks", "ruff_format")
    config.set_section_option("post_write_hooks", "ruff_format.type", "module")
    config.set_section_option("post_write_hooks", "ruff_format.module", "ruff")
    config.set_section_option(
        "post_write_hooks", "ruff_format.options", "format REVISION_SCRIPT_FILENAME"
    )
    cli.run_cmd(config, options)


def _database_url(options: Namespace) -> str:
    x_arguments: list[str] = options.x or []
    for argument in x_arguments:
        key, _, value = argument.partition("=")
        if key == "db_url":
            return value
    return DEFAULT_DATABASE_URL


def _escape(value: str) -> str:
    # Config options go through configparser interpolation, where "%" starts a reference.
    return value.replace("%", "%%")


if __name__ == "__main__":
    main()
