"""One independent date; the producer never constructs a social/model client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.application.ports.official_account_single_edition import (
    SingleEdition,
    SingleEditionPlanner,
    SingleEditionRepository,
)
from app.application.services.official_account_weekly_production import (
    WeeklyProductionArticleRepository,
    WeeklyProductionCheckpointOwner,
    WeeklyProductionPreparedArtifacts,
)
from app.core.errors import ConflictError, NotFoundError
from app.domain.official_account_weekly_edition import WeeklyArticleRole


def failed_progress(
    edition: SingleEdition,
    *,
    stage: str,
    error_code: str,
    retryable: bool,
    now: datetime,
    unknown: bool = False,
) -> SingleEdition:
    attempts = dict(edition.attempts)
    attempts[stage] = attempts.get(stage, 0) + 1
    again = retryable and attempts[stage] < edition.max_attempts and now < edition.expires_at
    status = (
        edition.status if again else ("no_topic" if error_code == "single_no_topic" else "failed")
    )
    if unknown:
        status = "outcome_unknown"
    return replace(
        edition,
        status=status,
        attempts=attempts,
        error_code=error_code,
        available_at=now
        + timedelta(seconds=edition.retry_base_seconds * 2 ** (attempts[stage] - 1)),
    )


class SingleEditionProducer:
    def __init__(
        self,
        *,
        repository: SingleEditionRepository,
        planner: SingleEditionPlanner,
        article_repository: WeeklyProductionArticleRepository,
        artifacts: WeeklyProductionPreparedArtifacts,
        checkpoints: WeeklyProductionCheckpointOwner,
        account: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository, self.planner = repository, planner
        self.articles, self.artifacts, self.checkpoints = article_repository, artifacts, checkpoints
        self.account = account
        self.clock = clock or (lambda: datetime.now(UTC))

    async def process_once(self) -> bool:
        now = self.clock()
        edition = await self.repository.claim(
            account=self.account, delivery=False, now=now, lease_seconds=900
        )
        if edition is None:
            return False
        try:
            if edition.status == "admitted":
                item = await self.planner.plan_single(
                    cutoff=now, excluded_events=await self.repository.excluded_events(self.account)
                )
                if item is None:
                    await self.repository.save(
                        failed_progress(
                            edition,
                            stage="selection",
                            error_code="single_no_topic",
                            retryable=True,
                            now=self.clock(),
                        ),
                        now=self.clock(),
                    )
                    return True
                artifact = self.checkpoints.put_json(
                    {
                        "version": "single-edition-selection-v1",
                        "edition_id": str(edition.id),
                        "cutoff": now.isoformat(),
                        "item": item.as_dict(),
                    }
                )
                if not await self.repository.select(edition, item, artifact, now=self.clock()):
                    # A competing date/route reserved this event; the next tick selects another.
                    await self.repository.save(
                        replace(edition, available_at=self.clock() + timedelta(seconds=2)),
                        now=self.clock(),
                    )
                return True
            if edition.status == "generating":
                if edition.article_run_id is None:
                    assert edition.material_package_id is not None
                    run, _ = await self.articles.enqueue_material_package(
                        material_package_id=edition.material_package_id,
                        identity=edition.identity,
                        execution_retry_policy={
                            "version": "single-edition-article-retry-v1",
                            "max_attempts": edition.max_attempts,
                            "retry_base_seconds": edition.retry_base_seconds,
                            "expires_at": edition.expires_at.isoformat(),
                        },
                    )
                    edition = replace(edition, article_run_id=run.id)
                assert edition.article_run_id is not None
                run = await self.articles.get_run(edition.article_run_id)
                if run.status == "ready":
                    edition = replace(edition, status="preparing", error_code=None)
                elif run.status in {"review_required", "failed", "result_unknown"}:
                    edition = replace(
                        edition,
                        status="outcome_unknown" if run.status == "result_unknown" else "failed",
                        error_code=f"single_article_{run.status}",
                    )
                else:
                    # Observing persisted generation is not a new model attempt.
                    edition = replace(edition, available_at=self.clock() + timedelta(seconds=5))
                await self.repository.save(edition, now=self.clock())
                return True
            if edition.status == "preparing":
                assert edition.article_run_id is not None and edition.role is not None
                role = WeeklyArticleRole(edition.role)
                artifact = await self.artifacts.build_child(
                    run_id=edition.article_run_id, role=role
                )
                prepared = self.artifacts.validate_child(artifact, role=role)
                edition = replace(
                    edition,
                    prepared_artifact=artifact,
                    article_fingerprint=prepared.article_fingerprint,
                    content_fingerprint=prepared.content_fingerprint,
                )
                if not await self.repository.reserve_article(edition, now=self.clock()):
                    edition = replace(
                        edition, status="failed", error_code="single_article_already_owned"
                    )
                else:
                    edition = replace(
                        edition, status="ready", available_at=edition.deliver_at, error_code=None
                    )
                await self.repository.save(edition, now=self.clock())
                return True
            raise ValueError("single producer state invalid")
        except (ConflictError, NotFoundError, ValueError):
            await self.repository.save(
                failed_progress(
                    edition,
                    stage=edition.status,
                    error_code="single_preparation_invalid",
                    retryable=False,
                    now=self.clock(),
                ),
                now=self.clock(),
            )
            return True
        except OSError:
            await self.repository.save(
                failed_progress(
                    edition,
                    stage=edition.status,
                    error_code="single_artifact_unavailable",
                    retryable=True,
                    now=self.clock(),
                ),
                now=self.clock(),
            )
            return True
