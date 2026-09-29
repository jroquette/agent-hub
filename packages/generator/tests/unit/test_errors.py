from agent_hub.core.errors import AgentHubError
from agent_hub.generator.errors import (
    FileWriteError,
    GeneratorError,
    LinkOutsideHubError,
    SymlinkedAncestorError,
    TemplateError,
)


def test_is_agent_hub_error_when_generator_error_raised() -> None:
    assert issubclass(GeneratorError, AgentHubError)


def test_is_generator_error_when_template_error_raised() -> None:
    assert issubclass(TemplateError, GeneratorError)


def test_names_source_and_placeholder_when_template_error_built() -> None:
    error = TemplateError(
        source="templates/AGENTS.md.tmpl", placeholder="nmae", reason="unknown placeholder"
    )

    assert error.source == "templates/AGENTS.md.tmpl"
    assert error.placeholder == "nmae"
    assert str(error) == "templates/AGENTS.md.tmpl: unknown placeholder: nmae"


def test_is_generator_error_when_write_error_raised() -> None:
    assert issubclass(FileWriteError, GeneratorError)
    assert issubclass(SymlinkedAncestorError, GeneratorError)
    assert issubclass(LinkOutsideHubError, GeneratorError)


def test_names_path_and_cause_when_write_errors_built() -> None:
    write = FileWriteError(path="scripts/run.py", cause="No space left on device")
    ancestor = SymlinkedAncestorError(path="plugin/agents/x.md", ancestor="plugin")
    outside = LinkOutsideHubError(path=".claude/agents/x.md")

    assert (write.path, write.cause) == ("scripts/run.py", "No space left on device")
    assert str(write) == "scripts/run.py: No space left on device"
    assert (ancestor.path, ancestor.ancestor) == ("plugin/agents/x.md", "plugin")
    assert str(ancestor) == "plugin/agents/x.md: symlinked ancestor plugin"
    assert outside.path == ".claude/agents/x.md"
    assert str(outside) == ".claude/agents/x.md: resolves outside the hub"
