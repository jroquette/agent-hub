import pytest

from agent_hub.generator.errors import TemplateError
from agent_hub.generator.hub_template import render_template


def test_substitutes_both_forms_when_placeholders_known() -> None:
    text = "@@a|@@{b}x|@@@@|$(MAKE)|${{ github.sha }}|$HOME"

    rendered = render_template(text, {"a": "1", "b": "2"}, source="example.tmpl")

    assert rendered == "1|2x|@@|$(MAKE)|${{ github.sha }}|$HOME"


@pytest.mark.parametrize("text", ["say @@nmae here", "say @@{nmae} here"])
def test_raises_template_error_when_placeholder_unknown(text: str) -> None:
    with pytest.raises(TemplateError) as caught:
        render_template(text, {"name": "x"}, source="templates/AGENTS.md.tmpl")

    error = caught.value
    assert error.source == "templates/AGENTS.md.tmpl"
    assert error.placeholder == "nmae"
    assert "templates/AGENTS.md.tmpl" in str(error)
    assert "nmae" in str(error)
    assert isinstance(error.__cause__, KeyError)


@pytest.mark.parametrize(
    ("text", "placeholder", "position"),
    [
        ("a @@ b", "@@", "line 1, column 3"),
        ("x @@@name", "@@@name", "line 1, column 3"),
        ("first\n@@1", "@@1", "line 2, column 1"),
        ("one\ntwo\nx @@{nmae", "@@{nmae", "line 3, column 3"),
    ],
)
def test_raises_template_error_when_placeholder_malformed(
    text: str, placeholder: str, position: str
) -> None:
    with pytest.raises(TemplateError) as caught:
        render_template(text, {"nmae": "x"}, source="templates/Makefile.tmpl")

    error = caught.value
    assert error.source == "templates/Makefile.tmpl"
    assert error.placeholder == placeholder
    assert "templates/Makefile.tmpl" in str(error)
    assert placeholder in str(error)
    assert position in str(error)
    assert isinstance(error.__cause__, ValueError)
