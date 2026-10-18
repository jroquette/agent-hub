"""The lines the CLI prints about declared environments (docs/design/environments.md).

``production_line`` is the one explicit line a production environment gets wherever a command
names it (``hub sync``, later ``hub setup`` and ``hub env``): its name, its effective access and
the file that access comes from. ``production_lines`` gives one per production environment of an
effective view, committed ones first. Only the ``production`` flag counts, never a name.
"""

from agent_hub.core.hub_config.effective_environments import EffectiveEnvironments


def production_line(name: str, access: str, source: str) -> str:
    """``production environment: <name> (access <access>, <source>)``."""
    return f"production environment: {name} (access {access}, {source})"


def production_lines(view: EffectiveEnvironments) -> tuple[str, ...]:
    """One line per production environment of ``view``, in its order."""
    return tuple(
        production_line(environment.name, environment.access, environment.source)
        for environment in view.environments
        if environment.production
    )
