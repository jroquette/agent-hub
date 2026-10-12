"""``GitBrainChangeRequests`` against a real bare ``origin`` and a fake ``gh`` (fixtures in
``tests/conftest.py``) honours the ``BrainChangeRequests`` contract."""

from agent_hub.core.testing.brain_change_requests_contract import BrainChangeRequestsContract


class TestGitBrainChangeRequests(BrainChangeRequestsContract):
    pass
