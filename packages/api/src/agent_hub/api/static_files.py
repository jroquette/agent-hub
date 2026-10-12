"""The built web app (``web_dist``): its files, and ``index.html`` for every app route.

The app routes in the browser (``/sessions/abc``), so a GET of any path outside ``/api`` that
names no file answers ``index.html``. A missing file with an extension (``/missing.js``) is a
404, so a broken asset fails visibly; anything under ``/api/v1`` no route matched is a 404
problem, never the app.
"""

import stat
from pathlib import Path, PurePosixPath

from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from agent_hub.api.openapi_paths import API_PREFIX
from agent_hub.api.rfc9457 import problem

WEB_DIST = Path(__file__).parent / "web_dist"
INDEX = "index.html"
READ_METHODS = frozenset({"GET", "HEAD"})


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
            await self._files(scope, receive, send)
            return
        elif PurePosixPath(path).suffix:
            response = problem(
                404, title="Not Found", detail="No file has this path.", instance=path
            )
        else:
            response = FileResponse(self._directory / INDEX, headers={"Cache-Control": "no-cache"})
        await response(scope, receive, send)

    def _names_file(self, path: str) -> bool:
        relative = path.lstrip("/")
        if not relative:
            return False
        full, found = self._files.lookup_path(relative)
        return bool(full) and found is not None and stat.S_ISREG(found.st_mode)


def _is_api(path: str) -> bool:
    return path == API_PREFIX or path.startswith(f"{API_PREFIX}/") or path.startswith("/api/")
