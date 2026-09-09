"""Permit the prospective Chinese-family native prompt without altering native geometry.

Forward-only: frozen V5 weekly checkpoint files can predate every database row.
An SQL-only empty-table check cannot establish that a V4-only rollback is safe.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260909_0045"
down_revision: str | None = "20260907_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _shape() -> str:
    # Frozen copies of 0043's clauses. Only its native prompt predicate widens.
    common = (
        " AND block_index BETWEEN 0 AND 12"
        " AND block_kind IN ('paragraph','bullet_list','quote','callout')"
        " AND block_fingerprint ~ '^[0-9a-f]{64}$'"
        " AND reference_input_version = 'image-reference-input-v2-png-preserve-jpeg-normalize'"
        " AND reference_input_checksum ~ '^[0-9a-f]{64}$'"
        " AND output_profile_version = 'official-account-generated-body-publication-v2-3x2-jpeg')"
    )
    return (
        "(plan_version = 'official-account-generated-visual-plan-v1'"
        " AND prompt_version = 'official-account-generated-visual-prompt-v1'"
        " AND block_index IS NULL AND block_kind IS NULL AND block_fingerprint IS NULL"
        " AND reference_input_version IS NULL AND reference_input_checksum IS NULL"
        " AND output_profile_version IS NULL) OR "
        "(plan_version = 'official-account-generated-visual-plan-v2-block-anchor'"
        " AND prompt_version = 'official-account-generated-visual-prompt-v2-block-scene'"
        + common
        + " OR (plan_version = 'official-account-generated-visual-plan-v3-visible-ip'"
        " AND prompt_version = 'official-account-generated-visual-prompt-v3-visible-ip-block-scene'"
        + common
        + " OR (plan_version = 'official-account-generated-visual-plan-v4-native-strict'"
        " AND prompt_version IN ('official-account-generated-visual-prompt-v4-native-strict',"
        "'official-account-generated-visual-prompt-v5-chinese-family')"
        " AND block_index BETWEEN 0 AND 12"
        " AND block_kind IN ('paragraph','bullet_list','quote','callout')"
        " AND block_fingerprint ~ '^[0-9a-f]{64}$'"
        " AND reference_input_version = 'image-reference-input-v2-png-preserve-jpeg-normalize'"
        " AND reference_input_checksum ~ '^[0-9a-f]{64}$'"
        " AND output_profile_version = 'official-account-generated-body-jpeg-v2-native-strict')"
    )


def upgrade() -> None:
    name, table = "ck_official_generated_visuals_plan_shape", "official_account_generated_visuals"
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, _shape())


def downgrade() -> None:
    raise RuntimeError(
        "cannot downgrade Chinese-family visual prompt: frozen V5 weekly filesystem inputs "
        "may exist before database rows; retain V5-compatible code and schema"
    )
