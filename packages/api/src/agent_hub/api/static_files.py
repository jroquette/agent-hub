"""The built web app (``web_dist``): its files, and ``index.html`` for every app route.

The app routes in the browser (``/sessions/abc``), so a GET of any path outside ``/api`` that
names no file answers ``index.html``. A missing file with an extension (``/missing.js``) is a
404, so a broken asset fails visibly, except under a Brain route (``/projects/<p>/brain/...``),
whose paths are notes (``index.md``); anything under ``/api/v1`` no route matched is a 404
problem, never the app.

Vite names each file under ``assets/`` after its content, so every answer there is cached a year
as ``immutable`` and carries ``Vary: Accept-Encoding``; ``index.html`` stays ``no-cache``, so the
next load picks up a new release. The build writes a Brotli variant (``<name>.br``) beside each
script, style and SVG of 1 KB or more. A client whose ``Accept-Encoding`` takes ``br`` gets it,
typed as the file itself and with its own etag; every other client, and any ``Range`` request,
gets the file as it is.
"""

import mimetypes
import re
import stat
from pathlib import Path, PurePosixPath

from starlette.datastructures import Headers
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from agent_hub.api.openapi_paths import API_PREFIX
from agent_hub.api.rfc9457 import problem

WEB_DIST = Path(__file__).parent / "web_dist"
INDEX = "index.html"
READ_METHODS = frozenset({"GET", "HEAD"})
# The Brain screen's routes end with a note's path, extension included.
_BRAIN_ROUTE = re.compile(r"^/projects/[^/]+/brain/")
# The build's hashed files: a name there never changes content (AC-10).
_ASSETS = "assets/"
_IMMUTABLE = "public, max-age=31536000, immutable"
_BROTLI = "br"
# How much of ``Accept-Encoding`` is read: the rest is ignored, never an error.
_MAX_ACCEPT_ENCODING_CHARS = 1_024
_MAX_CODINGS = 32
# RFC 9110's qvalue: 0 to 1, at most three decimals.
_QVALUE = re.compile(r"0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?")


class WebApp:
    """The ASGI app mounted at ``/`` behind the API routes."""

    def __init__(self, directory: Path = WEB_DIST) -> None:
        self._directory = directory
        self._files = StaticFiles(directory=directory, check_dir=False)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope["path"])
        response: Response
        if _is_api(path):
            response = problem(
                404, title="Not Found", detail="No API route has this path.", instance=path
            )
        elif scope["method"] not in READ_METHODS:
            response = problem(405, title="Method Not Allowed", instance=path)
            response.headers["Allow"] = "GET, HEAD"
        elif self._names_file(path):
            served = self._files.get_path(scope)
            if not served.startswith(_ASSETS):
                await self._files(scope, receive, send)
                return
            response = await self._asset(served, scope)
        elif PurePosixPath(path).suffix and not _BRAIN_ROUTE.match(path):
            response = problem(
                404, title="Not Found", detail="No file has this path.", instance=path
            )
        else:
            response = FileResponse(self._directory / INDEX, headers={"Cache-Control": "no-cache"})
        await response(scope, receive, send)

    async def _asset(self, served: str, scope: Scope) -> Response:
        """A file under ``assets/``: its Brotli variant when the client takes one, else the file
        itself. Each is answered by ``StaticFiles``, so each keeps its own etag and 304 (Q10)."""
        variant = self._variant(served, Headers(scope=scope))
        response = await self._files.get_response(variant or served, scope)
        if variant is not None and isinstance(response, FileResponse):
            response.headers["Content-Type"] = _content_type(served)
            response.headers["Content-Encoding"] = _BROTLI
        response.headers["Vary"] = "Accept-Encoding"
        response.headers["Cache-Control"] = _IMMUTABLE
        return response

    def _variant(self, served: str, headers: Headers) -> str | None:
        """The ``.br`` file the build wrote beside ``served``, when the client takes ``br``. A
        ``Range`` request gets the file itself: a range of encoded bytes confuses clients."""
        if "range" in headers or not _accepts_br(headers.get("accept-encoding", "")):
            return None
        variant = f"{served}.{_BROTLI}"
        return variant if self._is_file(variant) else None

    def _names_file(self, path: str) -> bool:
        relative = path.lstrip("/")
        return bool(relative) and self._is_file(relative)

    def _is_file(self, relative: str) -> bool:
        full, found = self._files.lookup_path(relative)
        return bool(full) and found is not None and stat.S_ISREG(found.st_mode)


def _is_api(path: str) -> bool:
    return path == API_PREFIX or path.startswith(f"{API_PREFIX}/") or path.startswith("/api/")


def _accepts_br(accept_encoding: str) -> bool:
    """Whether ``Accept-Encoding`` takes Brotli: ``br``, else ``*``, with a q above 0 (RFC 9110,
    12.5.3). Only the first 1,024 characters and 32 codings are read, and a coding whose q is
    not a number from 0 to 1 is skipped, so a malformed field gets the file as it is."""
    qualities: dict[str, float] = {}
    for coding in _codings(accept_encoding):
        name, quality = _weighed(coding)
        if quality is not None:
            qualities.setdefault(name, quality)
    return qualities.get(_BROTLI, qualities.get("*", 0.0)) > 0


def _codings(accept_encoding: str) -> list[str]:
    """The field's codings within the bounds. The one the character bound cuts is dropped, so a
    cut ``br;q=0`` is never read as ``br``."""
    codings = accept_encoding[:_MAX_ACCEPT_ENCODING_CHARS].split(",")
    if len(accept_encoding) > _MAX_ACCEPT_ENCODING_CHARS:
        codings.pop()
    return codings[:_MAX_CODINGS]


def _weighed(coding: str) -> tuple[str, float | None]:
    """A coding's name, lowercased, and its q: 1 with no weight, None for a malformed one."""
    name, separator, weight = coding.partition(";")
    return name.strip().lower(), (_quality(weight) if separator else 1.0)


def _quality(weight: str) -> float | None:
    """The q of a ``q=<qvalue>`` weight, or None for any other weight."""
    key, _, value = weight.partition("=")
    value = value.strip()
    if key.strip().lower() != "q" or _QVALUE.fullmatch(value) is None:
        return None
    return float(value)


def _content_type(served: str) -> str:
    """The ``Content-Type`` Starlette gives the file ``served`` (its ``mimetypes`` guess, with
    ``utf-8`` for text), so a variant is typed as its file and never after its ``.br`` name."""
    media_type = mimetypes.guess_type(served)[0] or "application/octet-stream"
    return f"{media_type}; charset=utf-8" if media_type.startswith("text/") else media_type
