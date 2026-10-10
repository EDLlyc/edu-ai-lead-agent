from __future__ import annotations

import re
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.application.ports.wechat_official_account import (
    WeChatMpOutcomeUnknownError,
    WeChatMpTransientError,
)
from app.application.services.wechat_official_account_draft import (
    WeChatOfficialAccountDraftOnlyService,
)
from app.application.services.wechat_single_edition_delivery import (
    JournaledSingleDraftClient,
    deliver_single,
)
from app.domain.official_account_layout_templates import (
    DEFAULT_LAYOUT_TEMPLATE_ID,
    LAYOUT_TEMPLATE_VERSION,
    LAYOUT_TEMPLATES,
    RENDERER_COLOURS,
    apply_layout_template,
    layout_template,
)
from app.infrastructure.wechat_official_account.manual_journal import LocalManualDraftJournal
from test_official_account_single_edition import (
    ACCOUNT,
    NOW,
    Client,
    Repository,
    edition,
    prepared,
)

SAMPLE = (
    Path(__file__).resolve().parents[2] / "app" / "assets" / "official_account_layout_sample.html"
).read_text(encoding="utf-8")
HEX = re.compile(r"#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])")
# Colours the renderer uses for text, with the background each sits on.
TEXT_ON = (
    ("#0D57C8", "#FFFFFF"),
    ("#285ACE", "#FFFFFF"),
    ("#B85A00", "#FFFFFF"),
    ("#26364A", "#FFFFFF"),
    ("#607086", "#FFFFFF"),
    ("#0D57C8", "#EAF7FF"),
    ("#26364A", "#F3FBFF"),
)


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_the_sample_uses_exactly_the_renderer_colours():
    # A renderer change that adds a colour must be added to every template too.
    assert {match.upper() for match in HEX.findall(SAMPLE)} == set(RENDERER_COLOURS)


def test_the_default_and_unknown_templates_leave_the_body_untouched():
    assert apply_layout_template(SAMPLE, None) is SAMPLE
    assert apply_layout_template(SAMPLE, DEFAULT_LAYOUT_TEMPLATE_ID) is SAMPLE
    assert apply_layout_template(SAMPLE, "no-such-template") is SAMPLE


@pytest.mark.parametrize("template", LAYOUT_TEMPLATES[1:], ids=lambda t: t.id)
def test_a_template_only_swaps_colours(template):
    themed = apply_layout_template(SAMPLE, template.id)
    assert len(themed) == len(SAMPLE)
    assert HEX.sub("#000000", themed) == HEX.sub("#000000", SAMPLE)
    for original, replacement in template.colours.items():
        assert original not in themed.upper() or original in template.colours.values()
        assert replacement in themed


@pytest.mark.parametrize("template", LAYOUT_TEMPLATES, ids=lambda t: t.id)
def test_text_stays_readable(template):
    for text, background in TEXT_ON:
        before = _contrast(text, background)
        after = _contrast(template.colour(text), template.colour(background))
        assert after >= min(4.5, before), (template.id, text, after)


def test_every_template_has_four_swatches_and_a_name():
    assert len({template.id for template in LAYOUT_TEMPLATES}) == len(LAYOUT_TEMPLATES)
    for template in LAYOUT_TEMPLATES:
        assert len(template.swatches) == 4
        assert template.name and template.description
        assert re.fullmatch(r"[a-z0-9-]{1,40}", template.id)
    assert layout_template("unknown").id == DEFAULT_LAYOUT_TEMPLATE_ID


def _coloured():
    return replace(
        prepared(),
        body_html='<section style="color:#0D57C8"><img src="assets/body.jpg"/></section>',
    )


@pytest.mark.asyncio
async def test_delivery_applies_the_chosen_template(tmp_path):
    client = Client()
    repository = Repository()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await deliver_single(
            repository=repository,
            edition=edition(),
            prepared=_coloured(),
            journal=journal,
            client=client,
            clock=lambda: NOW,
            layout_template_id="jade-green",
        )
    finally:
        journal.close()
    assert repository.value.status == "delivered"
    assert 'style="color:#0B7A64"' in client.article.content


@pytest.mark.asyncio
async def test_a_retry_keeps_the_template_of_the_first_attempt(tmp_path):
    first = Client(WeChatMpTransientError(endpoint="material_add_thumb", provider_code=-1))
    repository = Repository()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await deliver_single(
            repository=repository,
            edition=edition(),
            prepared=_coloured(),
            journal=journal,
            client=first,
            clock=lambda: NOW,
            layout_template_id="jade-green",
        )
    finally:
        journal.close()
    assert repository.value.status == "delivering"
    # The operator switches template between the attempts; this edition keeps its first one.
    second = Client()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await deliver_single(
            repository=repository,
            edition=repository.value,
            prepared=_coloured(),
            journal=journal,
            client=second,
            clock=lambda: NOW,
            layout_template_id="ink",
        )
    finally:
        journal.close()
    assert repository.value.status == "delivered"
    assert 'style="color:#0B7A64"' in second.article.content


@pytest.mark.asyncio
@pytest.mark.parametrize("chosen", [None, "unknown-template"])
async def test_without_a_valid_choice_the_draft_is_byte_identical(tmp_path, chosen):
    client = Client()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await deliver_single(
            repository=Repository(),
            edition=edition(),
            prepared=_coloured(),
            journal=journal,
            client=client,
            clock=lambda: NOW,
            layout_template_id=chosen,
        )
    finally:
        journal.close()
    assert client.article.content == (
        '<section style="color:#0D57C8"><img src="https://mmbiz.qpic.cn/test.jpg"/></section>'
    )


def _legacy_body(with_media):
    body = _coloured()
    return (
        body
        if with_media
        else replace(body, body_html='<section style="color:#0D57C8">正文</section>', body_media=())
    )


async def _legacy_attempt(journal, value, body, client):
    # Run the pre-template path: durable claim/intents/ACKs, but no layout pin.
    observed = JournaledSingleDraftClient(
        client=client,
        journal=journal,
        edition=value,
        prepared=body,
        authorize=AsyncMock(return_value=True),
        clock=lambda: NOW,
    )
    return await WeChatOfficialAccountDraftOnlyService(
        client=observed, clock=lambda: NOW
    ).create_prepared(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_media", [True, False])
async def test_pre_template_add_ack_reconciles_after_expiry_without_rewriting_history(
    tmp_path, with_media
):
    value, body, original = edition(), _legacy_body(with_media), Client()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    pin = f"single-{value.id.hex}-layout.json"
    try:
        await _legacy_attempt(journal, value, body, original)
        assert journal.read(pin) is None
        original_files = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
        retry, repository = Client(), Repository()
        await deliver_single(
            repository=repository,
            edition=value,
            prepared=body,
            journal=journal,
            client=retry,
            clock=lambda: NOW + timedelta(days=1),
            layout_template_id="jade-green",
        )
        assert retry.calls == []
        assert repository.value.status == "delivered"
        assert repository.value.receipt_fingerprint == sha256(b"draft_id").hexdigest()
        assert journal.read(pin) == {
            "template": DEFAULT_LAYOUT_TEMPLATE_ID,
            "version": LAYOUT_TEMPLATE_VERSION,
        }
        assert all(path.read_bytes() == contents for path, contents in original_files.items())
    finally:
        journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_media", [True, False])
@pytest.mark.parametrize("rejected_step", ["thumb", "add"])
async def test_pre_template_rejected_attempt_keeps_default_and_reuses_media(
    tmp_path, with_media, rejected_step
):
    value, body = edition(), _legacy_body(with_media)
    rejection = WeChatMpTransientError(endpoint="draft_add", provider_code=-1)
    original = Client(rejection if rejected_step == "thumb" else None)
    if rejected_step == "add":
        original.add_draft = AsyncMock(side_effect=rejection)
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        with pytest.raises(WeChatMpTransientError):
            await _legacy_attempt(journal, value, body, original)
        retry, repository = Client(), Repository()
        await deliver_single(
            repository=repository,
            edition=value,
            prepared=body,
            journal=journal,
            client=retry,
            clock=lambda: NOW + timedelta(minutes=1),
            layout_template_id="jade-green",
        )
        assert retry.calls == (["thumb", "add"] if rejected_step == "thumb" else ["add"])
        assert repository.value.status == "delivered"
        assert 'style="color:#0D57C8"' in retry.article.content
        assert journal.read(f"single-{value.id.hex}-layout.json")["template"] == (
            DEFAULT_LAYOUT_TEMPLATE_ID
        )
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_pre_template_unknown_add_remains_unknown_without_replay(tmp_path):
    value, body, original = edition(), _coloured(), Client()
    original.add_draft = AsyncMock(side_effect=WeChatMpTransientError(endpoint="draft_add"))
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        with pytest.raises(WeChatMpOutcomeUnknownError):
            await _legacy_attempt(journal, value, body, original)
        retry, repository = Client(), Repository()
        await deliver_single(
            repository=repository,
            edition=value,
            prepared=body,
            journal=journal,
            client=retry,
            clock=lambda: NOW + timedelta(days=1),
            layout_template_id="jade-green",
        )
        assert original.add_draft.await_count == 1
        assert retry.calls == []
        assert repository.value.status == "outcome_unknown"
        assert repository.value.error_code == "wechat_mp_outcome_unknown"
    finally:
        journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pin",
    [
        {"template": "jade-green"},
        {"template": "jade-green", "version": "official-account-layout-template-v2"},
        {"template": "unknown", "version": LAYOUT_TEMPLATE_VERSION},
        {"template": None, "version": LAYOUT_TEMPLATE_VERSION},
        {"template": 1, "version": LAYOUT_TEMPLATE_VERSION},
    ],
)
async def test_invalid_layout_pin_fails_closed_before_provider_calls(tmp_path, pin):
    value, client, repository = edition(), Client(), Repository()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    name = f"single-{value.id.hex}-layout.json"
    try:
        journal.write(name, pin)
        await deliver_single(
            repository=repository,
            edition=value,
            prepared=_coloured(),
            journal=journal,
            client=client,
            clock=lambda: NOW,
            layout_template_id="jade-green",
        )
        assert client.calls == []
        assert repository.value.status == "outcome_unknown"
        assert repository.value.error_code == "single_journal_invalid"
        assert journal.read(name) == pin
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_layout_recovery_cannot_accept_another_editions_claim(tmp_path):
    value, body = edition(), _coloured()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await _legacy_attempt(journal, value, body, Client())
        other = replace(value, id=uuid4())
        client, repository = Client(), Repository()
        await deliver_single(
            repository=repository,
            edition=other,
            prepared=body,
            journal=journal,
            client=client,
            clock=lambda: NOW,
            layout_template_id="jade-green",
        )
        assert client.calls == []
        assert repository.value.error_code == "single_article_already_owned"
        assert journal.read(f"single-{other.id.hex}-layout.json") is None
    finally:
        journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_field", ["binding", "step", "attempt", "request"])
async def test_layout_recovery_rejects_a_malformed_legacy_intent(tmp_path, invalid_field):
    value, body, client, repository = edition(), _coloured(), Client(), Repository()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        observed = JournaledSingleDraftClient(
            client=client,
            journal=journal,
            edition=value,
            prepared=body,
            authorize=AsyncMock(return_value=True),
            clock=lambda: NOW,
        )
        intent = {"binding": observed.binding, "step": "thumb", "attempt": 1, "request": {}}
        intent[invalid_field] = None
        journal.write(f"single-{value.id.hex}-thumb-1-intent.json", intent)
        await deliver_single(
            repository=repository,
            edition=value,
            prepared=body,
            journal=journal,
            client=client,
            clock=lambda: NOW,
            layout_template_id="jade-green",
        )
        assert client.calls == []
        assert repository.value.status == "outcome_unknown"
        assert repository.value.error_code == "single_journal_invalid"
        assert journal.read(f"single-{value.id.hex}-layout.json") is None
    finally:
        journal.close()
