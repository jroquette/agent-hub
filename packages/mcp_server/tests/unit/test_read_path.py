import pytest

from agent_hub.mcp_server.read_path import MAX_PATH_CHARS, PATH_NOT_ALLOWED, refusal

REPO_DIRS = ("demo-api", "demo-web")


def test_states_bounds_when_constants_read() -> None:
    assert MAX_PATH_CHARS == 1024
    assert PATH_NOT_ALLOWED == "path not allowed"


@pytest.mark.parametrize(
    "path",
    [
        "brain/decisions/0001-worktrees.md",
        "brain/now.md",
        "demo-api/docs/adr/0001-x.md",
        "demo-web/docs/guide.md",
        "brain/automation/x.md",
    ],
)
def test_allows_path_when_under_brain_or_repo_docs(path: str) -> None:
    assert refusal(path, REPO_DIRS) is None


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "/brain/now.md",
        "brain/../hub.json",
        "brain/./now.md",
        "brain\\now.md",
        "brain//x.md",
        "brain/now.md/",
        "",
        "brain/no\x00w.md",
        "brain/" + "a" * (1025 - len("brain/.md")) + ".md",
    ],
)
def test_refuses_path_when_grammar_broken(path: str) -> None:
    assert refusal(path, REPO_DIRS) == PATH_NOT_ALLOWED


def test_allows_path_when_exactly_at_length_limit() -> None:
    path = "brain/" + "a" * (MAX_PATH_CHARS - len("brain/.md")) + ".md"
    assert len(path) == MAX_PATH_CHARS
    assert refusal(path, REPO_DIRS) is None


@pytest.mark.parametrize(
    "path",
    [
        "hub.json",
        "now.md",
        "brain/auto/workspace/me.md",
        "brain/AUTO/x.md",
        "brain/x.txt",
        "brain/.md",
        "BRAIN/now.md",
        "demo-api/src/notes.md",
        "demo-api/README.md",
        "nope/docs/a.md",
        "demo-api/docs",
        "demo-api/docs/",
        "demo-api/docs.md",
    ],
)
def test_refuses_path_when_outside_sources(path: str) -> None:
    assert refusal(path, REPO_DIRS) == PATH_NOT_ALLOWED
