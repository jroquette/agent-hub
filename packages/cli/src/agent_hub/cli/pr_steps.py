"""The steps ``hub run`` and ``hub ship`` share: the gate, the push guard, the push and the PR.

Each step runs its children through the caller's ``child`` (a ``ChildCall``), never through
``run_child`` itself: ``hub run`` passes its own runner, which its tests patch, and a child that
cannot start or times out fails as the caller decides. A step that fails raises ``PrStepError``
with the reason; the caller adds its stage. Timeouts are arguments (``StepTimeouts``), read by the
caller from ``run_steps``' constants at call time, so one patch point serves both commands.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.errors import PrStepError
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.push_guard import REMOTE_URL, names_github_repo, parse_scoped_list, risky_keys
from agent_hub.cli.run_children import (
    gate_command,
    pr_body_reset_command,
    pr_create_command,
    pr_view_command,
    pull_request_path,
    push_command,
    push_env,
    untrusted_env,
)
from agent_hub.core.ai_attribution import carries_ai_attribution
from agent_hub.core.hub_config.conventions import EffectiveConventions
from agent_hub.core.runner.run_texts import conventional_pr_title, pr_title

MAX_ERROR_TAIL_CHARS: Final = 500
MAX_PR_URL_CHARS: Final = 2_048
# The most of a ``gh api`` answer (a PR as JSON, its body included) that is read; one this long
# was cut (only its end is kept) and is refused.
GH_API_OUTPUT_LIMIT: Final = 1 << 20
# The push guard's texts: what the refused call would do with the keys, and what was not done.
PUSH_USE: Final = "a push would use"
PUSH_OUTCOME: Final = "the branch was not pushed"
# The warnings about the body of a PR just created, each one line for the user: the edit that
# sets it again failed (``why``), its answer could not be read, or the body still has the marks.
BODY_NOT_RESET: Final = (
    "the body of {url} could not be set again; check it for an attribution footer: {why}"
)
BODY_NOT_READ: Final = (
    "the body of {url} could not be read back; check it for an attribution footer"
)
BODY_ATTRIBUTED: Final = (
    "the body of {url} still carries AI attribution;"
    " set it again through the session's GitHub tools, or edit it by hand"
)
NO_REST_PATH: Final = "its url is not a github.com pull request"
_URL_SCHEME: Final = "https://"


class ChildCall(Protocol):
    """Runs ``argv`` (in ``cwd``, else the caller's worktree; ``stdin`` its input, else none)
    and returns what it left."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: dict[str, str],
        timeout: float,
        output_limit: int = ...,
        cwd: Path | None = None,
        stdin: bytes | None = None,
    ) -> ChildResult: ...


@dataclass(frozen=True, kw_only=True, slots=True)
class StepTimeouts:
    """The seconds each kind of child may run: the gate, the push, ``gh`` and git's reads."""

    gate: float
    push: float
    gh: float
    git: float


@dataclass(frozen=True, kw_only=True, slots=True)
class PrTarget:
    """Where a branch's PR goes: the repo's GitHub ``owner/name`` and base, and the branch."""

    github: str
    base_branch: str
    branch: str


@dataclass(frozen=True, kw_only=True, slots=True)
class OpenedPr:
    """The branch's PR: its url, and whether it was already open (``found``) or just created.
    ``warning`` is one line for the user, without a command's name, when the body of a PR just
    created holds an attribution footer, or may hold one; else None."""

    url: str
    found: bool
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class _BodyUnknown:
    """The body GitHub holds for a PR is not known: ``warning`` tells the user, in one line."""

    warning: str


@dataclass(frozen=True, kw_only=True, slots=True)
class TitledPr:
    """A PR title; ``unmatched`` is the subject's cleaned first line (cut as a title, empty when
    nothing is left, E20) when a configured ``commit_title`` did not match it, else None."""

    title: str
    unmatched: str | None


def git_output(
    child: ChildCall,
    *arguments: str,
    environ: Mapping[str, str],
    timeout: float,
    accept: tuple[int, ...] = (0,),
    cwd: Path | None = None,
) -> str:
    """git's stdout in ``cwd`` (else the caller's worktree), with the untrusted environment; an
    exit code outside ``accept`` is a ``PrStepError`` naming the git command."""
    result = child(["git", *arguments], env=untrusted_env(environ), timeout=timeout, cwd=cwd)
    if result.returncode not in accept:
        raise PrStepError(f"git {arguments[0]} failed: {error_tail(result.stderr).strip()}")
    return result.stdout.decode(errors="replace")


def refuse_uncommitted(
    child: ChildCall, *, environ: Mapping[str, str], timeout: float, cwd: Path | None = None
) -> None:
    """The gate checks what the PR will hold: the commits, no tracked change beside them
    (untracked files never reach the PR; owner decision, 2026-10-02)."""
    status = git_output(
        child,
        "status",
        "--porcelain",
        "--untracked-files=no",
        environ=environ,
        timeout=timeout,
        cwd=cwd,
    )
    if status.strip():
        raise PrStepError("uncommitted changes in the worktree")


def run_gate(
    child: ChildCall,
    *,
    gate: str,
    environ: Mapping[str, str],
    timeout: float,
    cwd: Path | None = None,
) -> ChildResult:
    """Run ``gate`` with ``bash -c`` and the untrusted environment in ``cwd`` (else the caller's
    worktree); the caller reads the result."""
    return child(gate_command(gate), env=untrusted_env(environ), timeout=timeout, cwd=cwd)


def refuse_risky_config(
    child: ChildCall,
    *,
    github: str,
    environ: Mapping[str, str],
    timeout: float,
    use: str,
    outcome: str,
    cwd: Path | None = None,
) -> None:
    """No token-bearing call (the fetch, the push) when the repo's config in ``cwd`` holds a
    key it would act on, or origin is not ``github``'s url (push_guard). Only key names are
    shown, never values; ``use`` and ``outcome`` say what was refused."""
    listed = git_output(
        child,
        *("config", "--list", "--show-scope", "--includes", "-z"),
        environ=environ,
        timeout=timeout,
        cwd=cwd,
    )
    held = risky_keys(parse_scoped_list(listed))
    if held:
        raise PrStepError(f"git config holds keys {use} ({', '.join(held)}); {outcome}")
    urls = git_output(
        child,
        *("config", "--get-all", REMOTE_URL),
        environ=environ,
        timeout=timeout,
        accept=(0, 1),
        cwd=cwd,
    ).splitlines()
    if not names_github_repo(urls, github=github):
        raise PrStepError(f"{REMOTE_URL} is not the GitHub url of {github}; {outcome}")


def push_branch(
    child: ChildCall,
    *,
    target: PrTarget,
    environ: Mapping[str, str],
    timeouts: StepTimeouts,
    cwd: Path | None = None,
) -> None:
    """Push ``target``'s branch to origin from ``cwd`` (else the caller's worktree) after the
    push guard, with ``push_env`` (the GitHub tokens kept, hooks, fsmonitor and signing off)."""
    refuse_risky_config(
        child,
        github=target.github,
        environ=environ,
        timeout=timeouts.git,
        use=PUSH_USE,
        outcome=PUSH_OUTCOME,
        cwd=cwd,
    )
    argv = push_command(target.branch)
    pushed = child(argv, env=push_env(environ), timeout=timeouts.push, cwd=cwd)
    if pushed.returncode != 0:
        raise PrStepError(f"push failed: {error_tail(pushed.stderr)}")


def open_or_find_pr(
    child: ChildCall,
    *,
    target: PrTarget,
    title: str,
    body: str,
    draft: bool,
    environ: Mapping[str, str],
    timeout: float,
    cwd: Path | None = None,
) -> OpenedPr:
    """Create ``target``'s PR through GitHub's REST API (``gh api``, run in ``cwd``, else the
    caller's worktree; ``body`` on its stdin); when that fails, the branch's PR already open (a
    rerun, which the push updated). Any other outcome is a ``PrStepError``. A PR just created
    whose answer holds another body gets ``body`` again (``_body_warning``); one found open
    keeps its body."""
    env = push_env(environ)
    argv = pr_create_command(
        github=target.github,
        base=target.base_branch,
        branch=target.branch,
        title=title,
        draft=draft,
    )
    created = child(
        argv,
        env=env,
        timeout=timeout,
        output_limit=GH_API_OUTPUT_LIMIT,
        cwd=cwd,
        stdin=body.encode(errors="surrogatepass"),
    )
    if created.returncode != 0:
        existing = _open_pr_url(child, target=target, env=env, timeout=timeout, cwd=cwd)
        if existing is None:
            raise PrStepError(f"gh api POST pulls failed: {error_tail(created.stderr)}")
        return OpenedPr(url=existing, found=True)
    answer = _api_answer(created.stdout)
    pull = answer if isinstance(answer, dict) else {}
    url = _html_url(pull)
    if url is None:
        raise PrStepError("gh printed no PR url")
    warning = _body_warning(
        child, url=url, body=body, held=pull.get("body"), env=env, timeout=timeout, cwd=cwd
    )
    return OpenedPr(url=url, found=False, warning=warning)


def _body_warning(
    child: ChildCall,
    *,
    url: str,
    body: str,
    held: object,
    env: dict[str, str],
    timeout: float,
    cwd: Path | None,
) -> str | None:
    """What the user must know about the body of the PR just created at ``url``, else None.

    A cloud session's create appends an attribution footer to the body. An edit with the same
    text removes it where the environment lets it; through ``gh`` a cloud session can add one
    again, and then the warning says so. ``held`` is the body in the create's answer: when it
    is not ``body``, the body is set again and read back; an answer without a body is left
    alone. The body GitHub holds at the end must carry no AI attribution. Nothing here raises:
    the PR is open.
    """
    if not isinstance(held, str):
        return None
    if held != body:
        reset = _reset_body(child, url=url, body=body, env=env, timeout=timeout, cwd=cwd)
        if isinstance(reset, _BodyUnknown):
            return reset.warning
        held = reset
    return BODY_ATTRIBUTED.format(url=url) if carries_ai_attribution(held) else None


def _reset_body(
    child: ChildCall, *, url: str, body: str, env: dict[str, str], timeout: float, cwd: Path | None
) -> str | _BodyUnknown:
    """Set the body of the PR at ``url`` to ``body`` again with one REST edit (``body`` on its
    stdin); the body in the edit's answer, which is what GitHub holds now."""
    path = pull_request_path(url)
    if path is None:
        return _BodyUnknown(BODY_NOT_RESET.format(url=url, why=NO_REST_PATH))
    try:
        edited = child(
            pr_body_reset_command(path),
            env=env,
            timeout=timeout,
            output_limit=GH_API_OUTPUT_LIMIT,
            cwd=cwd,
            stdin=body.encode(errors="surrogatepass"),
        )
    except PrStepError as error:
        return _BodyUnknown(BODY_NOT_RESET.format(url=url, why=_one_line(error.reason)))
    if edited.returncode != 0:
        why = _one_line(error_tail(edited.stderr))
        return _BodyUnknown(BODY_NOT_RESET.format(url=url, why=why))
    answer = _api_answer(edited.stdout)
    held = answer.get("body") if isinstance(answer, dict) else None
    return held if isinstance(held, str) else _BodyUnknown(BODY_NOT_READ.format(url=url))


def _one_line(text: str) -> str:
    """``text`` with each run of blanks and line breaks as one space, shown as JSON when it
    still holds an unprintable character."""
    return shown_text(" ".join(text.split()))


def _open_pr_url(
    child: ChildCall, *, target: PrTarget, env: dict[str, str], timeout: float, cwd: Path | None
) -> str | None:
    """The url of the branch's open PR, the first the REST lookup lists; None when there is
    none."""
    argv = pr_view_command(github=target.github, branch=target.branch)
    viewed = child(argv, env=env, timeout=timeout, output_limit=GH_API_OUTPUT_LIMIT, cwd=cwd)
    if viewed.returncode != 0:
        return None
    listed = _api_answer(viewed.stdout)
    found = listed[0] if isinstance(listed, list) and listed else None
    if not isinstance(found, dict) or found.get("state") != "open":
        return None
    return _html_url(found)


def _api_answer(stdout: bytes) -> object:
    """The JSON ``gh api`` printed; None when it is not JSON or was cut (``GH_API_OUTPUT_LIMIT``
    bytes or more)."""
    if len(stdout) >= GH_API_OUTPUT_LIMIT:
        return None
    try:
        return json.loads(stdout)
    except ValueError:
        return None


def _html_url(pull: dict[str, object]) -> str | None:
    """The PR page url (``html_url``; ``url`` is the API's) of a REST answer's PR, when
    ``pr_url_of`` accepts it."""
    url = pull.get("html_url")
    return pr_url_of(url.encode()) if isinstance(url, str) else None


def titled_pr(
    subject: str, *, conventions: EffectiveConventions, issue_id: str, workspace: str
) -> TitledPr:
    """The PR title of the newest commit ``subject``, following the repo's conventions."""
    titled = conventional_pr_title(
        subject, conventions=conventions, issue_id=issue_id, workspace=workspace
    )
    if not titled.unmatched:
        return TitledPr(title=titled.title, unmatched=None)
    line = pr_title(subject, workspace=workspace, fallback="")
    return TitledPr(title=titled.title, unmatched=line)


def unmatched_warning(prefix: str, *, line: str, commit_title: str) -> str:
    """The one stderr warning of a subject ``line`` that ``commit_title`` did not match (E12)."""
    shown = "the subject" if line else "the issue id"
    return (
        f"{prefix}: warning: the commit subject `{shown_text(line)}` does not match"
        f" commit_title `{commit_title}`; the PR title is {shown}"
    )


def error_tail(data: bytes) -> str:
    """The last ``MAX_ERROR_TAIL_CHARS`` characters of a child's output, decoded."""
    return data.decode(errors="replace")[-MAX_ERROR_TAIL_CHARS:]


def pr_url_of(stdout: bytes) -> str | None:
    """The last line of ``gh``'s output when it is one printable ``https://`` url (E21)."""
    lines = stdout.decode(errors="replace").strip().splitlines()
    last = lines[-1].strip() if lines else ""
    if last.startswith(_URL_SCHEME) and last.isprintable() and " " not in last:
        return last if len(last) <= MAX_PR_URL_CHARS else None
    return None
