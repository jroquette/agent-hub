"""``links.dead``: relative Markdown links that resolve to no file or folder (spec AC-11.27, Q-18).

Inline links and images (E19) and reference definitions, outside code spans, fenced blocks and
HTML comments (indented code blocks are read, E37), in the listed ``.md`` files of the hub and
of each checked-out repo; a hub link into ``../<dir>/`` is checked against that repo's listing.
Scale: every scan is linear in the line (plan's scale traps), checked by exact results and by
counting what the scans pass over.
"""

import re
from collections.abc import Callable, Iterator

import pytest

from agent_hub.core.doctor import links_rule
from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.links_rule import LINKS_DEAD
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_files.tree_snapshot import FileEntry

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, int | None, str]

FIX = "point the link at an existing file or folder, or remove it"
NOTES = "notes.md"


def dead_link(target: str) -> str:
    return f"dead link `{target}` (no such file or folder)"


def dead(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(LINKS_DEAD.check(snapshot))
    assert all(finding.rule == "links.dead" for finding in found)
    assert all(finding.severity is Severity.ERROR for finding in found)
    assert all(finding.fix == FIX for finding in found)
    return [(finding.path, finding.line, finding.message) for finding in found]


def notes(snapshot_of: SnapshotFactory, text: str, **files: bytes) -> DoctorSnapshot:
    """A hub whose ``notes.md`` holds the text, beside the files given by path."""
    return snapshot_of(files={NOTES: text.encode(), **{path: b"x\n" for path in files}})


def test_declares_design_id_when_rule_read() -> None:
    assert LINKS_DEAD.id == "links.dead"
    assert LINKS_DEAD.reads == frozenset({Read.HUB_LISTING, Read.REPOS})
    assert LINKS_DEAD.severity is Severity.ERROR
    assert LINKS_DEAD.module is None


def test_reports_link_when_target_missing(snapshot_of: SnapshotFactory) -> None:
    text = "# A\n\nSee [b](b.md), [root](../README.md) and [gone](gone.md).\n\n[also](c.md)\n"
    snapshot = snapshot_of(
        files={"docs/a.md": text.encode(), "docs/b.md": b"x\n", "README.md": b"x\n"}
    )

    assert dead(snapshot) == [
        ("docs/a.md", 3, dead_link("gone.md")),
        ("docs/a.md", 5, dead_link("c.md")),
    ]


def test_checks_link_without_fragment_when_fragment_given(snapshot_of: SnapshotFactory) -> None:
    text = "[a](b.md#part) [b](gone.md#part) [c](b.md?plain=1#x) [d](b.md#)\n"

    assert dead(notes(snapshot_of, text, **{"b.md": b""})) == [
        (NOTES, 1, dead_link("gone.md#part"))
    ]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("[a](http://example.com/gone.md)\n", id="http"),
        pytest.param("[a](https://example.com/gone.md)\n", id="https"),
        pytest.param("[a](mailto:someone@example.com)\n", id="mailto"),
        pytest.param("[a](ftp://example.com/gone.md)\n", id="other-scheme"),
        pytest.param("[a](#section) [b](#)\n", id="fragment-only"),
        pytest.param("[a](/gone.md) [b](//host/gone.md)\n", id="absolute"),
        pytest.param("[a]() [b](<>) [c]( )\n", id="empty"),
        pytest.param("Use `[a](gone.md)` here.\n", id="code-span"),
        pytest.param("Use ``a ` [b](gone.md) `` here.\n", id="code-span-double"),
        pytest.param("```md\n[a](gone.md)\n```\n", id="fence"),
        pytest.param("~~~\n[a](gone.md)\n~~~\n", id="fence-tilde"),
        pytest.param("````\n```\n[a](gone.md)\n````\n", id="fence-shorter-inside"),
        pytest.param("  ```\n[a](gone.md)\n  ```\n", id="fence-indented"),
        pytest.param("text\n```\n[a](gone.md)\n", id="fence-unclosed"),
        pytest.param("[a](../elsewhere/gone.md)\n", id="leaving-to-sibling"),
        pytest.param("[a](../../gone.md) [b](..)\n", id="leaving-workspace"),
        pytest.param("not a link](gone.md)\n", id="no-link-text"),
    ],
)
def test_skips_link_when_not_checkable(snapshot_of: SnapshotFactory, text: str) -> None:
    assert dead(notes(snapshot_of, text)) == []


def test_reads_code_after_span_when_backticks_close(snapshot_of: SnapshotFactory) -> None:
    # A run of backticks with no closing run of the same length is literal text.
    text = "`a` [b](gone.md) `` [c](gone2.md)\n```js\n```\n[d](gone3.md)\n"

    assert dead(notes(snapshot_of, text)) == [
        (NOTES, 1, dead_link("gone.md")),
        (NOTES, 1, dead_link("gone2.md")),
        (NOTES, 4, dead_link("gone3.md")),
    ]


def test_reports_link_when_indented_four_spaces(snapshot_of: SnapshotFactory) -> None:
    # E37: an indented code block is not skipped, and four spaces make no definition either.
    text = "Text.\n\n    [a](gone.md)\n    [b]: gone2.md\n\t[c](gone3.md)\n"

    assert dead(notes(snapshot_of, text)) == [
        (NOTES, 3, dead_link("gone.md")),
        (NOTES, 5, dead_link("gone3.md")),
    ]


@pytest.mark.parametrize(
    ("scheme", "checked"),
    [
        pytest.param("C", True, id="one-character"),
        pytest.param("ab", False, id="two-characters"),
        pytest.param("a" * 32, False, id="thirty-two-characters"),
        pytest.param("a" * 33, True, id="thirty-three-characters"),
        pytest.param("a1+.-", False, id="scheme-characters"),
        pytest.param("1a", True, id="leading-digit"),
    ],
)
def test_checks_path_when_scheme_out_of_bounds(
    snapshot_of: SnapshotFactory, *, scheme: str, checked: bool
) -> None:
    # E37: a URI scheme is 2 to 32 characters, a letter first; anything else is a path.
    target = f"{scheme}:/x.md"

    found = dead(notes(snapshot_of, f"[a]({target})\n"))

    assert found == ([(NOTES, 1, dead_link(target))] if checked else [])


def test_reads_definition_when_nothing_or_title_follows(snapshot_of: SnapshotFactory) -> None:
    # E37: after the destination only blanks or a title may follow, else the line is prose.
    text = (
        "[Note]: this is important\n"
        '[a]: gone1.md "title"\n'
        "[b]: gone2.md 'title'\n"
        "[c]: gone3.md (title)\n"
        "[d]: gone4.md   \n"
        "[e]: <gone5.md> trailing words\n"
        "[f]: <gone6.md>\t'title'\n"
        '[g]: gone7.md"title"\n'
        "[h]: gone8.md title\n"
    )

    assert dead(notes(snapshot_of, text)) == [
        (NOTES, 2, dead_link("gone1.md")),
        (NOTES, 3, dead_link("gone2.md")),
        (NOTES, 4, dead_link("gone3.md")),
        (NOTES, 5, dead_link("gone4.md")),
        (NOTES, 7, dead_link("gone6.md")),
        # A title needs a blank before it, so the quotes are part of the destination.
        (NOTES, 8, dead_link('gone7.md"title"')),
    ]


@pytest.mark.parametrize(
    ("text", "lines"),
    [
        pytest.param("<!-- [a](gone.md) -->\n", [], id="one-line"),
        pytest.param("a <!-- [b](gone.md) --> [c](gone2.md)\n", [1], id="inline-then-link"),
        pytest.param("<!-- x --> <!-- [b](gone.md) --> [c](gone2.md)\n", [1], id="two-on-a-line"),
        pytest.param("<!--\n[a](gone.md)\n[b]: gone.md\n-->[c](gone2.md)\n", [4], id="multi-line"),
        pytest.param("[c](gone2.md) <!-- [a](gone.md)\n[b](gone.md)\n", [1], id="never-closed"),
        # CommonMark 0.31: "<!-->" and "<!--->" are whole (empty) comments.
        pytest.param("<!-->[c](gone2.md) <!--->[d](gone2.md)\n", [1, 1], id="empty-comments"),
        pytest.param("`<!--` [c](gone2.md) `-->`\n", [1], id="in-code-spans"),
        pytest.param("```\n<!--\n```\n[c](gone2.md)\n", [4], id="in-fence"),
    ],
)
def test_skips_link_when_in_html_comment(
    snapshot_of: SnapshotFactory, *, text: str, lines: list[int]
) -> None:
    # E37: an HTML comment, on one line or several, is skipped like a fence.
    assert dead(notes(snapshot_of, text)) == [
        (NOTES, line, dead_link("gone2.md")) for line in lines
    ]


def test_skips_checkout_when_listing_failed(snapshot_of: SnapshotFactory) -> None:
    # E36: a checkout that could not be listed is treated as a missing one.
    snapshot = snapshot_of(
        files={NOTES: b"[a](../demo-api/gone.md) [b](../demo-web/gone.md)\n"},
        repos={
            "demo-api": {"README.md": b"[c](gone.md)\n"},
            "demo-web": {"README.md": b"[d](gone.md)\n"},
        },
        repo_problems={"demo-api": "git ls-files failed"},
    )

    assert dead(snapshot) == [
        (NOTES, 1, dead_link("../demo-web/gone.md")),
        ("../demo-web/README.md", 1, dead_link("gone.md")),
    ]


def test_counts_repo_link_and_skips_unlisted_when_checkout_read(
    snapshot_of: SnapshotFactory,
) -> None:
    # A listed link of a checkout is a path there; an unlisted file is neither read nor a path.
    snapshot = snapshot_of(
        files={NOTES: b"[a](../demo-api/linked.md) [b](../demo-api/extra.md)\n"},
        repos={"demo-api": {"README.md": b"x\n", "extra.md": b"[c](gone.md)\n"}},
        repo_links={"demo-api": {"linked.md": "README.md"}},
        repo_listed={"demo-api": ("README.md", "linked.md")},
    )

    assert dead(snapshot) == [(NOTES, 1, dead_link("../demo-api/extra.md"))]


def test_reads_reference_definition_when_given(snapshot_of: SnapshotFactory) -> None:
    text = (
        "[ok]: b.md\n"
        '[gone]: gone.md "title"\n'
        "  [Gone]: other-gone.md\n"
        "[pointy]: <gone two.md>\n"
        "    [indented]: code.md\n"
        "[later]:\n"
        "[used][gone] and [ok]\n"
        "[empty]: <>\n"
        "[unclosed]: <gone3.md\n"
    )

    # The first definition of a label wins (CommonMark): the second ``gone`` is not a link.
    assert dead(notes(snapshot_of, text, **{"b.md": b""})) == [
        (NOTES, 2, dead_link("gone.md")),
        (NOTES, 4, dead_link("gone two.md")),
    ]


def test_unwraps_and_decodes_target_when_wrapped_or_encoded(snapshot_of: SnapshotFactory) -> None:
    text = (
        "[a](<my file.md>) [b](my%20file.md) [c](<my file.md> \"t\") [d](b.md 'title')\n"
        "[e](my%20gone.md) [f](<my gone.md>) [g](f(1).md) [h](g(1).md)\n"
        "[i](%E2%82%AC.md) [j](%FF.md) [k](a%2Fb.md)\n"
    )
    snapshot = notes(
        snapshot_of,
        text,
        **{"my file.md": b"", "b.md": b"", "f(1).md": b"", "€.md": b"", "a/b.md": b""},
    )

    assert dead(snapshot) == [
        (NOTES, 2, dead_link("my%20gone.md")),
        (NOTES, 2, dead_link("my gone.md")),
        (NOTES, 2, dead_link("g(1).md")),
        (NOTES, 3, dead_link("%FF.md")),
    ]


def test_counts_folder_when_listed_file_under_it(snapshot_of: SnapshotFactory) -> None:
    text = "[a](docs/) [b](docs) [c](docs/guide) [d](./) [e](.) [f](docs/none/) [g](docs/guide/a)\n"

    assert dead(notes(snapshot_of, text, **{"docs/guide/a.md": b""})) == [
        (NOTES, 1, dead_link("docs/none/")),
        (NOTES, 1, dead_link("docs/guide/a")),
    ]


def test_counts_target_when_listed_link_or_fixed_path_present(
    snapshot_of: SnapshotFactory,
) -> None:
    # E31: the listing and the fixed paths present count; any other entry looked at does not.
    snapshot = snapshot_of(
        files={NOTES: b"[a](linked.md) [b](Makefile) [c](leftover.md) [d](package.json)\n"},
        links={"linked.md": "elsewhere.md"},
        entries={
            "Makefile": FileEntry(executable=False, content=b"check:\n"),
            "leftover.md": FileEntry(executable=False, content=b"x\n"),
        },
        listed=(NOTES, "linked.md"),
    )

    assert dead(snapshot) == [
        (NOTES, 1, dead_link("leftover.md")),
        (NOTES, 1, dead_link("package.json")),
    ]


def test_counts_fixed_paths_when_not_all_read(snapshot_of: SnapshotFactory) -> None:
    # An unread fixed path may exist: no rule may call it missing.
    snapshot = snapshot_of(
        files={NOTES: b"[a](Makefile) [b](gone.md)\n"}, paths_read=False, problem="cut short"
    )

    assert dead(snapshot) == [(NOTES, 1, dead_link("gone.md"))]


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(FileEntry(executable=False, content=b"[a](gone.md)\x00\n"), id="nul"),
        pytest.param(FileEntry(executable=False, content=b"[a](gone.md)\xff\n"), id="not-utf8"),
        pytest.param(FileEntry(executable=False, content=None), id="unread"),
    ],
)
def test_skips_file_when_not_text(snapshot_of: SnapshotFactory, entry: FileEntry) -> None:
    assert dead(snapshot_of(entries={NOTES: entry})) == []


def test_skips_file_when_link_unlisted_or_not_markdown(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        files={
            "real.md": b"[a](gone1.md)\n",
            "unlisted.md": b"[a](gone2.md)\n",
            "notes.txt": b"[a](gone3.md)\n",
            "notes.MD.bak": b"[a](gone4.md)\n",
        },
        links={"linked.md": "real.md"},
        listed=("linked.md", "notes.MD.bak", "notes.txt", "real.md"),
    )

    assert dead(snapshot) == [("real.md", 1, dead_link("gone1.md"))]


def test_ends_line_at_newline_only_when_line_ends_vary(snapshot_of: SnapshotFactory) -> None:
    # E29: \n and \r\n end a line, a lone \r does not.
    text = "a\r\nb\r\n[a](gone.md)\r\nc\rd [b](gone2.md)\n"

    assert dead(notes(snapshot_of, text)) == [
        (NOTES, 3, dead_link("gone.md")),
        (NOTES, 4, dead_link("gone2.md")),
    ]


def test_checks_repo_link_when_hub_links_into_checkout(snapshot_of: SnapshotFactory) -> None:
    text = (
        "[a](../demo-api/docs/a.md) [b](../demo-api/docs/gone.md) [c](../demo-api)\n"
        "[d](../demo-api/docs/) [e](../demo-api/src/../docs/a.md#x) [f](../demo-web/gone.md)\n"
    )
    nested = "[adr](../../demo-api/docs/a.md) [up](../../../demo-api/docs/a.md)\n"
    snapshot = snapshot_of(
        files={NOTES: text.encode(), "brain/features/n.md": nested.encode()},
        repos={"demo-api": {"docs/a.md": b"x\n"}, "demo-web": {"README.md": b"x\n"}},
    )

    # From ``brain/features/``, two levels up is ``brain/`` itself, not the workspace.
    assert dead(snapshot) == [
        ("brain/features/n.md", 1, dead_link("../../demo-api/docs/a.md")),
        (NOTES, 1, dead_link("../demo-api/docs/gone.md")),
        (NOTES, 2, dead_link("../demo-web/gone.md")),
    ]


def test_skips_repo_link_when_checkout_missing(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        files={NOTES: b"[a](../demo-api/x.md) [b](../demo-web/gone.md)\n"},
        repos={"demo-api": None, "demo-web": {"README.md": b"x\n"}},
    )

    assert dead(snapshot) == [(NOTES, 1, dead_link("../demo-web/gone.md"))]


def test_checks_repo_markdown_when_checkout_listed(snapshot_of: SnapshotFactory) -> None:
    readme = (
        "[d](docs/gone.md) [ok](src/m.py)\n"
        "[hub](../agent-hub-hub/notes.md) [web](../demo-web/x.md)\n"
    )
    snapshot = snapshot_of(
        files={NOTES: b"x\n"},
        repos={
            "demo-api": {
                "README.md": readme.encode(),
                "docs/guide.md": b"[up](../README.md) [img](../img/gone.png)\n",
                "src/m.py": b"# [a](gone.md)\n",
            },
            "demo-web": {"README.md": b"[a](gone.md)\n"},
        },
    )

    # A link that leaves its repo is not checked; a repo's path is shown from the hub.
    assert dead(snapshot) == [
        ("../demo-api/README.md", 1, dead_link("docs/gone.md")),
        ("../demo-api/docs/guide.md", 1, dead_link("../img/gone.png")),
        ("../demo-web/README.md", 1, dead_link("gone.md")),
    ]


def test_checks_image_when_relative(snapshot_of: SnapshotFactory) -> None:
    text = (
        "![logo](img/logo.png) ![gone](img/gone.png) ![remote](https://x.test/y.png)\n"
        '[![badge](img/logo.png "t")](gone.md)\n'
    )

    assert dead(notes(snapshot_of, text, **{"img/logo.png": b""})) == [
        (NOTES, 1, dead_link("img/gone.png")),
        (NOTES, 2, dead_link("gone.md")),
    ]


def test_reads_destination_once_when_links_nest(snapshot_of: SnapshotFactory) -> None:
    # The destination keeps its balanced parentheses; the "](" inside it opens nothing.
    assert dead(notes(snapshot_of, "[[a](x](y))\n")) == [(NOTES, 1, dead_link("x](y)"))]


def test_cuts_target_when_echoed_long(snapshot_of: SnapshotFactory) -> None:
    target = "a" * 5_000 + ".md"

    assert dead(notes(snapshot_of, f"[a]({target})\n")) == [(NOTES, 1, dead_link("a" * 79 + "…"))]


class TestScale:
    @pytest.mark.parametrize(
        ("line", "found"),
        [
            pytest.param("](" * 50_000, [], id="link-openers"),
            pytest.param("[" * 100_000, [], id="brackets"),
            pytest.param("`" * 100_000, [], id="backticks"),
            pytest.param("`a" * 50_000, [], id="code-spans"),
            pytest.param(
                "".join("`" * length + "a" for length in range(1, 440)), [], id="unclosed-spans"
            ),
            pytest.param("[a](" * 25_000, [], id="unclosed-links"),
            pytest.param("[a](<" * 10_000 + ")" * 10_000, [], id="pointy-unclosed"),
            pytest.param("[a](notes.md " * 4_000 + ")" * 4_000, [], id="titles"),
            pytest.param(
                "[a](" + "(" * 50_000 + ")" * 50_001, ["(" * 79 + "…"], id="nested-parens"
            ),
            pytest.param("[a](" + "%41" * 30_000 + ")", ["%41" * 26 + "%…"], id="encoded"),
            pytest.param("[" + "a" * 100_000 + "]: gone.md", [], id="long-label"),
            pytest.param(" [x]: " + " " * 100_000 + "gone.md", ["gone.md"], id="long-blank"),
            pytest.param("<!--" * 25_000 + "[a](gone.md)", [], id="comment-openers"),
            pytest.param("<!---->[a](gone.md)" * 5_000, ["gone.md"] * 5_000, id="comments"),
        ],
    )
    def test_reports_exact_findings_when_line_hostile(
        self, snapshot_of: SnapshotFactory, *, line: str, found: list[str]
    ) -> None:
        # One line of about 100 KB of one shape; the counters below show each scan is linear.
        snapshot = notes(snapshot_of, f"{line}\n")

        assert dead(snapshot) == [(NOTES, 1, dead_link(target)) for target in found]

    def test_reads_lines_once_when_comment_never_closes(self, snapshot_of: SnapshotFactory) -> None:
        # 20,000 lines inside one open comment, each with an opener and a link.
        text = "<!--\n" + "<!-- [a](gone.md)\n" * 20_000 + "--> [b](gone2.md)\n"

        assert dead(notes(snapshot_of, text)) == [(NOTES, 20_002, dead_link("gone2.md"))]

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param("[](" * 1_000, id="openers"),
            pytest.param("[a](<" * 1_000 + ")" * 1_000, id="pointy-unclosed"),
            pytest.param("[a](b " * 1_000 + ")" * 1_000, id="titles"),
            pytest.param(("[a](" + " " * 10 + "b)") * 1_000, id="blanks"),
            pytest.param("[a](b)" * 1_000, id="bare"),
            pytest.param("[" * 1_000 + "](x" * 1_000 + ")" * 1_000, id="overlapping"),
            # Runs of 1 to 44 backticks, none closed: a closer looked for from each run rescans.
            pytest.param("".join("`" * length + "a" * 10 for length in range(1, 45)), id="spans"),
            pytest.param("<!-- -->" * 1_000, id="comments"),
            pytest.param("<!--" * 1_000, id="comment-openers"),
        ],
    )
    def test_scans_each_character_once_when_openers_repeat(
        self, monkeypatch: pytest.MonkeyPatch, line: str
    ) -> None:
        counters = {
            name: ScanCounter(getattr(links_rule, name))
            for name in (
                "_OPENER",
                "_NOT_BLANK",
                "_DESTINATION_END",
                "_POINTY_END",
                "_BACKTICKS",
                "_COMMENT_OPEN",
                "_COMMENT_CLOSE",
            )
        }
        for name, counter in counters.items():
            monkeypatch.setattr(links_rule, name, counter)

        visible, _ = links_rule._visible(line, in_comment=False)
        targets = list(links_rule._inline_targets(visible or ""))

        # Destinations never overlap, so together they are no longer than the line.
        assert sum(len(target) for target in targets) <= len(line)
        assert {name: counter.characters <= len(line) for name, counter in counters.items()} == {
            name: True for name in counters
        }

    def test_resolves_links_when_paths_deep(self, snapshot_of: SnapshotFactory) -> None:
        # 100 files 600 folders deep, each linking up to the root and to a missing sibling.
        chains = ["/".join([f"c{n}", *(f"s{depth}" for depth in range(599))]) for n in range(100)]
        up = "../" * 600
        text = f"[top]({up}top.md) [gone]({up}gone.md) [here](n.md) [self](../s598/n.md)\n"
        files = {f"{chain}/n.md": text.encode() for chain in chains}
        snapshot = snapshot_of(files={**files, "top.md": b"x\n"})

        assert dead(snapshot) == [
            (f"{chain}/n.md", 1, dead_link((up + "gone.md")[:79] + "…")) for chain in sorted(chains)
        ]

    def test_reads_files_once_when_hub_large(self, snapshot_of: SnapshotFactory) -> None:
        # 3000 Markdown files in a chain of links; only the last one's target is missing.
        files = {f"docs/f{n:04}.md": f"[next](f{n + 1:04}.md)\n".encode() for n in range(3_000)}

        assert dead(snapshot_of(files=files)) == [("docs/f2999.md", 1, dead_link("f3000.md"))]


class ScanCounter:
    """A stand-in for a compiled pattern that counts the characters its scans pass over."""

    def __init__(self, pattern: re.Pattern[str]) -> None:
        self.pattern = pattern
        self.characters = 0

    def search(self, text: str, start: int = 0) -> re.Match[str] | None:
        found = self.pattern.search(text, start)
        self.characters += (len(text) if found is None else found.start()) - start
        return found

    def finditer(self, text: str) -> Iterator[re.Match[str]]:
        yield from self.pattern.finditer(text)
        # Exhausted, the scan has passed over the whole text.
        self.characters += len(text)
