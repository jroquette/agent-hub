from agent_hub.core.errors import AgentHubError
from agent_hub.generator.errors import GeneratorError, TemplateError


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
