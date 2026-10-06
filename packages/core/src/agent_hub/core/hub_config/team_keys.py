"""The hub's tracker team keys: the key an issue id or worktree name belongs to, and their text."""

from collections.abc import Sequence


def team_of(identifier: str, teams: Sequence[str]) -> str | None:
    """The configured key whose lowercase equals the text before ``identifier``'s first ``-``.

    The whole segment is compared, so keys sharing a prefix (``AP``, ``APP``) never match each
    other's ids; case is ignored on both sides. None when ``identifier`` has no ``-``, its
    segment is not ASCII (``str.lower`` folds some other letters to ASCII, e.g. the Kelvin sign
    to ``k``) or no key matches.
    """
    segment, dash, _ = identifier.partition("-")
    if not dash or not segment.isascii():
        return None
    folded = segment.lower()
    return next((team for team in teams if team.lower() == folded), None)


def teams_text(teams: Sequence[str]) -> str:
    """The keys in config order, joined for a message: ``APP, OPS``."""
    return ", ".join(teams)


def team_segment(teams: Sequence[str]) -> str:
    """The team part of a name shape: ``dem`` for one team, ``<app|ops>`` for several."""
    lowered = [team.lower() for team in teams]
    if len(lowered) == 1:
        return lowered[0]
    return f"<{'|'.join(lowered)}>"
