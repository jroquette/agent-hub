import json
from collections.abc import Mapping
from typing import Any

import pytest

from agent_hub.core.environment_discovery.proposal import (
    MAX_PROPOSAL_BYTES,
    NO_BLOCK,
    Asked,
    ProposalError,
    read_proposal,
    with_statuses,
)
from agent_hub.core.hub_config.config_view import hub_config_view
from agent_hub.core.hub_config.effective_environments import EffectiveEnvironments
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import an_environments_document

ASKED = Asked(
    repos=("demo-api",),
    environments=("local", "staging"),
    suggest_environments=False,
    declared=("local", "staging", "live"),
    workspace="/hubs",
)
# Shaped like a GitHub token, built at run time so no secret-shaped text sits in the source.
TOKEN_SHAPED = "ghp_" + "A1b2C3d4E5f6G7h8I9j0" * 2


def _no_git(_keys: frozenset[str]) -> Mapping[str, str]:
    return {}


def _effective() -> EffectiveEnvironments:
    view = hub_config_view(
        hub_path="/hubs/demo-hub",
        config=HubConfig.model_validate(an_environments_document()),
        local=LocalConfig(),
        read_git=_no_git,
    )
    return view.environments


def _reply(document: object, *, before: str = "Here is what I found.") -> str:
    return f"{before}\n\n```json\n{json.dumps(document)}\n```\n"


def _service(**overrides: Any) -> dict[str, Any]:
    service: dict[str, Any] = {
        "repo": "demo-api",
        "name": "payments",
        "kind": "lambda",
        "description": "Takes card payments",
        "evidence": [{"path": "demo-api/serverless.yml", "line": 12}],
        "addresses": [{"environment": "staging", "address": "demo-payments-staging"}],
    }
    return service | overrides


def test_reads_last_json_block_when_reply_holds_several() -> None:
    first = _reply({"services": [_service(name="first")]})
    last = _reply({"services": [_service(name="second")]}, before="Corrected:")

    proposal = read_proposal(first + last, ASKED)

    assert [service.name for service in proposal.services] == ["second"]


def test_raises_when_reply_has_no_json_block() -> None:
    with pytest.raises(ProposalError, match=NO_BLOCK):
        read_proposal("I could not find anything.", ASKED)


def test_raises_when_block_is_not_json() -> None:
    with pytest.raises(ProposalError, match="not valid JSON"):
        read_proposal("```json\n{services: []}\n```", ASKED)


def test_raises_when_block_repeats_a_key() -> None:
    with pytest.raises(ProposalError, match="not valid JSON"):
        read_proposal('```json\n{"services": [], "services": []}\n```', ASKED)


def test_raises_when_block_is_over_the_size_cap() -> None:
    padding = "x" * MAX_PROPOSAL_BYTES

    with pytest.raises(ProposalError, match="512 KiB"):
        read_proposal(_reply({"not_read": [{"path": "demo-api/a", "reason": padding}]}), ASKED)


def test_sets_access_from_preset_when_claude_names_one() -> None:
    reply = _reply(
        {
            "environments": [
                {"name": "staging", "preset": "staging", "access": "write"},
                {"name": "Local", "preset": "local"},
            ]
        }
    )

    proposal = read_proposal(reply, ASKED)

    staging, local = proposal.environments
    assert (staging.access, staging.production) == ("ask", False)
    assert (local.name, local.access) == ("local", "write")


def test_drops_environment_when_not_picked_and_suggestions_off() -> None:
    reply = _reply({"environments": [{"name": "qa", "preset": "staging"}]})

    proposal = read_proposal(reply, ASKED)

    assert proposal.environments == ()
    assert [(item.what, item.reason) for item in proposal.dropped] == [
        ("environment qa", "not one of the environments you picked")
    ]


def test_keeps_new_environment_as_read_production_when_suggestions_on() -> None:
    asked = Asked(**{**ASKED.__dict__, "suggest_environments": True})
    reply = _reply({"environments": [{"name": "prod-eu", "preset": "production"}]})

    (environment,) = read_proposal(reply, asked).environments

    assert (environment.access, environment.production) == ("read", True)


def test_drops_declared_but_unpicked_environment_when_suggestions_on() -> None:
    asked = Asked(**{**ASKED.__dict__, "suggest_environments": True})

    proposal = read_proposal(_reply({"environments": [{"name": "live", "preset": "other"}]}), asked)

    assert proposal.environments == ()


def test_drops_field_without_echo_when_it_has_a_secret_shape() -> None:
    reply = _reply({"services": [_service(description=TOKEN_SHAPED)]})

    proposal = read_proposal(reply, ASKED)

    (service,) = proposal.services
    assert service.description is None
    assert proposal.dropped[0].what == "service demo-api/payments: description"
    assert TOKEN_SHAPED not in proposal.model_dump_json()


def test_drops_service_when_repo_not_picked() -> None:
    proposal = read_proposal(_reply({"services": [_service(repo="other-repo")]}), ASKED)

    assert proposal.services == ()
    assert proposal.dropped[0].reason == "repo: not one of the repos you picked"


def test_drops_address_when_environment_not_picked_or_proposed() -> None:
    service = _service(addresses=[{"environment": "live", "address": "https://pay.example.com"}])

    (checked,) = read_proposal(_reply({"services": [service]}), ASKED).services

    assert checked.addresses == ()


def test_drops_address_when_url_carries_user_info() -> None:
    url = "https://user:pw@pay.example.com"
    service = _service(addresses=[{"environment": "staging", "address": url}])

    proposal = read_proposal(_reply({"services": [service]}), ASKED)

    assert proposal.services[0].addresses == ()
    assert url not in proposal.model_dump_json()


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "demo-api/../secrets", "other/file.yml", "~/x", "demo-api\\a"],
)
def test_refuses_evidence_when_path_leaves_picked_repos(path: str) -> None:
    proposal = read_proposal(_reply({"services": [_service(evidence=[path])]}), ASKED)

    assert proposal.services[0].evidence == ()
    assert proposal.dropped[0].reason == "1 not a file inside a picked repo"


def test_makes_evidence_relative_when_path_is_absolute_in_workspace() -> None:
    evidence = [{"path": "/hubs/demo-api/./infra/stack.ts", "line": 7}]

    proposal = read_proposal(_reply({"services": [_service(evidence=evidence)]}), ASKED)

    assert proposal.services[0].evidence[0].model_dump() == {
        "path": "demo-api/infra/stack.ts",
        "line": 7,
    }


def test_keeps_missing_and_not_read_when_shaped_right() -> None:
    reply = _reply(
        {
            "missing": [{"repo": "demo-api", "name": "events-bus", "why": "built at deploy"}],
            "not_read": [{"path": "demo-api/infra/main.tf", "reason": "too large"}],
        }
    )

    proposal = read_proposal(reply, ASKED)

    assert proposal.missing[0].why == "built at deploy"
    assert proposal.not_read[0].path == "demo-api/infra/main.tf"


def test_drops_second_service_when_proposed_twice() -> None:
    proposal = read_proposal(_reply({"services": [_service(), _service()]}), ASKED)

    assert len(proposal.services) == 1
    assert proposal.dropped[-1].reason == "proposed twice"


def test_computes_statuses_when_compared_with_effective_config() -> None:
    reply = _reply(
        {
            "environments": [
                {"name": "local", "preset": "local"},
                {"name": "staging", "preset": "other"},
            ],
            "services": [
                _service(
                    name="api",
                    addresses=[
                        {"environment": "local", "address": "http://localhost:8000"},
                        {"environment": "staging", "address": "https://api2.example.com"},
                    ],
                ),
                _service(
                    name="orders",
                    addresses=[{"environment": "staging", "address": "demo-orders-staging"}],
                ),
                _service(),
            ],
        }
    )

    proposal = with_statuses(read_proposal(reply, ASKED), _effective())

    local, staging = proposal.environments
    assert (local.status, staging.status, staging.yours) == ("declared", "differs", "ask")
    api, orders, payments = proposal.services
    assert api.status == "differs"
    assert [(item.status, item.yours) for item in api.addresses] == [
        ("declared", None),
        ("differs", "https://api.staging.example.com"),
    ]
    assert orders.status == "declared"
    assert (payments.status, payments.addresses[0].status) == ("new", "new")
