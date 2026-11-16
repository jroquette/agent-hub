"""The characterization golden of the core unit tests: models' schemas and outcomes.

A module's golden (``packages/core/tests/data/characterization/<module>.json``) pins the JSON
schema of every public pydantic model the module defines and the result of validating a few
inputs, so building the models later (or lazily) cannot change what callers see.
``GOLDEN_UPDATE=1`` rewrites a golden (refused under ``CI``); review and commit the diff.
"""

import inspect
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

CHARACTERIZATION_ROOT = Path(__file__).resolve().parents[1] / "data" / "characterization"


def public_models(module: ModuleType) -> dict[str, type[BaseModel]]:
    """Every pydantic model ``module`` defines whose name has no leading underscore, by name."""
    return {
        name: value
        for name, value in sorted(vars(module).items())
        if inspect.isclass(value)
        and issubclass(value, BaseModel)
        and value.__module__ == module.__name__
        and not name.startswith("_")
    }


def outcome_of(adapter: TypeAdapter[Any], raw: object) -> dict[str, Any]:
    """The JSON dump of ``raw`` once validated, or each error's type, location and message."""
    try:
        value = adapter.validate_python(raw)
    except ValidationError as error:
        return {
            "errors": [
                {"type": item["type"], "loc": list(item["loc"]), "msg": item["msg"]}
                for item in error.errors(include_url=False)
            ]
        }
    return {"valid": adapter.dump_python(value, mode="json")}


@dataclass(frozen=True)
class Characterization:
    """Builds a module's characterization and compares it with the checked-in golden."""

    update: bool

    def snapshot(
        self,
        module: ModuleType,
        cases: Mapping[str, tuple[TypeAdapter[Any], object]],
        extra_schemas: Mapping[str, TypeAdapter[Any]] | None = None,
    ) -> dict[str, Any]:
        schemas = {name: model.model_json_schema() for name, model in public_models(module).items()}
        for name, adapter in (extra_schemas or {}).items():
            schemas[name] = adapter.json_schema()
        return {
            "module": module.__name__,
            "schemas": schemas,
            "outcomes": {name: outcome_of(adapter, raw) for name, (adapter, raw) in cases.items()},
        }

    def check(self, actual: dict[str, Any]) -> None:
        path = CHARACTERIZATION_ROOT / f"{actual['module']}.json"
        text = json.dumps(actual, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if self.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if not path.is_file():
            pytest.fail(f"{path} is missing; write it with GOLDEN_UPDATE=1 and review it")
        expected = json.loads(path.read_text(encoding="utf-8"))
        assert json.loads(text) == expected, (
            f"{path.name}: behaviour changed; rewrite with GOLDEN_UPDATE=1 only if intended"
        )


@pytest.fixture
def characterization() -> Characterization:
    """The golden check; ``GOLDEN_UPDATE=1`` rewrites the golden, and is refused under ``CI``."""
    update = os.environ.get("GOLDEN_UPDATE") == "1"
    if update and os.environ.get("CI"):
        pytest.fail("GOLDEN_UPDATE=1 is refused when CI is set")
    return Characterization(update=update)
