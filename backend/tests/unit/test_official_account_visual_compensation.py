from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.infrastructure.db.official_account_visual_compensation import (
    SEPTEMBER_16_TARGET,
    VisualCompensationAuthorization,
    VisualCompensationConsumption,
    check_journal_absence,
)
from pydantic import ValidationError


def authorization(**changes):
    payload = {
        **SEPTEMBER_16_TARGET.model_dump(),
        "account_fingerprint": "a" * 64,
        "render_version_id": uuid4(),
        "original_attempt_id": uuid4(),
        "original_intent_lease_token": uuid4(),
        "original_attempt_number": 1,
        "successor_attempt_number": 2,
        "max_attempts": 3,
        "logical_request_fingerprint": "b" * 64,
        "original_run_bundle_fingerprint": "c" * 64,
        "preserved_content_fingerprint": "d" * 64,
        "snapshot_fingerprint": "e" * 64,
        "authorized_at": datetime(2026, 9, 16, 9, tzinfo=UTC),
        "original_expires_at": datetime(2026, 9, 16, 8, tzinfo=UTC),
        "recovery_expires_at": datetime(2026, 9, 16, 11, tzinfo=UTC),
        **changes,
    }
    return VisualCompensationAuthorization.model_validate(payload)


def test_authority_closed_json_roundtrip_and_new_stable_physical_identity():
    auth = authorization()
    loaded = VisualCompensationAuthorization.model_validate_json(auth.model_dump_json())
    assert loaded == auth
    assert loaded.provider_request_fingerprint == auth.provider_request_fingerprint
    assert auth.provider_request_fingerprint != auth.logical_request_fingerprint
    assert len(auth.model_dump_json()) < 3000
    assert not any(
        word in auth.model_dump_json() for word in ("api_key", "prompt_text", "https://")
    )
    consumed = VisualCompensationConsumption(
        authorization_fingerprint=auth.authorization_fingerprint,
        provider_request_fingerprint=auth.provider_request_fingerprint,
        visual_id=auth.visual_id,
        attempt_number=2,
        lease_token=uuid4(),
    )
    assert VisualCompensationConsumption.model_validate_json(consumed.model_dump_json()) == consumed


@pytest.mark.parametrize(
    "changes",
    [
        {"unexpected": "secret"},
        {"original_attempt_number": True},
        {"successor_attempt_number": 3},
        {"max_attempts": 1},
        {"snapshot_fingerprint": "https://private"},
        {"authorized_at": datetime(2026, 9, 16, 9)},
        {"recovery_expires_at": datetime(2026, 9, 16, 11, 0, 1, tzinfo=UTC)},
        {"recovery_expires_at": datetime(2026, 9, 16, 8, tzinfo=UTC)},
        {
            "authorized_at": datetime(2026, 9, 16, 15, tzinfo=UTC),
            "recovery_expires_at": datetime(2026, 9, 16, 16, tzinfo=UTC),
        },
    ],
)
def test_invalid_authority_is_rejected(changes):
    with pytest.raises(ValidationError):
        authorization(**changes)


def test_late_cutoff_never_crosses_shanghai_midnight():
    auth = authorization(
        authorized_at=datetime(2026, 9, 16, 15, 30, tzinfo=UTC),
        recovery_expires_at=datetime(2026, 9, 16, 16, tzinfo=UTC) - timedelta(microseconds=1),
    )
    assert auth.recovery_expires_at - auth.authorized_at < timedelta(hours=2)


class Journal:
    def __init__(self):
        self.records = {}

    def read(self, name):
        return self.records.get(name)

    def write(self, name, payload):
        assert name not in self.records
        self.records[name] = payload


def test_private_journal_any_target_step_or_claim_blocks_compensation():
    target = SEPTEMBER_16_TARGET
    journal = Journal()
    check_journal_absence(journal, names=[], target=target)
    for suffix in ("inline-0-1-intent.json", "thumb-2-not-applied.json", "add-1-ack.json"):
        with pytest.raises(ValueError, match="precondition"):
            check_journal_absence(
                journal, names=[f"single-{target.edition_id.hex}-{suffix}"], target=target
            )
    journal.write("a" * 64 + "-claim.json", {"binding": {"edition_id": str(target.edition_id)}})
    with pytest.raises(ValueError, match="precondition"):
        check_journal_absence(journal, names=list(journal.records), target=target)
