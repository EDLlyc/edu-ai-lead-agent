from __future__ import annotations

from uuid import UUID

from app.application.ports.governance import GovernanceRepository
from app.core.config import Settings
from app.core.errors import PolicyRejectedError
from app.domain.governance_entities import GovernanceVersionBundle


async def enqueue_governance_run(
    repository: GovernanceRepository,
    settings: Settings,
    bundle: GovernanceVersionBundle,
    *,
    acquisition_run_id: UUID | None,
    candidate_ids: tuple[UUID, ...],
    idempotency_key: str | None,
) -> UUID:
    if acquisition_run_id is not None:
        if candidate_ids:
            raise PolicyRejectedError(
                "invalid_governance_selection",
                "acquisition governance runs cannot include candidate IDs",
            )
        return await repository.create_run_for_acquisition(
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone=settings.business_timezone,
        )
    if idempotency_key is None:
        raise PolicyRejectedError(
            "missing_idempotency_key",
            "manual governance runs require an Idempotency-Key header",
        )
    return await repository.create_manual_run(
        candidate_ids=candidate_ids,
        idempotency_key=idempotency_key,
        bundle=bundle,
        timezone=settings.business_timezone,
    )
