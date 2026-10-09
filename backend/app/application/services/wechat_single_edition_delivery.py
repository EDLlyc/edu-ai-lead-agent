"""Persist every individual write intent and acknowledgement before advancing SQL."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from app.application.ports.official_account_single_edition import (
    SingleEdition,
    SingleEditionRepository,
)
from app.application.ports.wechat_official_account import (
    WeChatDraftArticleRequest,
    WeChatDraftCreated,
    WeChatInlineImage,
    WeChatMpOutcomeUnknownError,
    WeChatOfficialAccountDraftClient,
    WeChatOfficialAccountError,
    WeChatThumbMedia,
)
from app.application.ports.wechat_official_account_manual_draft import ManualDraftJournal, require
from app.application.services.official_account_single_edition import failed_progress
from app.application.services.wechat_official_account_draft import (
    WeChatOfficialAccountDraftOnlyService,
    WeChatPreparedDraft,
)
from app.domain.official_account_layout_templates import LAYOUT_TEMPLATE_VERSION, layout_template
from app.domain.official_account_strict_layout import strict_escaped_upload_url


def _fingerprint(value: object) -> str:
    import json

    return sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _media_id(value: object) -> str:
    import re

    require(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None,
        "single_journal_invalid_media",
    )
    assert isinstance(value, str)
    return value


class JournaledSingleDraftClient:
    """A missing ACK never permits replay; only authenticated rejection proves no effect."""

    def __init__(
        self,
        *,
        client: WeChatOfficialAccountDraftClient,
        journal: ManualDraftJournal,
        edition: SingleEdition,
        prepared: WeChatPreparedDraft,
        authorize: Callable[[], Awaitable[bool]],
        clock: Callable[[], datetime],
    ) -> None:
        self.client, self.journal, self.edition = client, journal, edition
        self.authorize, self.clock = authorize, clock
        self.ordinal = 0
        self.prefix = f"single-{edition.id.hex}"
        self.binding = _fingerprint(
            {
                "edition": str(edition.id),
                "article": prepared.article_fingerprint,
                "content": prepared.content_fingerprint,
                "account": edition.account,
                "policy": "single-write-journal-v1",
                "max_attempts": edition.max_attempts,
            }
        )
        claim_name = prepared.article_fingerprint + "-claim.json"
        claim = {
            "account": edition.account,
            "binding": {
                "version": "single-edition-claim-v1",
                "raw_article": prepared.article_fingerprint,
                "edition_id": str(edition.id),
                "fingerprint": self.binding,
            },
        }
        old = journal.read(claim_name)
        if old is None:
            journal.write(claim_name, claim)
        else:
            require(old == claim, "single_article_already_owned")

    async def _step(
        self, step: str, request: dict[str, Any], send: Callable[[], Awaitable[str]]
    ) -> str:
        for attempt in range(1, self.edition.max_attempts + 1):
            name = f"{self.prefix}-{step}-{attempt}"
            intent = {"binding": self.binding, "step": step, "attempt": attempt, "request": request}
            old = self.journal.read(name + "-intent.json")
            ack = self.journal.read(name + "-ack.json")
            failure = self.journal.read(name + "-not-applied.json")
            if old is not None:
                require(old == intent, "single_write_binding_changed")
                if ack is not None:
                    require(
                        failure is None and ack.get("intent_sha256") == _fingerprint(intent),
                        "single_ack_changed",
                    )
                    value = ack.get("value")
                    require(isinstance(value, str), "single_ack_changed")
                    assert isinstance(value, str)
                    return value
                if failure is None:
                    raise WeChatMpOutcomeUnknownError(endpoint="draft_add")
                require(
                    failure.get("intent_sha256") == _fingerprint(intent)
                    and failure.get("known_not_applied") is True,
                    "single_failure_changed",
                )
                continue
            require(ack is None and failure is None, "single_ack_without_intent")
            # Expiry forbids a new write, but existing ACKs above remain reconcilable forever.
            require(self.clock() < self.edition.expires_at, "single_delivery_expired")
            require(await self.authorize(), "single_delivery_lease_lost")
            self.journal.write(name + "-intent.json", intent)
            try:
                value = await send()
            except WeChatOfficialAccountError as error:
                # Semantic provider rejection codes only. HTTP 5xx and transport errors
                # are NOT proof of no effect, even if the legacy adapter says retryable.
                if not error.unknown and error.provider_code in {-1, 45009, 45011}:
                    self.journal.write(
                        name + "-not-applied.json",
                        {
                            "intent_sha256": _fingerprint(intent),
                            "known_not_applied": True,
                            "error_code": error.code,
                        },
                    )
                    raise
                raise WeChatMpOutcomeUnknownError(endpoint=error.endpoint or "draft_add") from None
            self.journal.write(
                name + "-ack.json", {"intent_sha256": _fingerprint(intent), "value": value}
            )
            return value
        raise WeChatOfficialAccountError("single_write_attempts_exhausted")

    async def upload_inline_image(
        self, image_bytes: bytes, media_type: str, filename: str
    ) -> WeChatInlineImage:
        step = f"inline-{self.ordinal}"
        self.ordinal += 1

        async def send() -> str:
            value = await self.client.upload_inline_image(image_bytes, media_type, filename)
            strict_escaped_upload_url(value.url)
            return value.url

        value = await self._step(
            step,
            {
                "sha256": sha256(image_bytes).hexdigest(),
                "media_type": media_type,
                "filename": filename,
            },
            send,
        )
        strict_escaped_upload_url(value)
        return WeChatInlineImage(value)

    async def upload_thumb(
        self, image_bytes: bytes, media_type: str, filename: str
    ) -> WeChatThumbMedia:
        async def send() -> str:
            value = await self.client.upload_thumb(image_bytes, media_type, filename)
            return _media_id(value.media_id)

        value = await self._step(
            "thumb",
            {
                "sha256": sha256(image_bytes).hexdigest(),
                "media_type": media_type,
                "filename": filename,
            },
            send,
        )
        return WeChatThumbMedia(_media_id(value))

    async def add_draft(self, article: WeChatDraftArticleRequest) -> WeChatDraftCreated:
        async def send() -> str:
            value = await self.client.add_draft(article)
            return _media_id(value.media_id)

        return WeChatDraftCreated(_media_id(await self._step("add", asdict(article), send)))


def _pinned_layout(journal: ManualDraftJournal, edition: SingleEdition, chosen: str | None) -> str:
    """The 排版模板 of an edition is fixed at its first delivery attempt.

    Every write intent records the article body, so a retry with another template would read
    as a changed binding; an operator switching templates only affects later editions.
    """

    name = f"single-{edition.id.hex}-layout.json"
    pinned = journal.read(name)
    if pinned is not None:
        template = pinned.get("template")
        require(isinstance(template, str), "single_layout_pin_changed")
        assert isinstance(template, str)
        return template
    template = layout_template(chosen).id
    journal.write(name, {"template": template, "version": LAYOUT_TEMPLATE_VERSION})
    return template


async def deliver_single(
    *,
    repository: SingleEditionRepository,
    edition: SingleEdition,
    prepared: WeChatPreparedDraft,
    journal: ManualDraftJournal,
    client: WeChatOfficialAccountDraftClient,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    layout_template_id: str | None = None,
) -> None:
    async def authorize() -> bool:
        return await repository.heartbeat(edition, now=clock(), lease_seconds=300)

    try:
        require(
            prepared.article_fingerprint == edition.article_fingerprint
            and prepared.content_fingerprint == edition.content_fingerprint,
            "single_prepared_identity_changed",
        )
        observed = JournaledSingleDraftClient(
            client=client,
            journal=journal,
            edition=edition,
            prepared=prepared,
            authorize=authorize,
            clock=clock,
        )
        receipt = await WeChatOfficialAccountDraftOnlyService(
            client=observed,
            clock=clock,
            layout_template_id=_pinned_layout(journal, edition, layout_template_id),
        ).create_prepared(prepared)
        await repository.save(
            replace(
                edition,
                status="delivered",
                error_code=None,
                receipt_fingerprint=sha256(receipt.draft_media_id.encode()).hexdigest(),
            ),
            now=clock(),
        )
    except WeChatOfficialAccountError as error:
        await repository.save(
            failed_progress(
                edition,
                stage="delivery",
                error_code=error.code,
                retryable=error.retryable,
                unknown=error.unknown,
                now=clock(),
            ),
            now=clock(),
        )
    except ValueError as error:
        code = str(error)
        allowed = {
            "single_delivery_expired",
            "single_delivery_lease_lost",
            "single_article_already_owned",
        }
        await repository.save(
            failed_progress(
                edition,
                stage="delivery",
                error_code=code if code in allowed else "single_journal_invalid",
                retryable=False,
                unknown=code != "single_delivery_expired",
                now=clock(),
            ),
            now=clock(),
        )
