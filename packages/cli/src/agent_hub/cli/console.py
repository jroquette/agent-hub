"""Entry point of the installed ``hub`` command: a stub until the fast workflow listing lands.

``main`` is to print ``hub workflow list`` without loading Typer when the arguments are exactly
``workflow list``, and to hand any other run to the Typer app in ``agent_hub.cli.main``.
"""


def main() -> None:
    """Run ``hub`` with this process's arguments."""
    raise NotImplementedError
