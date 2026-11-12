"""The YAML check of ``hub doctor --staged`` (ADR 0061): what ``check-yaml`` did, no download.

One document, read with PyYAML's safe loader: a second document, a custom tag or a syntax error
is a problem, its first line given back.
"""

from typing import Final

import yaml

from agent_hub.core.hub_config.versions import cut_echo

_NESTED: Final = "nested too deep"


def yaml_problem(text: str) -> str | None:
    """Why ``text`` is not one safe YAML document, else ``None``."""
    try:
        yaml.safe_load(text)
    except RecursionError:
        return _NESTED
    except yaml.YAMLError as error:
        lines = [line.strip() for line in str(error).splitlines() if line.strip()]
        return cut_echo(" ".join(lines[:2])) if lines else type(error).__name__
    return None
