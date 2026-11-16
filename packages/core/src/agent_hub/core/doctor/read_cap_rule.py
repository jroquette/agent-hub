"""``instructions.read_cap``: an instruction file sends agents to a doc the Read tool cannot hold.

Claude Code's Read tool refuses a file over 25,000 tokens unless it is read in parts, so an
``AGENTS.md`` that sends every task to a bigger doc costs each session a failed read, then
several partial ones. The rule reads the listed instruction files of the hub (root ``AGENTS.md``,
``CLAUDE.md``…, ``.claude/{rules,agents,skills,commands}``, ``.github/instructions``) and the
plugins' agents and skills, and those of each checked-out repo, line by line
(``config_lint.text_lines``). Each path the line names (a link target or a code span shaped like a
path, as ``instructions.refs`` reads them, ``instruction_rules.line_references``) that resolves,
from the file's folder or the tree's root, to a listed regular doc (``DOC_SUFFIXES``) of the same
tree whose content is over ``READ_CAP_BYTES`` is one warning, at the file's first line naming it.

The cap is in bytes, not tokens: the snapshot holds each listed file's bytes, and no tokenizer
runs here. A repo's findings are at ``../<dir>/<path>``; a doc in another tree (a hub file naming
``../<dir>/…``) is not resolved. A missing doc, a link, an unread file or a file that is not text
gives nothing here (``instructions.refs`` and the runner report those).
"""

import posixpath
from collections.abc import Iterator, Mapping
from typing import Final

from agent_hub.core.doctor.config_lint import (
    file_text,
    instruction_files,
    plugin_files,
    text_lines,
)
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.instruction_rules import line_references
from agent_hub.core.doctor.snapshot import DoctorSnapshot, HubFiles
from agent_hub.core.hub_config.doctor_rules import (
    INSTRUCTIONS_READ_CAP_RULE,
    RULE_MODULES,
    Severity,
)
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.hub_files.tree_snapshot import FileEntry

# The Read tool's cap, in tokens (Claude Code refuses a bigger file read whole).
READ_CAP_TOKENS: Final = 25_000
# The cap in bytes, pinned: agent-hub's docs/SPEC.md was 139,404 bytes for about 53,000 tokens
# (2.6 bytes a token), so 25,000 tokens is about 65,000 bytes; 64 KiB.
READ_CAP_BYTES: Final = 65_536
DOC_SUFFIXES: Final = (".md", ".mdx", ".markdown", ".rst", ".txt")
MESSAGE: Final = (
    "sends agents to {doc} ({size} bytes), over the Read tool's cap of about {tokens} tokens"
    " ({cap} bytes): one Read cannot hold it"
)
FIX: Final = (
    "split {doc} into docs under the cap, or name the section to read (Read with offset and"
    " limit, or grep)"
)


def _instructions_read_cap(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    hub = snapshot.hub
    yield from _tree_findings(hub, files=(*instruction_files(hub), *plugin_files(hub)), shown="")
    for checkout in snapshot.repos:
        files = checkout.files
        if files is None or files.problem is not None:
            continue
        yield from _tree_findings(
            files, files=instruction_files(files), shown=f"../{checkout.dir}/"
        )


def _tree_findings(tree: HubFiles, *, files: tuple[str, ...], shown: str) -> Iterator[Finding]:
    big = _big_docs(tree)
    if not big:
        return
    for path in files:
        text = file_text(tree.entries.get(path))
        if not isinstance(text, str):
            continue
        folder = posixpath.dirname(path)
        named: set[str] = set()
        for number, line in enumerate(text_lines(text), start=1):
            for ref in line_references(line):
                doc = _resolved(ref, folder=folder, big=big)
                if doc is None or doc in named:
                    continue
                named.add(doc)
                words = {"doc": cut_echo(doc), "size": big[doc]}
                yield INSTRUCTIONS_READ_CAP.finding(
                    path=f"{shown}{path}",
                    line=number,
                    message=MESSAGE.format(**words, tokens=READ_CAP_TOKENS, cap=READ_CAP_BYTES),
                    fix=FIX.format(**words),
                )


def _big_docs(tree: HubFiles) -> dict[str, int]:
    """The tree's listed regular docs over the cap, by path, with their size in bytes."""
    found: dict[str, int] = {}
    for path in tree.listed:
        entry = tree.entries.get(path)
        if (
            path.endswith(DOC_SUFFIXES)
            and isinstance(entry, FileEntry)
            and entry.content is not None
            and len(entry.content) > READ_CAP_BYTES
        ):
            found[path] = len(entry.content)
    return found


def _resolved(ref: str, *, folder: str, big: Mapping[str, int]) -> str | None:
    """The big doc ``ref`` names from ``folder`` or the root, if any."""
    for base in (folder, ""):
        where = posixpath.normpath(posixpath.join(base, ref))
        if where in big:
            return where
    return None


INSTRUCTIONS_READ_CAP: Final = Rule(
    id=INSTRUCTIONS_READ_CAP_RULE,
    severity=Severity.WARNING,
    summary="no instruction file sends agents to a doc over the Read tool's cap",
    module=RULE_MODULES.get(INSTRUCTIONS_READ_CAP_RULE),
    reads=frozenset({Read.INSTRUCTION_FILES, Read.PLUGIN_FILES, Read.REPOS}),
    check=_instructions_read_cap,
)
