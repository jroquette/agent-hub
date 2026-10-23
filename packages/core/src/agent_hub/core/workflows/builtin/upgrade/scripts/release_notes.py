# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Read a package's upstream release notes between two versions; print them as one JSON object.

``release_notes.py --manager uv|npm --package <name> --from <version> --to <version>``. A workflow
agent cannot reach the network, so this script reads, with no token and over https only:

1. the package's metadata for ``to`` (``pypi.org/pypi/<name>/<to>/json`` or
   ``registry.npmjs.org/<name>/<to>``), for the GitHub repository it names;
2. that repository's GitHub releases (``api.github.com``, up to 3 pages of 100), keeping each
   final release ``v`` with ``from < v <= to`` (a tag's ``v``, ``<name>@`` or ``<name>-``
   prefix dropped; pre-releases and drafts skipped) whose body holds notes (not blank, not only
   "see the changelog"), newest first;
3. else a changelog file at ``raw.githubusercontent.com/<owner>/<repo>/HEAD/<file>``, sliced from
   the first heading naming a version in that range down to the first naming ``from`` or older.

Bounds: at most ``MAX_REQUESTS`` requests, each ``TIMEOUT`` seconds and ``MAX_BODY_BYTES``; a
redirect off the allowed hosts is refused. The notes are untrusted text: control characters are
dropped, every run of three or more backticks becomes two (so the text cannot close the prompt's
fence), and ``text`` is cut to ``MAX_TEXT_BYTES`` of UTF-8 on a character boundary
(``truncated``). The output is ``{"found", "sources", "text", "truncated", "reason"}``; no notes
is data (``found`` false and the reason, such as GitHub's unauthenticated rate limit), never a
failure: exit 0. A bad argument exits 2 and reads nothing.
"""

# The hub runs pack scripts with uv, but they still import on the hooks' Python 3.9 floor.
from __future__ import annotations

import argparse
import http.client
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import IO

PYPI_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
NPM_NAME = re.compile(r"(@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]{0,213}")
FINAL = re.compile(r"[0-9]+(\.[0-9]+){0,3}")
ANY_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,63}")
GITHUB = re.compile(
    r"(?:^|//|@)github\.com[/:]([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})"
)
VERSION_TOKEN = re.compile(r"(?<![0-9A-Za-z.])v?([0-9]+(?:\.[0-9]+){1,3})(?![0-9.]|[A-Za-z])")
UNDERLINE = re.compile(r"([=\-~^*+#])\1{2,}\s*")
FENCE_RUN = re.compile("`{3,}")
# A release body that only points elsewhere ("See CHANGELOG.md") holds no notes.
POINTER = re.compile(
    r"(see|refer to|check)\b.*\b(changelog|changes|history|release notes|news)\b", re.I | re.S
)
MAX_POINTER_CHARS = 300
CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")
ALLOWED_HOSTS = frozenset(
    {"pypi.org", "registry.npmjs.org", "api.github.com", "raw.githubusercontent.com"}
)
MAX_REQUESTS = 10
TIMEOUT = 15
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_TEXT_BYTES = 65536
MAX_SOURCES = 10
MAX_REASON_CHARS = 500
RELEASE_PAGES = 3
PAGE_SIZE = 100
CHANGELOG_FILES = (
    "CHANGELOG.md",
    "CHANGES.md",
    "HISTORY.md",
    "CHANGELOG.rst",
    "CHANGES.rst",
    "NEWS.md",
    "docs/changelog.md",
)
HEADERS = {"User-Agent": "agent-hub-upgrade", "Accept": "application/json, text/plain"}


class FetchError(Exception):
    """A read that gave no body; ``status`` is the HTTP status when there was one."""

    def __init__(self, status: int | None, reason: str) -> None:
        super().__init__(reason)
        self.status = status


class BudgetSpentError(Exception):
    """The run used its ``MAX_REQUESTS``."""


def allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS and not parts.username


class HostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to an allowed https host."""

    def redirect_request(  # noqa: PLR0913, PLR0917 - urllib's signature
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if not allowed(newurl):
            raise urllib.error.HTTPError(
                newurl, code, "redirect off the allowed hosts", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(HostRedirects)


def fetch(url: str, limit: int) -> bytes:
    """The body at ``url``, at most ``limit`` bytes; no token, ``TIMEOUT`` seconds."""
    if not allowed(url):
        raise FetchError(None, f"{url} is not an allowed https host")
    request = urllib.request.Request(url, headers=HEADERS)  # noqa: S310 - https, allowed hosts
    try:
        with OPENER.open(request, timeout=TIMEOUT) as response:
            data: bytes = response.read(limit + 1)
    except urllib.error.HTTPError as error:
        raise FetchError(error.code, f"HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise FetchError(None, str(error.reason)) from error
    except (OSError, http.client.HTTPException) as error:
        raise FetchError(None, str(error) or type(error).__name__) from error
    if len(data) > limit:
        raise FetchError(None, f"the answer is larger than {limit} bytes")
    return data


class Reader:
    """``fetch`` within the request budget."""

    def __init__(self) -> None:
        self.used = 0

    def get(self, url: str) -> bytes:
        if self.used >= MAX_REQUESTS:
            raise BudgetSpentError
        self.used += 1
        return fetch(url, MAX_BODY_BYTES)

    def json(self, url: str) -> object:
        try:
            return json.loads(self.get(url))
        except ValueError as error:
            host = urllib.parse.urlsplit(url).hostname
            raise FetchError(None, f"{host} answered something that is not JSON") from error


def version(text: str) -> tuple[int, ...] | None:
    return tuple(int(part) for part in text.split(".")) if FINAL.fullmatch(text) else None


def leading(text: str) -> tuple[int, ...]:
    found = re.match(r"[0-9]+(\.[0-9]+)*", text.strip().lstrip("v"))
    return tuple(int(part) for part in found.group(0).split(".")) if found else ()


def _trimmed(numbers: tuple[int, ...]) -> tuple[int, ...]:
    while numbers and numbers[-1] == 0:
        numbers = numbers[:-1]
    return numbers


def in_range(numbers: tuple[int, ...], old: str, new: str) -> bool:
    value = _trimmed(numbers)
    return _trimmed(leading(old)) < value <= _trimmed(leading(new))


def clean(text: str) -> str:
    """Untrusted text made safe to fence: no control characters, no run of 3 backticks."""
    text = CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    return FENCE_RUN.sub("``", text)


def github_repo(metadata: object, manager: str) -> tuple[str, str] | None:
    """The GitHub ``(owner, repo)`` the package metadata names first, or None."""
    candidates: list[object] = []
    if isinstance(metadata, dict) and manager == "uv":
        info = metadata.get("info")
        if isinstance(info, dict):
            urls = info.get("project_urls")
            candidates += list(urls.values()) if isinstance(urls, dict) else []
            candidates.append(info.get("home_page"))
    elif isinstance(metadata, dict):
        repository = metadata.get("repository")
        url = repository.get("url") if isinstance(repository, dict) else repository
        candidates.append(url)
    for candidate in candidates:
        found = GITHUB.search(candidate) if isinstance(candidate, str) else None
        if found:
            repo = found.group(2).removesuffix(".git")
            if repo.strip("."):
                return found.group(1), repo
    return None


def tag_version(tag: str, package: str) -> tuple[int, ...] | None:
    lowered = tag.lower()
    for prefix in (f"{package.lower()}@", f"{package.lower()}-", "v"):
        lowered = lowered.removeprefix(prefix)
    return version(lowered)


def pick_releases(
    releases: list[object], *, old: str, new: str, package: str
) -> list[tuple[str, str]]:
    """The ``(tag, body)`` of each final release with ``old < v <= new``, newest first."""
    kept: list[tuple[tuple[int, ...], str, str]] = []
    for release in releases:
        if not isinstance(release, dict) or release.get("prerelease") or release.get("draft"):
            continue
        tag, body = release.get("tag_name"), release.get("body")
        numbers = tag_version(tag, package) if isinstance(tag, str) else None
        if isinstance(tag, str) and numbers is not None and in_range(numbers, old, new):
            kept.append((numbers, tag, body if isinstance(body, str) else ""))
    kept.sort(key=lambda item: item[0], reverse=True)
    return [(tag, body) for _, tag, body in kept]


def _heading_version(lines: list[str], index: int) -> tuple[int, ...] | None:
    line = lines[index]
    following = lines[index + 1] if index + 1 < len(lines) else ""
    if not (line.startswith("#") or (line.strip() and UNDERLINE.fullmatch(following))):
        return None
    token = VERSION_TOKEN.search(line)
    return tuple(int(part) for part in token.group(1).split(".")) if token else None


def slice_changelog(text: str, old: str, new: str) -> str | None:
    """The changelog from the first heading in ``(old, new]`` to the first at ``old`` or older."""
    lines = text.splitlines()
    start = end = None
    for index in range(len(lines)):
        numbers = _heading_version(lines, index)
        if numbers is None:
            continue
        if start is None and in_range(numbers, old, new):
            start = index
        elif start is not None and _trimmed(numbers) <= _trimmed(leading(old)):
            end = index
            break
    if start is None:
        return None
    return "\n".join(lines[start:end]).rstrip() + "\n"


def has_notes(body: str) -> bool:
    """Whether a release body says something: not blank, not only a pointer to a changelog."""
    text = body.strip()
    return bool(text) and not (len(text) <= MAX_POINTER_CHARS and POINTER.match(text))


class Notes:
    """What the reads found so far: the notes, their sources and why some failed."""

    def __init__(self) -> None:
        self.sections: list[str] = []
        self.sources: list[str] = []
        self.reasons: list[str] = []
        self.silent_releases = 0


def read_releases(
    reader: Reader, repo: tuple[str, str], *, args: argparse.Namespace, notes: Notes
) -> None:
    owner, name = repo
    for page in range(1, RELEASE_PAGES + 1):
        url = (
            f"https://api.github.com/repos/{owner}/{name}/releases?per_page={PAGE_SIZE}&page={page}"
        )
        try:
            releases = reader.json(url)
        except FetchError as error:
            if error.status in {403, 429}:
                notes.reasons.append(
                    f"GitHub refused the releases read (HTTP {error.status},"
                    " likely the unauthenticated rate limit)"
                )
            elif error.status != 404:
                notes.reasons.append(f"GitHub releases could not be read: {error}")
            return
        if not isinstance(releases, list):
            return
        add_releases(releases, repo, args=args, notes=notes)
        older = [r for r in releases if isinstance(r, dict) and _is_old(r, args)]
        if len(releases) < PAGE_SIZE or older:
            return


def add_releases(
    releases: list[object], repo: tuple[str, str], *, args: argparse.Namespace, notes: Notes
) -> None:
    """Add each in-range release that holds notes; count the ones that say nothing."""
    owner, name = repo
    for tag, body in pick_releases(releases, old=args.old, new=args.new, package=args.package):
        if not has_notes(body):
            notes.silent_releases += 1
            continue
        notes.sections.append(f"## {tag}\n\n{body.strip()}\n")
        quoted = urllib.parse.quote(tag, safe="@")
        notes.sources.append(f"https://github.com/{owner}/{name}/releases/tag/{quoted}")


def _is_old(release: dict[str, object], args: argparse.Namespace) -> bool:
    tag = release.get("tag_name")
    numbers = tag_version(tag, args.package) if isinstance(tag, str) else None
    return numbers is not None and _trimmed(numbers) <= _trimmed(leading(args.old))


def read_changelog(
    reader: Reader, repo: tuple[str, str], *, args: argparse.Namespace, notes: Notes
) -> None:
    owner, name = repo
    for file in CHANGELOG_FILES:
        try:
            data = reader.get(f"https://raw.githubusercontent.com/{owner}/{name}/HEAD/{file}")
        except FetchError:
            continue
        sliced = slice_changelog(data.decode("utf-8", errors="replace"), args.old, args.new)
        if sliced is not None:
            notes.sections.append(sliced)
            notes.sources.append(f"https://github.com/{owner}/{name}/blob/HEAD/{file}")
            return
    notes.reasons.append(f"no changelog file names a version from {args.old} to {args.new}")


def metadata_url(manager: str, package: str, new: str) -> str:
    if manager == "uv":
        return f"https://pypi.org/pypi/{package}/{new}/json"
    return f"https://registry.npmjs.org/{urllib.parse.quote(package, safe='@')}/{new}"


def collect(args: argparse.Namespace) -> Notes:
    reader, notes = Reader(), Notes()
    url = metadata_url(args.manager, args.package, args.new)
    host = urllib.parse.urlsplit(url).hostname
    try:
        metadata = reader.json(url)
    except FetchError as error:
        missing = f"{host} has no {args.package} {args.new} (HTTP 404)"
        notes.reasons.append(missing if error.status == 404 else _failed(host, error))
        return notes
    repo = github_repo(metadata, args.manager)
    if repo is None:
        notes.reasons.append(f"the {args.package} metadata names no GitHub repository")
        return notes
    try:
        read_releases(reader, repo, args=args, notes=notes)
        if not notes.sections and not notes.reasons:
            span = f"from {args.old} to {args.new}"
            notes.reasons.append(
                f"the GitHub releases {span} hold no notes"
                if notes.silent_releases
                else f"no GitHub release names a version {span}"
            )
        if not notes.sections:
            read_changelog(reader, repo, args=args, notes=notes)
    except BudgetSpentError:
        notes.reasons.append(f"the {MAX_REQUESTS}-request budget is spent")
    return notes


def _failed(host: str | None, error: FetchError) -> str:
    text = str(error)
    return text if text.startswith(f"{host} ") else f"{host} could not be read: {text}"


def result(notes: Notes) -> dict[str, object]:
    text = clean("\n".join(notes.sections))
    data = text.encode()
    truncated = len(data) > MAX_TEXT_BYTES
    if truncated:
        text = data[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")
    found = bool(notes.sections)
    return {
        "found": found,
        "sources": [source[:500] for source in notes.sources[:MAX_SOURCES]],
        "text": text,
        "truncated": truncated,
        "reason": "" if found else "; ".join(notes.reasons)[:MAX_REASON_CHARS],
    }


def parse(argv: list[str]) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(prog="release_notes.py")
    parser.add_argument("--manager", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--from", dest="old", required=True)
    parser.add_argument("--to", dest="new", required=True)
    args = parser.parse_args(argv)
    names = {"uv": PYPI_NAME, "npm": NPM_NAME}
    if args.manager not in names:
        problem = f"the manager is not uv or npm: {args.manager!r}"
    elif not names[args.manager].fullmatch(args.package):
        problem = f"not a package name: {args.package!r}"
    elif not ANY_VERSION.fullmatch(args.old) or version(args.new) is None:
        problem = f"not a version range: {args.old!r} to {args.new!r}"
    else:
        return args
    print(f"release_notes.py: {problem}", file=sys.stderr)
    return None


def main(argv: list[str]) -> int:
    args = parse(argv)
    if args is None:
        return 2
    print(json.dumps(result(collect(args))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
