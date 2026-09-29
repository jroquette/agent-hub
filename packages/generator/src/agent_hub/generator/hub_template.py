"""The ``@@`` template renderer.

``string.Template`` with ``@@`` as the delimiter, so ``$`` text stays verbatim. Rendering is
strict: an unknown or malformed placeholder raises ``TemplateError``, never a partial result.
"""

import string
from collections.abc import Mapping

from agent_hub.generator.errors import TemplateError


class HubTemplate(string.Template):
    """Placeholders are ``@@name`` or ``@@{name}``; ``@@@@`` renders a literal ``@@``."""

    delimiter = "@@"


def render_template(text: str, mapping: Mapping[str, str], *, source: str) -> str:
    """Substitute every placeholder of ``text`` from ``mapping``.

    ``source`` names the template in errors. Strict ``substitute`` only: nothing is left
    unrendered silently.
    """
    try:
        return HubTemplate(text).substitute(mapping)
    except KeyError as error:
        raise TemplateError(
            source=source, placeholder=str(error.args[0]), reason="unknown placeholder"
        ) from error
    except ValueError as error:
        raise _malformed(text, source) from error


def _malformed(text: str, source: str) -> TemplateError:
    """Build the error for the first malformed ``@@`` of ``text``, at its 1-based line and column.

    Called only after ``substitute`` raised ``ValueError``, so ``text`` holds an ``invalid`` match.
    """
    invalid = next(m for m in HubTemplate.pattern.finditer(text) if m.group("invalid") is not None)
    start = invalid.start()
    line = text.count("\n", 0, start) + 1
    column = start - (text.rfind("\n", 0, start) + 1) + 1
    return TemplateError(
        source=source,
        placeholder=text[start:].split(maxsplit=1)[0],  # the "@@" and the non-blank text after it
        reason=f"malformed placeholder at line {line}, column {column}",
    )
