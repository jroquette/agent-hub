from agent_hub.core import json_form as core_json_form
from agent_hub.generator import json_form


def test_reexports_core_form_when_imported() -> None:
    # One byte form for the whole platform: the generator's JSON files and hub.lock never drift.
    assert json_form.dump_json is core_json_form.dump_json
    assert json_form.JsonValue is core_json_form.JsonValue
