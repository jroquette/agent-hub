from agent_hub.core.errors import AgentHubError
from agent_hub.generator.errors import GeneratorError, TemplateError


def test_is_agent_hub_error_when_generator_error_raised() -> None:
    assert issubclass(GeneratorError, AgentHubError)


def test_is_generator_error_when_template_error_raised() -> None:
    assert issubclass(TemplateError, GeneratorError)
