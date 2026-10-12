"""The Phase 2 contract's paths, and the paths an app's OpenAPI document lists."""

from fastapi import FastAPI

API_PREFIX = "/api/v1"

# Exactly the spec's "API surface in P2"; no P3/P4 path exists in the document (D21).
P2_PATHS: frozenset[tuple[str, str]] = frozenset(
    (method, f"{API_PREFIX}{path}")
    for method, path in (
        ("post", "/events/hooks"),
        ("get", "/hubs"),
        ("post", "/hubs"),
        ("delete", "/hubs/{hub_id}"),
        ("get", "/projects"),
        ("get", "/projects/{project}"),
        ("get", "/projects/{project}/now"),
        ("get", "/projects/{project}/repos"),
        ("get", "/needs-you"),
        ("get", "/activity"),
        ("get", "/search"),
        ("get", "/sessions"),
        ("get", "/sessions/{session_id}"),
        ("get", "/sessions/{session_id}/summary"),
        ("get", "/sessions/{session_id}/events"),
        ("get", "/sessions/{session_id}/events/stream"),
        ("get", "/sessions/{session_id}/files"),
        ("get", "/sessions/{session_id}/cost"),
        ("get", "/live-sessions"),
        ("get", "/live-sessions/stream"),
        ("get", "/workflow-runs"),
        ("get", "/workflow-runs/{run_id}"),
        ("get", "/workflow-runs/{run_id}/stream"),
        ("get", "/approvals"),
        ("get", "/approvals/{approval_id}"),
        ("get", "/learnings"),
        ("get", "/learnings/{learning_id}"),
        ("get", "/features"),
        ("get", "/features/{project}/{slug}"),
        ("get", "/doctor/findings"),
        ("get", "/collector/status"),
        ("get", "/settings"),
        ("get", "/events/stream"),
    )
)


def document_paths(app: FastAPI) -> frozenset[tuple[str, str]]:
    """Every ``(method, path)`` of the app's OpenAPI document."""
    paths: dict[str, dict[str, object]] = app.openapi()["paths"]
    return frozenset((method, path) for path, item in paths.items() for method in item)
