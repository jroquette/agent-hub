"""What an action or a process node does to an environment, which the access policy decides on.

It has a module of its own so that the workflow nodes name it without loading the config
models the access policy reads. ``access_policy`` re-exports it.
"""

from typing import Literal

Effect = Literal["read", "write", "destroy"]
