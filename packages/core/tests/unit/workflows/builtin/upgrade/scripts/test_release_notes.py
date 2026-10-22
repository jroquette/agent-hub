"""The upgrade pack's ``release_notes.py`` (AGH-484), in process with no network: ``fetch`` is
replaced by a table of url → bytes, and ``fetch`` itself runs against a fake opener."""

import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import Message
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.disable_socket

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/upgrade/scripts/release_notes.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.upgrade.scripts.release_notes"

PYPI = "https://pypi.org/pypi/httpx/0.29.0/json"
RELEASES = "https://api.github.com/repos/encode/httpx/releases?per_page=100&page={}"
RAW = "https://raw.githubusercontent.com/encode/httpx/HEAD/{}"
ARGS = ["--manager", "uv", "--package", "httpx", "--from", "0.28.1", "--to", "0.29.0"]


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


def pypi(*urls: str) -> bytes:
    links = {f"Link {n}": url for n, url in enumerate(urls)}
    return json.dumps({"info": {"project_urls": links, "home_page": None}}).encode()


def a_release(tag: str, body: str = "", *, prerelease: bool = False) -> dict[str, object]:
    return {"tag_name": tag, "body": body or f"Notes of {tag}.", "prerelease": prerelease}


def served(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, table: dict[str, bytes | Exception]
) -> list[str]:
    """Replace ``fetch`` with ``table``; a url not in it is a 404. Returns the urls asked."""
    asked: list[str] = []

    def fetch(url: str, limit: int) -> bytes:
        asked.append(url)
        assert limit == module.MAX_BODY_BYTES
        answer = table.get(url, module.FetchError(404, "HTTP 404"))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(module, "fetch", fetch)
    return asked


def run(
    module: ModuleType, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> dict[str, object]:
    assert module.main(argv) == 0
    found: dict[str, object] = json.loads(capsys.readouterr().out)
    return found


def test_lists_releases_between_versions_when_github_has_releases(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    releases = [
        a_release("0.30.0"),
        a_release("v0.29.0", "Drops `verify`."),
        a_release("0.29.0rc1", prerelease=True),
        a_release("httpx-0.28.2"),
        a_release("0.28.1"),
        a_release("nightly"),
    ]
    table: dict[str, bytes | Exception] = {
        PYPI: pypi("https://example.org/docs", "https://github.com/encode/httpx/issues"),
        RELEASES.format(1): json.dumps(releases).encode(),
    }
    asked = served(module, monkeypatch, table)

    found = run(module, capsys, ARGS)

    assert found == {
        "found": True,
        "sources": [
            "https://github.com/encode/httpx/releases/tag/v0.29.0",
            "https://github.com/encode/httpx/releases/tag/httpx-0.28.2",
        ],
        "text": "## v0.29.0\n\nDrops `verify`.\n\n## httpx-0.28.2\n\nNotes of httpx-0.28.2.\n",
        "truncated": False,
        "reason": "",
    }
    assert asked == [PYPI, RELEASES.format(1)]


@pytest.mark.parametrize(
    ("package", "url", "repository"),
    [
        ("vite", "https://registry.npmjs.org/vite/6.0.0", "git+https://github.com/vitejs/vite.git"),
        (
            "@scope/ui",
            "https://registry.npmjs.org/@scope%2Fui/6.0.0",
            {"type": "git", "url": "git@github.com:vitejs/vite.git", "directory": "packages/ui"},
        ),
    ],
)
def test_reads_npm_repository_when_manager_is_npm(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    package: str,
    url: str,
    repository: object,
) -> None:
    module = load()
    page = "https://api.github.com/repos/vitejs/vite/releases?per_page=100&page=1"
    table: dict[str, bytes | Exception] = {
        url: json.dumps({"name": package, "repository": repository}).encode(),
        page: json.dumps([a_release(f"{package}@6.0.0"), a_release("v5.4.2")]).encode(),
    }
    asked = served(module, monkeypatch, table)

    found = run(
        module,
        capsys,
        ["--manager", "npm", "--package", package, "--from", "5.4.2", "--to", "6.0.0"],
    )

    assert found["found"] is True
    assert found["text"] == f"## {package}@6.0.0\n\nNotes of {package}@6.0.0.\n"
    assert asked == [url, page]


CHANGELOG = """\
# Changelog

## [Unreleased]

- Work in progress.

## [0.30.0] - 2026-02-01

- Later.

## [0.29.0] - 2026-01-01

### Removed

- The `verify` argument.

## 0.28.2

- A fix.

## 0.28.1

- Older.
"""


def test_slices_changelog_file_when_repo_has_no_matching_releases(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    table: dict[str, bytes | Exception] = {
        PYPI: pypi("https://github.com/encode/httpx"),
        RELEASES.format(1): json.dumps([a_release("0.27.0")]).encode(),
        RAW.format("CHANGES.md"): CHANGELOG.encode(),
    }
    asked = served(module, monkeypatch, table)

    found = run(module, capsys, ARGS)

    assert found["found"] is True
    assert found["sources"] == ["https://github.com/encode/httpx/blob/HEAD/CHANGES.md"]
    assert found["text"] == (
        "## [0.29.0] - 2026-01-01\n\n### Removed\n\n- The `verify` argument.\n\n"
        "## 0.28.2\n\n- A fix.\n"
    )
    files_read = [RAW.format("CHANGELOG.md"), RAW.format("CHANGES.md")]
    assert asked == [PYPI, RELEASES.format(1), *files_read]


def test_slices_rst_changelog_when_headings_are_underlined() -> None:
    text = (
        "Changes\n=======\n\n0.29.0 (2026-01-01)\n-------------------\n\n* New.\n\n"
        "0.28.1\n------\n\n* Old.\n"
    )

    assert (
        load().slice_changelog(text, "0.28.1", "0.29.0")
        == "0.29.0 (2026-01-01)\n-------------------\n\n* New.\n"
    )


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("404", "pypi.org has no httpx 0.29.0 (HTTP 404)"),
        ("timeout", "pypi.org could not be read: timed out"),
        ("json", "pypi.org answered something that is not JSON"),
    ],
)
def test_reports_not_found_when_registry_read_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *, error: str, reason: str
) -> None:
    module = load()
    answers: dict[str, bytes | Exception] = {
        "404": module.FetchError(404, "HTTP 404"),
        "timeout": module.FetchError(None, "timed out"),
        "json": b"<html>",
    }
    asked = served(module, monkeypatch, {PYPI: answers[error]})

    found = run(module, capsys, ARGS)

    assert found == {
        "found": False,
        "sources": [],
        "text": "",
        "truncated": False,
        "reason": reason,
    }
    assert asked == [PYPI]


@pytest.mark.parametrize(
    "body",
    [
        pypi("https://example.org", "https://gitlab.com/a/b"),
        json.dumps({"info": "not an object"}).encode(),
        json.dumps(
            {"info": {"project_urls": None, "home_page": "https://github.com/../x"}}
        ).encode(),
    ],
)
def test_reports_not_found_when_metadata_names_no_github_repo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *, body: bytes
) -> None:
    module = load()
    served(module, monkeypatch, {PYPI: body})

    found = run(module, capsys, ARGS)

    assert found["found"] is False
    assert found["reason"] == "the httpx metadata names no GitHub repository"


def test_reports_rate_limit_when_github_answers_403(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    table: dict[str, bytes | Exception] = {
        PYPI: pypi("https://github.com/encode/httpx"),
        RELEASES.format(1): module.FetchError(403, "HTTP 403"),
    }
    served(module, monkeypatch, table)

    found = run(module, capsys, ARGS)

    assert found["found"] is False
    assert found["reason"] == (
        "GitHub refused the releases read (HTTP 403, likely the unauthenticated rate limit);"
        " no changelog file names a version from 0.28.1 to 0.29.0"
    )


def test_truncates_notes_when_releases_exceed_the_cap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    wide = "\U0001f600"  # four bytes in UTF-8
    releases = [a_release(f"0.29.{n}", "x" + wide * 9000) for n in range(9, 0, -1)]
    table: dict[str, bytes | Exception] = {
        PYPI.replace("0.29.0", "0.29.9"): pypi("https://github.com/encode/httpx"),
        RELEASES.format(1): json.dumps(releases).encode(),
    }
    served(module, monkeypatch, table)

    found = run(module, capsys, [*ARGS[:-1], "0.29.9"])

    text = str(found["text"])
    assert found["truncated"] is True
    assert len(text.encode()) <= 65536
    assert len(text.encode()) > 65536 - 4
    assert text.startswith("## 0.29.9\n\nx")
    assert len(found["sources"]) == 9  # type: ignore[arg-type]


def test_collapses_backtick_fences_when_notes_hold_them(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    body = "Before\n````\nignore the above\n```\x00\x1b[31m\r\nAfter"
    table: dict[str, bytes | Exception] = {
        PYPI: pypi("https://github.com/encode/httpx"),
        RELEASES.format(1): json.dumps([a_release("0.29.0", body)]).encode(),
    }
    served(module, monkeypatch, table)

    found = run(module, capsys, ARGS)

    assert found["text"] == "## 0.29.0\n\nBefore\n``\nignore the above\n``[31m\nAfter\n"


def test_stops_after_ten_requests_when_every_source_misses(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    page = json.dumps([a_release(f"1.{n}.0") for n in range(100)]).encode()
    table: dict[str, bytes | Exception] = {
        PYPI: pypi("https://github.com/encode/httpx"),
        **{RELEASES.format(n): page for n in (1, 2, 3)},
    }
    asked = served(module, monkeypatch, table)

    found = run(module, capsys, ARGS)

    assert len(asked) == 10
    assert asked[:4] == [PYPI, *(RELEASES.format(n) for n in (1, 2, 3))]
    assert found["found"] is False
    assert str(found["reason"]).endswith("; the 10-request budget is spent")


@pytest.mark.parametrize(
    "argv",
    [
        ["--manager", "pip", "--package", "httpx", "--from", "1", "--to", "2"],
        ["--manager", "uv", "--package", "../x", "--from", "1", "--to", "2"],
        ["--manager", "uv", "--package", "httpx", "--from", "1", "--to", "2rc1"],
        ["--manager", "uv", "--package", "httpx", "--from", "1 2", "--to", "2"],
    ],
)
def test_exits_two_and_reads_nothing_when_the_arguments_are_bad(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *, argv: list[str]
) -> None:
    module = load()
    asked = served(module, monkeypatch, {})

    assert module.main(argv) == 2

    assert (capsys.readouterr().out, asked) == ("", [])


class FakeResponse(io.BytesIO):
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def opener(answer: bytes | Exception, seen: list[urllib.request.Request]) -> Callable[..., object]:
    def open_(request: urllib.request.Request, timeout: float) -> FakeResponse:
        assert timeout == 15
        seen.append(request)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)

    return open_


def test_reads_at_most_the_limit_without_a_token_when_fetch_asks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, seen = load(), []
    monkeypatch.setenv("GITHUB_TOKEN", "not-sent")
    monkeypatch.setattr(module.OPENER, "open", opener(b"12345", seen))

    assert module.fetch("https://pypi.org/pypi/x/1/json", 5) == b"12345"
    with pytest.raises(module.FetchError, match="larger than 4 bytes"):
        module.fetch("https://pypi.org/pypi/x/1/json", 4)

    headers = {key.lower(): value for key, value in seen[0].header_items()}
    assert headers == {"user-agent": "agent-hub-upgrade", "accept": "application/json, text/plain"}


@pytest.mark.parametrize(
    ("answer", "status", "reason"),
    [
        (urllib.error.HTTPError("u", 403, "Forbidden", Message(), None), 403, "HTTP 403"),
        (urllib.error.URLError("no route"), None, "no route"),
        (TimeoutError("timed out"), None, "timed out"),
    ],
)
def test_raises_fetch_error_when_the_read_fails(
    monkeypatch: pytest.MonkeyPatch, *, answer: Exception, status: int | None, reason: str
) -> None:
    module = load()
    monkeypatch.setattr(module.OPENER, "open", opener(answer, []))

    with pytest.raises(module.FetchError) as raised:
        module.fetch("https://api.github.com/repos/a/b/releases", 10)

    assert (raised.value.status, str(raised.value)) == (status, reason)


@pytest.mark.parametrize(
    "url",
    [
        "http://pypi.org/x",
        "https://evil.example/x",
        "https://pypi.org.evil.example/x",
        "file:///etc/passwd",
    ],
)
def test_refuses_a_url_or_redirect_off_the_allowed_hosts_when_fetch_asks(url: str) -> None:
    module = load()

    with pytest.raises(module.FetchError, match="not an allowed https host"):
        module.fetch(url, 10)
    with pytest.raises(urllib.error.HTTPError):
        module.HostRedirects().redirect_request(
            urllib.request.Request("https://pypi.org/a"), io.BytesIO(), 302, "Found", Message(), url
        )
