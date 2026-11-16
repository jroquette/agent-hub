"""A stored file is either indexed or skipped (AGH-391): exactly one of a hash and a reason."""

import pytest
from pydantic import ValidationError

from agent_hub.core.knowledge.knowledge_index import Fingerprint, StoredFile

_FINGERPRINT = Fingerprint(size=1, mtime_ns=0)


def test_refuses_stored_file_when_hash_and_reason_both_set() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        StoredFile(
            path="brain/now.md", fingerprint=_FINGERPRINT, sha256="ab" * 32, skip_reason="too big"
        )


def test_refuses_stored_file_when_neither_hash_nor_reason_set() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        StoredFile(path="brain/now.md", fingerprint=_FINGERPRINT)
