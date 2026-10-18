"""The owner sign-off's eval note, written into the hub's feature folder (playground).

The folder is ``<hub>/brain/features/<slug>/evals/``; the slug comes from a feature folder the
reader found, and the name from ``SignOffOwnerSteps``. The note is created exclusively, never
overwriting an eval, and no link is followed into the folder.
"""

import os
from pathlib import Path

from agent_hub.core.features.feature_evals import EVALS_FOLDER
from agent_hub.core.readmodels.read_ports import HubReadModels

_FEATURES = ("brain", "features")


class ProjectHubPaths:
    """``ProjectHubs`` over the hub read models."""

    def __init__(self, models: HubReadModels) -> None:
        self._models = models

    def hub_path_of(self, project: str) -> str:
        """The hub folder of ``project``."""
        return self._models.get_project(project).hub_path


class HubEvalWriter:
    """``EvalWriter`` on the local file system."""

    def create_eval(self, hub_path: str, *, slug: str, name: str, text: str) -> None:
        """Create ``brain/features/<slug>/evals/<name>``; ``FileExistsError`` when it exists."""
        if "/" in slug or "/" in name or slug.startswith(".") or name.startswith("."):
            raise ValueError("invalid feature or eval name")
        feature = Path(hub_path, *_FEATURES, slug)
        if feature.is_symlink() or not feature.is_dir():
            raise FileNotFoundError(feature.name)
        folder = feature / EVALS_FOLDER
        if folder.is_symlink():
            raise FileNotFoundError(EVALS_FOLDER)
        folder.mkdir(exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(folder / name, flags, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as note:
            note.write(text)
