"""``brain.memory``: personal memory in ``brain/auto/workspace/`` stays out of git (AGH-48).

Each developer's personal memory lives in the hub's ``brain/auto/workspace/`` (gitignored but
for its ``.gitkeep``), so it must never be committed with the team's brain. Two checks:

- (a) On a listing git made (``HubFiles.listed_by_git``), each listed path under the folder
  other than its ``.gitkeep`` is tracked or not ignored: one warning at the path, in listing
  order, at most 10, then one ``N more … besides the 10 shown`` warning at the folder (the
  report sorts it before the paths, so it reads alone). A walked listing (no ``.git``)
  lists every file on disk, ignored or not, so (a) is skipped there (D-walk).
- (b) ``.gitignore`` has a line that ignores the folder (D-ignore): ``brain/auto/workspace``,
  ``brain/auto`` or ``brain``, with or without one leading ``/`` and one trailing ``/``, ``/*``
  or ``/**``, trailing spaces and a leading byte order mark dropped (as git drops them); a
  comment or ``!`` line never covers. Else one warning at ``.gitignore``. This matches lines,
  it does not run git's matcher: only the root ``.gitignore`` is read, so a nested one (as
  ``brain/.gitignore``) that ignores the folder still warns. ``.gitignore`` is read with the
  listing, not as a fixed path (plan E7): it is absent when not listed and not in the entries,
  so an untracked ``.gitignore`` that ignores itself reads as absent; absent gives one warning
  at ``.`` only when every fixed path was read. A link or a file that is not UTF-8 text gives
  none (D-out).

A hub listing problem gives nothing: the runner reports it once (AC-48.10). The rule never
looks at a memory file's content and shows only paths and counts; ``.gitignore`` lines are
only compared (AC-48.11). Paths go in the finding's ``path``, which the report escapes.
"""

from collections.abc import Iterator
from typing import Final

from agent_hub.core.doctor.config_lint import file_text, text_lines
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, HubFiles
from agent_hub.core.hub_config.doctor_rules import BRAIN_MEMORY_RULE, RULE_MODULES, Severity

FOLDER: Final = "brain/auto/workspace/"
GITKEEP: Final = "brain/auto/workspace/.gitkeep"
GITIGNORE: Final = ".gitignore"
MAX_PATH_FINDINGS: Final = 10
COVERING: Final = frozenset({"brain/auto/workspace", "brain/auto", "brain"})
LISTED_MESSAGE: Final = "personal memory file is tracked or not ignored by git"
IGNORE_MESSAGE: Final = ".gitignore has no line ignoring brain/auto/workspace/ (personal memory)"
FIX: Final = (
    "add brain/auto/workspace/* and !brain/auto/workspace/.gitkeep to .gitignore;"
    ' if a memory file was committed, see "Personal memory (existing hubs)" in the agent-hub'
    " README first"
)

# The trailing forms a covering line may end with, longest first: one is dropped.
_TRAILERS: Final = ("/**", "/*", "/")
_BOM: Final = "\ufeff"


def _brain_memory(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    hub = snapshot.hub
    if hub.problem is not None:
        return
    if hub.listed_by_git:
        yield from _listed_memory(hub)
    yield from _ignore_finding(hub)


def _listed_memory(hub: HubFiles) -> Iterator[Finding]:
    """(a): one warning per listed memory path, at most 10, then one ``N more`` at the folder."""
    count = 0
    for path in hub.listed:
        if not path.startswith(FOLDER) or path == GITKEEP:
            continue
        count += 1
        if count <= MAX_PATH_FINDINGS:
            yield BRAIN_MEMORY.finding(path=path, message=LISTED_MESSAGE, fix=FIX)
    more = count - MAX_PATH_FINDINGS
    if more > 0:
        files = "file is" if more == 1 else "files are"
        yield BRAIN_MEMORY.finding(
            path=FOLDER,
            message=f"{more} more personal memory {files} tracked or not ignored by git"
            f" besides the {MAX_PATH_FINDINGS} shown",
            fix=FIX,
        )


def _ignore_finding(hub: HubFiles) -> Iterator[Finding]:
    """(b): a ``.gitignore`` that is absent or has no line covering the folder."""
    entry = hub.entries.get(GITIGNORE)
    if GITIGNORE not in hub.listed and entry is None:
        # An absent path may be one the read never reached (``paths_read``).
        if hub.paths_read:
            yield BRAIN_MEMORY.finding(path=".", message=IGNORE_MESSAGE, fix=FIX)
        return
    text = file_text(entry)
    if not isinstance(text, str):
        return
    # Git ignores a UTF-8 byte order mark before the first pattern.
    if not any(_covers(line) for line in text_lines(text.removeprefix(_BOM))):
        yield BRAIN_MEMORY.finding(path=GITIGNORE, message=IGNORE_MESSAGE, fix=FIX)


def _covers(line: str) -> bool:
    """Whether one ``.gitignore`` line ignores the folder (``\\r`` is dropped by ``text_lines``)."""
    pattern = line.rstrip(" ")
    if pattern.startswith(("#", "!")):
        return False
    pattern = pattern.removeprefix("/")
    for trailer in _TRAILERS:
        if pattern.endswith(trailer):
            pattern = pattern.removesuffix(trailer)
            break
    return pattern in COVERING


BRAIN_MEMORY: Final = Rule(
    id=BRAIN_MEMORY_RULE,
    severity=Severity.WARNING,
    summary="personal memory in brain/auto/workspace/ stays out of git",
    module=RULE_MODULES.get(BRAIN_MEMORY_RULE),
    reads=frozenset({Read.HUB_LISTING}),
    check=_brain_memory,
)
