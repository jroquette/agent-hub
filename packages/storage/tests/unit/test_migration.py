from pathlib import Path

from agent_hub.storage.migration import alembic_config


def test_points_at_packaged_scripts_when_config_built() -> None:
    config = alembic_config("sqlite://")

    scripts = Path(config.get_main_option("script_location") or "")

    assert (scripts / "env.py").is_file()
    assert (scripts / "script.py.mako").is_file()
    assert (scripts / "versions" / "0001_baseline.py").is_file()


def test_escapes_percent_when_url_contains_one() -> None:
    url = "sqlite:////tmp/100%25 full/agent-hub.db"

    config = alembic_config(url)

    assert config.get_main_option("sqlalchemy.url") == url
