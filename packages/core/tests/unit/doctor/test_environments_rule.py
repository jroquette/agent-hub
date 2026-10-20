from collections.abc import Callable
from dataclasses import replace

import pytest

import agent_hub.core.doctor.finding as doctor_finding
import agent_hub.core.doctor.snapshot as doctor_snapshot
from agent_hub.core.doctor import environments_rule
from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.run_rules import Selection, run_rules, select_rules
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.local_config import LocalConfig, check_local_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_hub_document,
    a_local_environments_document,
    an_environments_document,
)

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str, Severity, str | None, int | None, str, str]

FIX = (
    "keep the agent's access to a production environment at read, or confirm it on purpose"
    " (docs/design/environments.md)"
)
LIVE_INFO: Shown = (
    "environments.production",
    Severity.INFO,
    "hub.json",
    None,
    "production environment: live (access read, hub.json)",
    FIX,
)
JANE_WARNING: Shown = (
    "environments.production",
    Severity.WARNING,
    "hub.local.json",
    None,
    "production environment: jane-cloud (access write, hub.local.json); actions: writes and"
    " destroys are denied there",
    FIX,
)


def shown(findings: object) -> list[Shown]:
    assert isinstance(findings, (list, tuple))
    return [
        (
            finding.rule,
            finding.severity,
            finding.path,
            finding.line,
            finding.message,
            finding.fix,
        )
        for finding in findings
        if isinstance(finding, Finding)
    ]


def selected(config: HubConfig) -> Selection:
    selection = select_rules((environments_rule.ENVIRONMENTS_PRODUCTION,), config=config, only=())
    assert isinstance(selection, Selection)
    return selection


def production_local() -> LocalConfig:
    document = a_local_environments_document()
    document["environments"]["jane-cloud"]["production"] = True
    return LocalConfig.model_validate(document)


def test_declares_rule_when_rule_read() -> None:
    rule = environments_rule.ENVIRONMENTS_PRODUCTION

    assert rule.id == "environments.production"
    assert rule.severity is Severity.WARNING
    assert rule.reads == frozenset()
    assert rule.module is None


def test_reports_production_environments_when_declared(snapshot_of: SnapshotFactory) -> None:
    # AC-277.9 (Q-8): an info for read access, a warning for write or ask, at its source.
    config = HubConfig.model_validate(an_environments_document())
    snapshot = snapshot_of(config=config, local=production_local())

    findings = environments_rule.ENVIRONMENTS_PRODUCTION.check(snapshot)

    assert shown(list(findings)) == [LIVE_INFO, JANE_WARNING]


def test_warns_at_local_file_when_local_tightens_to_ask(snapshot_of: SnapshotFactory) -> None:
    # The source is the file the effective access comes from (P-6).
    document = an_environments_document()
    document["environments"]["live"]["access"] = "write"
    config = HubConfig.model_validate(document)
    local = LocalConfig.model_validate({"environments": {"live": {"access": "ask"}}})

    findings = environments_rule.ENVIRONMENTS_PRODUCTION.check(
        snapshot_of(config=config, local=local)
    )

    assert shown(list(findings)) == [
        (
            "environments.production",
            Severity.WARNING,
            "hub.local.json",
            None,
            "production environment: live (access ask, hub.local.json); actions: writes and"
            " destroys are denied there",
            FIX,
        )
    ]


def test_reports_nothing_when_named_production_without_flag(
    snapshot_of: SnapshotFactory,
) -> None:
    document = a_hub_document()
    document["environments"] = {"production": {"access": "write"}}
    config = HubConfig.model_validate(document)

    findings = environments_rule.ENVIRONMENTS_PRODUCTION.check(snapshot_of(config=config))

    assert list(findings) == []


def test_reports_committed_only_when_local_file_unusable(snapshot_of: SnapshotFactory) -> None:
    # config.schema reports the local file; this rule still names hub.json's environments.
    config = HubConfig.model_validate(an_environments_document())
    problems = check_local_document([])
    assert not isinstance(problems, LocalConfig)
    redeclared = LocalConfig.model_validate(
        {"environments": {"live": {"access": "read", "production": False}}}
    )

    for local in (problems, redeclared):
        findings = environments_rule.ENVIRONMENTS_PRODUCTION.check(
            snapshot_of(config=config, local=local)
        )
        assert shown(list(findings)) == [LIVE_INFO]


def test_reports_nothing_when_rule_disabled(snapshot_of: SnapshotFactory) -> None:
    # AM-2: an ordinary doctor.rules entry; disabled, it gives no finding.
    document = an_environments_document()
    document["doctor"] = {"rules": {"environments.production": {"enabled": False}}}
    config = HubConfig.model_validate(document)
    snapshot = snapshot_of(config=config, local=production_local())

    assert run_rules(selected(config), snapshot) == ()


def test_retunes_every_finding_when_severity_set(snapshot_of: SnapshotFactory) -> None:
    # AM-2: a severity applies to all its findings.
    document = an_environments_document()
    document["doctor"] = {"rules": {"environments.production": {"severity": "error"}}}
    config = HubConfig.model_validate(document)
    snapshot = snapshot_of(config=config, local=production_local())

    findings = run_rules(selected(config), snapshot)

    assert [(finding.severity, finding.path) for finding in findings] == [
        (Severity.ERROR, "hub.json"),
        (Severity.ERROR, "hub.local.json"),
    ]


def production_config(access: str) -> HubConfig:
    document = an_environments_document()
    document["environments"]["live"]["access"] = access
    return HubConfig.model_validate(document)


@pytest.mark.parametrize("access", ["write", "ask"])
def test_says_writes_denied_when_environments_production_has_write_access(
    snapshot_of: SnapshotFactory, access: str
) -> None:
    # AC-350.3 (P-22): actions never write or destroy on production, whatever the access says.
    findings = environments_rule.ENVIRONMENTS_PRODUCTION.check(
        snapshot_of(config=production_config(access))
    )

    assert shown(list(findings)) == [
        (
            "environments.production",
            Severity.WARNING,
            "hub.json",
            None,
            f"production environment: live (access {access}, hub.json); actions: writes and"
            " destroys are denied there",
            FIX,
        )
    ]


def test_keeps_info_when_environments_production_has_read_access(
    snapshot_of: SnapshotFactory,
) -> None:
    # AC-350.3: reads only, so nothing is denied that the access allows.
    findings = environments_rule.ENVIRONMENTS_PRODUCTION.check(
        snapshot_of(config=production_config("read"))
    )

    assert shown(list(findings)) == [LIVE_INFO]


ENV_FILE_FIX = (
    "keep each declared env file present, git-ignored and inside the hub or a declared repo"
    " (docs/design/scenarios.md)"
)


def an_env_file(**changes: object) -> doctor_snapshot.EnvFileFacts:
    facts = doctor_snapshot.EnvFileFacts(
        path="demo-api/environment/.env.staging",
        environment="staging",
        source="hub.json",
        exists=True,
        holder="demo-api",
        ignored=True,
    )
    return replace(facts, **changes)


def env_file_findings(
    snapshot_of: SnapshotFactory, *facts: doctor_snapshot.EnvFileFacts
) -> list[Shown]:
    snapshot = replace(snapshot_of(), env_files=facts)
    return shown(list(environments_rule.ENVIRONMENTS_ENV_FILE.check(snapshot)))


def an_env_file_warning(message: str, path: str = "hub.json") -> Shown:
    return ("environments.env_file", Severity.WARNING, path, None, message, ENV_FILE_FIX)


def test_warns_when_environments_env_file_not_ignored(snapshot_of: SnapshotFactory) -> None:
    # AC-350.45: a committed env file would publish its credentials.
    findings = env_file_findings(snapshot_of, an_env_file(ignored=False))

    assert findings == [
        an_env_file_warning(
            "env file demo-api/environment/.env.staging of staging is not ignored by git in"
            " demo-api"
        )
    ]


def test_warns_when_environments_env_file_missing(snapshot_of: SnapshotFactory) -> None:
    # AC-350.45: at the file that declares it, here the developer's own.
    findings = env_file_findings(
        snapshot_of, an_env_file(exists=False, environment="jane-cloud", source="hub.local.json")
    )

    assert findings == [
        an_env_file_warning(
            "env file demo-api/environment/.env.staging of jane-cloud is missing",
            path="hub.local.json",
        )
    ]


def test_warns_when_environments_env_file_outside_repo(snapshot_of: SnapshotFactory) -> None:
    # AC-350.45: no declared repo and not the hub holds it, so no git ignores it for sure.
    findings = env_file_findings(
        snapshot_of, an_env_file(path="secrets/.env.staging", holder=None, ignored=None)
    )

    assert findings == [
        an_env_file_warning(
            "env file secrets/.env.staging of staging is outside the hub and every declared repo"
        )
    ]


def test_finds_nothing_when_environments_env_file_ignored_and_present(
    snapshot_of: SnapshotFactory,
) -> None:
    # AC-350.45: an ignored, present file, no env file, or facts not read: no finding.
    assert env_file_findings(snapshot_of, an_env_file()) == []
    assert env_file_findings(snapshot_of) == []
    assert list(environments_rule.ENVIRONMENTS_ENV_FILE.check(snapshot_of())) == []
    assert environments_rule.ENVIRONMENTS_ENV_FILE.id == "environments.env_file"
    assert environments_rule.ENVIRONMENTS_ENV_FILE.reads == frozenset(
        {doctor_finding.Read.ENV_FILES}
    )
