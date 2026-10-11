"""``GET /settings``: the running server's settings (read-only in Phase 2)."""

from fastapi import APIRouter

from agent_hub.api.rfc9457 import NotImplementedInBuildError
from agent_hub.api.schemas import PROBLEM_RESPONSES
from agent_hub.core.readmodels.settings_view import SettingsView

router = APIRouter(tags=["settings"], responses=PROBLEM_RESPONSES)


@router.get("/settings")
def get_settings() -> SettingsView:
    """Paths, port, version and privacy rules."""
    raise NotImplementedInBuildError("get_settings")
