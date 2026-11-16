"""``hub mcp``'s ``propose`` tool (spec D-propose-checks, D-propose-write, D-availability, P-8).

Checks run in this order, each before anything after it: the input bounds (``proposal_input``),
the secret rule over the title and the body (no match is echoed), the hub's author; then the
``BrainChangeRequests`` port, whose adapter checks the hub's availability and its origin before
any clone, and refuses an existing note or branch. Every refusal is a ``ToolRefusal`` whose line
starts ``propose:`` and never quotes the caller's text.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Final

from agent_hub.core.item_versions.secret_match import has_secret_match
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.json_form import JsonValue
from agent_hub.core.learnings.brain_change_requests import (
    BrainChangeRequests,
    BrainProposal,
    ChangeRequestConflictError,
    ChangeRequestFailedError,
    ChangeRequestTimeoutError,
    RefspecRefusedError,
)
from agent_hub.mcp_server.hub_context import HubContext, ToolRefusal
from agent_hub.mcp_server.proposal_input import (
    checked_body,
    checked_title,
    commit_message,
    note_path,
    note_text,
    proposal_date,
    pull_request_body,
    pull_request_title,
    target_folder,
    title_slug,
)

MATCHED_RULE: Final = "propose: the text matches a secret rule"
NO_AUTHOR: Final = "propose: the hub has no author"
TIMED_OUT: Final = "propose: could not open the pull request (timed out)"


class ProposeTool:
    """The ``propose`` tool over ``hub``, opening pull requests through ``change_requests``,
    dating the note with ``clock`` (an aware ``datetime``)."""

    def __init__(
        self,
        hub: HubContext,
        *,
        change_requests: BrainChangeRequests,
        clock: Callable[[], datetime],
    ) -> None:
        self._hub = hub
        self._change_requests = change_requests
        self._clock = clock

    def propose(self, *, title: str, body: str, kind: str, external: bool) -> dict[str, JsonValue]:
        """Open a hub pull request adding the note; its URL, branch and hub-relative path."""
        title = checked_title(title)
        body = checked_body(body)
        target_folder(kind)
        slug = title_slug(title)
        if _matches_secret(title, body):
            raise ToolRefusal(MATCHED_RULE)
        facts = self._hub.proposal
        if facts.author is None:
            raise ToolRefusal(NO_AUTHOR)
        created = proposal_date(self._clock())
        note = note_path(created, slug)
        session = self._hub.session
        proposal = BrainProposal(
            hub_path=self._hub.hub_path,
            hub_repo=facts.hub_repo,
            default_branch=facts.default_branch,
            branch_prefix=facts.branch_prefix,
            slug=slug,
            note=note,
            text=note_text(
                title=title,
                body=body,
                kind=kind,
                external=external,
                created=created,
                session=session,
            ),
            author=facts.author,
            title=pull_request_title(title),
            body=pull_request_body(note=note, body=body, external=external, session=session),
            commit_message=commit_message(slug),
        )
        try:
            opened = self._change_requests.propose(proposal)
        except (ChangeRequestConflictError, RefspecRefusedError) as error:
            raise ToolRefusal(f"propose: {error.reason}") from None
        except ChangeRequestFailedError as error:
            raise ToolRefusal(f"propose: could not {error.step} (step failed)") from None
        except ChangeRequestTimeoutError:
            raise ToolRefusal(TIMED_OUT) from None
        return {"pr_url": opened.pr_url, "branch": opened.branch, "path": f"brain/{note}"}


def _matches_secret(title: str, body: str) -> bool:
    # In path order, as a unit's files are kept.
    files = (
        UnitFile(path="body", content=body.encode("utf-8")),
        UnitFile(path="title", content=title.encode("utf-8")),
    )
    return has_secret_match(UnitContent(files=files))
