from agent_hub.core.doctor.finding import Rule
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.hub_config.doctor_rules import RULE_IDS, RULE_MODULES, Severity

# The rules this release ships, in RULE_IDS order; each later rule slice appends its own (E21 b).
RELEASED_IDS = (
    "config.schema",
    "platform.version",
    "lock.drift",
    "links.dead",
    "instructions.size",
    "instructions.refs",
    "instructions.duplicates",
    "rules.frontmatter",
    "settings.valid",
    "settings.weakening",
    "permissions.bypass",
    "secrets.config",
    "mcp.pinned",
    "attribution.ai",
    "brain.leak",
    "hooks.guard-extension",
    "makefile.override",
    "features.tracker",
    "bench.tasks",
)

# The "Default" column of docs/design/hub-doctor.md § Rules.
DESIGN_SEVERITIES = {
    "config.schema": Severity.ERROR,
    "platform.version": Severity.ERROR,
    "lock.drift": Severity.ERROR,
    "links.dead": Severity.ERROR,
    "instructions.size": Severity.ERROR,
    "instructions.refs": Severity.ERROR,
    "instructions.duplicates": Severity.ERROR,
    "rules.frontmatter": Severity.ERROR,
    "settings.valid": Severity.ERROR,
    "settings.weakening": Severity.ERROR,
    "permissions.bypass": Severity.ERROR,
    "secrets.config": Severity.ERROR,
    "mcp.pinned": Severity.ERROR,
    "attribution.ai": Severity.ERROR,
    "brain.leak": Severity.ERROR,
    "hooks.guard-extension": Severity.ERROR,
    "makefile.override": Severity.WARNING,
    "features.tracker": Severity.ERROR,
    "bench.tasks": Severity.ERROR,
}


def test_holds_released_rules_when_registry_read() -> None:
    ids = tuple(rule.id for rule in REGISTRY)

    assert ids == RELEASED_IDS
    assert len(set(ids)) == len(ids)
    assert set(ids) <= set(RULE_IDS)
    assert ids == tuple(rule_id for rule_id in RULE_IDS if rule_id in ids)


def test_declares_fields_when_rule_registered() -> None:
    assert DESIGN_SEVERITIES.keys() == set(RULE_IDS)
    for rule in REGISTRY:
        assert isinstance(rule, Rule)
        assert rule.summary.strip() == rule.summary
        assert rule.summary
        assert "\n" not in rule.summary
        assert rule.severity is DESIGN_SEVERITIES[rule.id], rule.id
        assert callable(rule.check)


def test_takes_module_from_rule_modules_when_registered() -> None:
    for rule in REGISTRY:
        assert rule.module == RULE_MODULES.get(rule.id), rule.id
