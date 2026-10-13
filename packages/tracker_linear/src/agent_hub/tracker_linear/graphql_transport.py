"""The transport shared by the Linear GraphQL adapters (ADR 0014, ADR 0025).

One POST per request to the fixed endpoint, with the key from ``LINEAR_API_KEY`` read on each
call (never at construction) and sent as the bare ``Authorization`` value (a personal API key
takes no ``Bearer``). Caller values travel only as GraphQL variables, never in the query text.

Every failure is a one-line ``TrackerError`` naming the operation, the issue id, the cause and
the fix: a missing or malformed key (before any request), a transport ``OSError`` or timeout,
an HTTP error status, a body that is not JSON, a GraphQL ``errors`` array at any status, and an
answer whose shape is not the one the query selects. Each raise site sets the error's ``kind``
(``not_connected``, ``unauthorized``, ``timeout``, ``rate_limited``, ``unavailable``,
``unreachable``, ``unexpected``) and ``http_status`` when Linear answered. Nothing is retried.
The key is never part of a message, a ``repr`` or a log record.

The default transport is ``urllib_post`` (standard library only, AC-9.6); tests pass their own.
"""

import http.client
import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from typing import IO, Any, Protocol, override

from agent_hub.core.errors import TrackerError, TrackerFailure

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
LINEAR_API_KEY_VARIABLE = "LINEAR_API_KEY"
# Untrusted text (a Linear error message) quoted in an error is cut to this many characters.
MAX_QUOTED_CHARS = 200
# A key is sent as a header value as is: only printable ASCII, no space, is accepted.
_API_KEY_PATTERN = re.compile(r"[\x21-\x7e]+")
# A longer answer is refused (the default transport reads at most one byte more).
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


# A response shape: a type (or types) for a leaf, a dict of exactly these fields, a list of
# items of one shape, or ``Nullable(shape)`` for null or that shape.
type Shape = type | tuple[type, ...] | dict[str, Shape] | list[Shape] | Nullable


@dataclass(frozen=True, slots=True)
class Nullable:
    """A shape that also accepts null: a nullable object field, such as an unset assignee."""

    shape: Shape


UNEXPECTED_FIX = "Linear's API may have changed; report it with the operation named here"


class Post(Protocol):
    """The HTTP transport: POST ``body`` to ``url`` and return ``(status, response body)``.

    ``timeout_s`` bounds each blocking step (connecting, each read), not the whole call.
    """

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        """Send one request; a step that waits longer than ``timeout_s`` seconds gives up."""
        ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect: a followed one would resend ``Authorization`` to its host."""

    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        # None makes urllib raise HTTPError for the 3xx, which urllib_post returns as an answer.
        return None


def opener_with(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
    """urllib's default opener (proxies from the environment, verified HTTPS) minus redirects.

    ``handlers`` replace or add to the defaults, as in ``urllib.request.build_opener``.
    """
    return urllib.request.build_opener(_NoRedirect, *handlers)


_OPENER = opener_with()


def urllib_post(
    url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
) -> tuple[int, bytes]:
    """The default ``Post``: one ``urllib`` POST, reading at most ``MAX_RESPONSE_BYTES + 1``.

    An HTTP error status, a redirect included (never followed), is an answer, returned as
    ``(status, body)``. ``timeout_s`` applies to each socket operation (connect, each read), so
    a slow trickle can take longer in total, and the DNS lookup has no bound. A timeout raises
    ``TimeoutError``; any other failure raises an ``OSError`` (a malformed HTTP answer becomes a
    ``ConnectionError``). No message names the headers, so the key never reaches one.
    """
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")  # noqa: S310 - fixed https endpoint
    try:
        try:
            response = _OPENER.open(request, timeout=timeout_s)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read(MAX_RESPONSE_BYTES + 1)
        with response:
            return response.status, response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise TimeoutError(f"no answer within {timeout_s:g} s") from error
        raise
    except http.client.HTTPException as error:
        raise ConnectionError(f"malformed HTTP answer ({type(error).__name__})") from error


def request_data(  # noqa: PLR0913 - the request's parts, all keyword-only
    *,
    post: Post,
    environ: Mapping[str, str],
    timeout_s: float,
    operation: str,
    issue_id: str | None,
    operation_name: str,
    query: str,
    variables: dict[str, Any],
    shape: Shape,
) -> Any:
    """POST the query named ``operation_name``; return its ``data``, of the given ``shape``."""
    key = api_key(environ, operation, issue_id)
    headers = {"Content-Type": "application/json", "Authorization": key}
    body = json.dumps(
        {"query": query, "operationName": operation_name, "variables": variables}
    ).encode()
    try:
        status, response = post(LINEAR_GRAPHQL_URL, headers, body, timeout_s=timeout_s)
    except TimeoutError as error:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"no answer from Linear within {timeout_s:g} s",
            fix="retry later",
            kind="timeout",
        ) from error
    except OSError as error:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"could not reach Linear: {quoted(without_key(str(error), key))}",
            fix="check the network connection to api.linear.app, then retry",
            kind="unreachable",
        ) from error
    return _data(
        operation=operation,
        issue_id=issue_id,
        operation_name=operation_name,
        answer=(status, response),
        shape=shape,
        key=key,
    )


def api_key(environ: Mapping[str, str], operation: str, issue_id: str | None) -> str:
    """The key from ``environ``, checked before any request; its value is never quoted."""
    key = environ.get(LINEAR_API_KEY_VARIABLE, "")
    if not key:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"{LINEAR_API_KEY_VARIABLE} is not set",
            fix=f"export {LINEAR_API_KEY_VARIABLE} with a Linear personal API key",
            kind="not_connected",
        )
    if not _API_KEY_PATTERN.fullmatch(key):
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"{LINEAR_API_KEY_VARIABLE} has a character outside printable ASCII",
            fix=f"set {LINEAR_API_KEY_VARIABLE} to the key alone, without spaces or newlines",
            kind="unauthorized",
        )
    return key


def _data(
    *,
    operation: str,
    issue_id: str | None,
    operation_name: str,
    answer: tuple[int, bytes],
    shape: Shape,
    key: str,
) -> Any:
    """The answer's ``data``, of ``shape``; any failure the answer reports raises."""
    status, response = answer
    _check_status(operation, issue_id, status)
    payload = _decoded(operation, issue_id, answer)
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if errors:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"Linear answered with an error: {_first_message(errors, key)}",
            fix=_errors_fix(errors, issue_id),
            kind=_errors_kind(errors),
            http_status=status,
        )
    if not 200 <= status < 300:  # noqa: PLR2004 - the HTTP success range
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"Linear rejected the request (HTTP {status})",
            fix=(
                "check the issue id and the state or label names passed"
                " (if they are right, Linear's API may have changed)"
            ),
            kind="unexpected",
            http_status=status,
        )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not fits(data, shape):
        raise unexpected(
            operation, issue_id, f"{operation_name} answered another shape", http_status=status
        )
    return data


def _decoded(operation: str, issue_id: str | None, answer: tuple[int, bytes]) -> Any:
    """The answer's body as JSON, within ``MAX_RESPONSE_BYTES`` and the parser's nesting limit."""
    status, response = answer
    if len(response) > MAX_RESPONSE_BYTES:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"Linear's answer is over {MAX_RESPONSE_BYTES // 1024**2} MiB",
            fix="list a narrower label, or report it with the operation named here",
            kind="unexpected",
            http_status=status,
        )
    try:
        return json.loads(response)
    except RecursionError as error:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause="Linear's answer is nested too deep to read",
            fix=UNEXPECTED_FIX,
            kind="unexpected",
            http_status=status,
        ) from error
    except ValueError as error:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"Linear answered a body that is not JSON (HTTP {status})",
            fix="retry later",
            kind="unexpected",
            http_status=status,
        ) from error


def _check_status(operation: str, issue_id: str | None, status: int) -> None:
    """Raise for the HTTP statuses whose fix does not depend on the body."""
    kind: TrackerFailure
    if status in {401, 403}:
        kind, cause = "unauthorized", f"Linear refused the key (HTTP {status})"
        fix = f"check that {LINEAR_API_KEY_VARIABLE} is a valid Linear API key with access"
    elif 300 <= status < 400:  # noqa: PLR2004 - HTTP redirects
        kind, cause = "unexpected", f"Linear answered a redirect (HTTP {status})"
        fix = (
            "check for a proxy or network that redirects api.linear.app"
            " (redirects are not followed, so the key is never sent elsewhere)"
        )
    elif status == 429:  # noqa: PLR2004 - HTTP Too Many Requests
        kind, fix = "rate_limited", "retry later"
        cause = f"Linear rate-limited the request (HTTP {status})"
    elif status >= 500:  # noqa: PLR2004 - HTTP server errors
        kind, fix = "unavailable", "retry later"
        cause = f"Linear is unavailable (HTTP {status})"
    else:
        return
    raise TrackerError(
        operation=operation,
        issue_id=issue_id,
        cause=cause,
        fix=fix,
        kind=kind,
        http_status=status,
    )


def _extension_kinds(errors: Any) -> str:
    """The ``code`` and ``type`` of each GraphQL error's ``extensions``, lower case."""
    return " ".join(
        value.lower()
        for error in (errors if isinstance(errors, list) else [])
        if isinstance(error, dict) and isinstance(error.get("extensions"), dict)
        for name, value in error["extensions"].items()
        if name in {"code", "type"} and isinstance(value, str)
    )


def _errors_kind(errors: Any) -> TrackerFailure:
    """The failure kind of a GraphQL ``errors`` array (``unexpected`` unless it says more)."""
    kinds = _extension_kinds(errors)
    if "ratelimited" in kinds:
        return "rate_limited"
    if "authentication" in kinds or "forbidden" in kinds:
        return "unauthorized"
    return "unexpected"


def _errors_fix(errors: Any, issue_id: str | None) -> str:
    """The fix for a GraphQL ``errors`` array, from its ``extensions`` when they say more."""
    kinds = _extension_kinds(errors)
    if "ratelimited" in kinds:
        return "retry later"
    if "authentication" in kinds or "forbidden" in kinds:
        return f"check that {LINEAR_API_KEY_VARIABLE} is a valid Linear API key with access"
    if issue_id is not None:
        return f"check that {issue_id} exists in Linear and the key can read it"
    return "check the team key and the label name"


def fits(value: Any, shape: Shape) -> bool:
    """Whether ``value`` has ``shape``: exactly the selected fields, each of its type."""
    if isinstance(shape, Nullable):
        return value is None or fits(value, shape.shape)
    if isinstance(shape, dict):
        return (
            isinstance(value, dict)
            and value.keys() == shape.keys()
            and all(fits(value[name], field) for name, field in shape.items())
        )
    if isinstance(shape, list):
        (item,) = shape
        return isinstance(value, list) and all(fits(element, item) for element in value)
    return isinstance(value, shape)


def unexpected(
    operation: str, issue_id: str | None, detail: str, *, http_status: int | None = None
) -> TrackerError:
    """The failure of an answer Linear should not give (``detail`` names what was wrong)."""
    return TrackerError(
        operation=operation,
        issue_id=issue_id,
        cause=f"unexpected response from Linear: {detail}",
        fix=UNEXPECTED_FIX,
        kind="unexpected",
        http_status=http_status,
    )


def _first_message(errors: Any, key: str) -> str:
    """The first GraphQL error's message, without the key, quoted and cut: it is untrusted text."""
    first = errors[0] if isinstance(errors, list) and errors else None
    message = first.get("message") if isinstance(first, dict) else None
    return quoted(without_key(str(message), key))


def without_key(text: str, key: str) -> str:
    """``text`` with every copy of ``key`` replaced, before any cut (no prefix may leak)."""
    return text.replace(key, "[the API key]") if key else text


def quoted(text: object) -> str:
    """Untrusted text, cut to ``MAX_QUOTED_CHARS`` and quoted (escapes included)."""
    return repr(str(text)[:MAX_QUOTED_CHARS])
