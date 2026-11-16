"""``hub digest --input PATH``: the owner digest, from the session's input file and the hub's
local claims (AGH-811, plan D-4).

Neither the tracker port nor the sandbox lets the CLI read the claim comments or reach GitHub, so
the session writes one JSON file with its own tools (``DigestInput``) and this command decides
from it. The file is read as a regular file, never through a link, of at most
``MAX_INPUT_BYTES``; anything else, or a file that is not one ``DigestInput``, exits 2 with one
line ``hub digest: cannot read <path>: <why>`` and writes nothing. The local claims are
``.agent-runs/claims/<ticket>.json``, read as ``hub claim`` reads them (no link, at most
``MAX_CLAIM_BYTES``, a ``Claim`` for that ticket); an unreadable one is skipped and named on
stderr.

The digest is built at the clock's now (``build_digest``), written to ``.hub-cache/digest.json``
(mode 0600, replaced atomically, for ``hub brief``) and printed as
``digest_lines(digest, limit=LIMIT)``, the tracker comment's body. No network call is made.

Exit codes: 0 when printed, 1 when the cache cannot be written, 2 for a bad argument or input.
"""

import errno
import os
import stat
from pathlib import Path
from typing import Annotated, Final

import typer
from pydantic import ValidationError

from agent_hub.cli.claim_command import CLAIMS_FOLDER, MAX_CLAIM_BYTES
from agent_hub.cli.hub_cache import write_hub_cache
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.cli.workflow_runs import SystemClock
from agent_hub.core.claims.claim import Claim
from agent_hub.core.workspace.digest import DigestInput, build_digest, digest_lines

COMMAND: Final = "digest"
CACHE_NAME: Final = "digest.json"
CACHE_MODE: Final = 0o600
# The input file is at most this many bytes.
MAX_INPUT_BYTES: Final = 1024 * 1024
# Items printed per section.
LIMIT: Final = 10
BAD_INPUT_EXIT: Final = 2
_NO_LINK: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class _UnreadableError(Exception):
    """Why a file cannot be read, in a few words."""


def digest(
    *,
    input_path: Annotated[
        str,
        typer.Option(
            "--input",
            metavar="PATH",
            help="The session's JSON file: the tickets and pull requests to decide from.",
            show_default=False,
        ),
    ],
) -> None:
    """Print and cache the owner digest from the session's file and the local claims.

    The file is one JSON object of at most 1 MiB: version 1, read_at (a time with its zone),
    tickets (only the team's In Progress and In Review ones, at most 200: id, title, state,
    url, and claim, null or session, link, live, question, asked_at, title) and prs (at most
    200: repo, number, title, url, branch, draft, updated_at, mergeable_state, checks as counts
    by conclusion, unresolved_threads). A local claim counts as live only while its last
    activity is under 24 hours old, pid or not. It writes .hub-cache/digest.json for hub brief
    and makes no network call.
    """
    source = _input_or_exit(input_path)
    root = hub_root_or_exit(os.environ, command=COMMAND)
    claims = _local_claims(root)
    built = build_digest(source, claims, SystemClock().now())
    write_hub_cache(root, CACHE_NAME, built.model_dump_json().encode(), mode=CACHE_MODE)
    for line in digest_lines(built, limit=LIMIT):
        typer.echo(line)


def _input_or_exit(given: str) -> DigestInput:
    """The input file as a ``DigestInput``, or exit 2 with one stderr line naming why not."""
    try:
        raw = _bounded_read(Path(given), MAX_INPUT_BYTES)
        try:
            return DigestInput.model_validate_json(raw)
        except ValidationError as error:
            raise _UnreadableError(_first_problem(error)) from None
    except _UnreadableError as error:
        typer.echo(shown_text(f"hub {COMMAND}: cannot read {shown_path(given)}: {error}"), err=True)
        raise typer.Exit(BAD_INPUT_EXIT) from None


def _first_problem(error: ValidationError) -> str:
    problems = error.errors(include_url=False, include_input=False)
    first = problems[0]
    where = ".".join(str(part) for part in first["loc"])
    more = f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""
    shown = f"{where}: {first['msg']}" if where else first["msg"]
    return f"it is not a digest input: {shown}{more}"


def _local_claims(root: Path) -> tuple[Claim, ...]:
    """Every readable claim file of the hub; each unreadable one is named on stderr and skipped."""
    folder = root.joinpath(*CLAIMS_FOLDER)
    try:
        names = sorted(
            entry.name
            for entry in os.scandir(folder)
            if entry.name.endswith(".json") and not entry.name.startswith(".")
        )
    except OSError:
        return ()
    claims: list[Claim] = []
    for name in names:
        path = folder / name
        try:
            claims.append(_claim(path, name.removesuffix(".json")))
        except _UnreadableError as error:
            typer.echo(
                shown_text(f"hub {COMMAND}: skipped the claim {shown_path(str(path))}: {error}"),
                err=True,
            )
    return tuple(claims)


def _claim(path: Path, ticket: str) -> Claim:
    raw = _bounded_read(path, MAX_CLAIM_BYTES)
    try:
        claim = Claim.model_validate_json(raw)
    except ValidationError:
        raise _UnreadableError("it is not a claim with the fields hub claim writes") from None
    if claim.ticket != ticket:
        raise _UnreadableError(f"it names another ticket, {claim.ticket}")
    return claim


def _bounded_read(path: Path, limit: int) -> bytes:
    """A regular file's bytes, never through a link; raises ``_UnreadableError`` past ``limit``."""
    try:
        descriptor = os.open(path, _NO_LINK)
    except OSError as error:
        why = "it is a link" if error.errno == errno.ELOOP else _why(error)
        raise _UnreadableError(why) from None
    try:
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise _UnreadableError("it is not a regular file")
            raw = stream.read(limit + 1)
    except OSError as error:
        raise _UnreadableError(_why(error)) from None
    if len(raw) > limit:
        raise _UnreadableError(f"it is larger than {limit} bytes")
    return raw


def _why(error: OSError) -> str:
    return error.strerror or type(error).__name__
