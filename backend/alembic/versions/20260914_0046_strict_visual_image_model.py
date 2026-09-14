"""Permit the current Comfly relay model while preserving legacy strict visuals.

Only the strict generated-visual model predicate changes. Historical rows are not rewritten.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0046"
down_revision: str | None = "20260909_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "official_account_generated_visuals"
_CONSTRAINT = "ck_official_generated_visuals_native_intent"
_LEGACY_MODEL = "gpt-image-2"
_CURRENT_MODEL = "gpt-image-2.5-sunburst"


def _native_intent_constraint(*, model_predicate: str) -> str:
    return (
        "(plan_version = 'official-account-generated-visual-plan-v4-native-strict' "
        "AND output_size IS NOT NULL AND output_size = '1536x1024' "
        "AND intent_lease_token IS NOT NULL AND intent_attempt_number IS NOT NULL "
        "AND intent_attempt_number > 0 AND provider = 'comfly' "
        f"AND {model_predicate} "
        "AND block_index IS NOT NULL AND block_kind IS NOT NULL "
        "AND block_fingerprint IS NOT NULL "
        "AND reference_input_version IS NOT NULL AND reference_input_checksum IS NOT NULL "
        "AND output_profile_version IS NOT NULL "
        "AND (status <> 'ready' OR (width IS NOT NULL AND height IS NOT NULL "
        "AND media_type IS NOT NULL AND width = 1536 AND height = 1024 "
        "AND media_type = 'image/jpeg'))) OR "
        "(plan_version <> 'official-account-generated-visual-plan-v4-native-strict' "
        "AND output_size IS NULL AND intent_lease_token IS NULL "
        "AND intent_attempt_number IS NULL)"
    )


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        _native_intent_constraint(
            model_predicate=(f"model IN ('{_LEGACY_MODEL}', '{_CURRENT_MODEL}')")
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {_TABLE} "
            f"WHERE plan_version = 'official-account-generated-visual-plan-v4-native-strict' "
            f"AND model = '{_CURRENT_MODEL}') THEN "
            "RAISE EXCEPTION 'cannot downgrade populated current strict visual image model'; "
            "END IF; END $$"
        )
    )
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        _native_intent_constraint(model_predicate=f"model = '{_LEGACY_MODEL}'"),
    )
