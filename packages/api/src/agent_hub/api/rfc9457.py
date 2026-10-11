"""RFC 9457 Problem Details: every error the API answers is one of these documents."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from agent_hub.core.errors import AgentHubError

PROBLEM_MEDIA_TYPE = "application/problem+json"


class NotImplementedInBuildError(AgentHubError):
    """A route of the contract whose behaviour this build does not have yet (answers 501)."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"{operation} is not implemented in this build")


def problem(
    status: int, *, title: str, detail: str | None = None, instance: str | None = None
) -> JSONResponse:
    """A Problem Details response; ``detail`` and ``instance`` are left out when None."""
    document: dict[str, object] = {"type": "about:blank", "title": title, "status": status}
    if detail is not None:
        document["detail"] = detail
    if instance is not None:
        document["instance"] = instance
    return JSONResponse(document, status_code=status, media_type=PROBLEM_MEDIA_TYPE)


async def _not_implemented(request: Request, error: Exception) -> Response:
    return problem(
        501, title="Not implemented in this build", detail=str(error), instance=request.url.path
    )


def install_problem_handlers(app: FastAPI) -> None:
    """Answer the API's own exceptions with problems."""
    app.add_exception_handler(NotImplementedInBuildError, _not_implemented)
