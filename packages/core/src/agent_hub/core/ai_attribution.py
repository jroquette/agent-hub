"""The marks of AI attribution (hub ``AGENTS.md`` rule 1): an AI co-author trailer, a "Generated
with Claude" line, the robot emoji.

The same marks as the hub guard's ``AI_ATTRIBUTION`` (generator's ``guard.py.tmpl``, a stdlib hook
that cannot import this), ``co-authored-by:\\s*[^\\n]*(claude|anthropic|openai|copilot|\\bai\\b)|
generated with \\[?claude|🤖`` ignoring case, found in time linear in the text: the guard's
``\\s*[^\\n]*`` rescans the rest of a line from each tag and each blank, so here each tag's line is
searched once.
"""

import re
from typing import Final

# A co-author tag and its blanks, which end on the line the guard's ``[^\n]*`` searches.
_TAG: Final = re.compile(r"co-authored-by:\s*", re.IGNORECASE)
# What a co-author line must name, after the tag's blanks, on the line where they end.
_AI_CO_AUTHOR: Final = re.compile(r"claude|anthropic|openai|copilot|\bai\b", re.IGNORECASE)
# The marks found by one search.
_AI_GENERATED: Final = re.compile(r"generated with \[?claude|\U0001f916", re.IGNORECASE)


def carries_ai_attribution(text: str) -> bool:
    """Whether ``text`` carries an AI attribution mark, as the hub guard's pattern finds it.

    A tag's blanks (``\\s*``, across lines too) end on some line; that line, from there, must
    name an AI. A later tag whose line was already searched adds nothing: its rest is part of it.
    """
    if _AI_GENERATED.search(text) is not None:
        return True
    searched_to = -1
    for tag in _TAG.finditer(text):
        line_start = tag.end()
        line_end = text.find("\n", line_start)
        end = len(text) if line_end == -1 else line_end
        if end <= searched_to:
            continue
        if _AI_CO_AUTHOR.search(text, line_start, end) is not None:
            return True
        searched_to = end
    return False
