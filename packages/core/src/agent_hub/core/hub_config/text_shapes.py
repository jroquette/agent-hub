"""Text shapes that ``model.py`` and ``environments.py`` share (project-config.md).

A module of its own, so ``environments.py`` needs nothing of ``model.py``, which imports it.
"""

from typing import Final

# Free text still lands in files and commands, so a control character is never part of it.
FREE_TEXT_PATTERN: Final = r"^[^\x00-\x1f\x7f]+$"

# Rendered values (project-config.md): values that land in shell, Make or YAML text. Pydantic's
# Rust regex has no look-around, and ``[0-9]`` is spelled out because ``\d`` takes any digit.
# A safe segment: no leading ``-`` or ``.`` (an option or a hidden path), no ``..``, no trailing
# punctuation. The separator class leaves out ``_``, already a segment character: the hooks'
# reader copies this pattern into Python's ``re``, which backtracks exponentially on an overlap.
SAFE_SEGMENT: Final = r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*"
