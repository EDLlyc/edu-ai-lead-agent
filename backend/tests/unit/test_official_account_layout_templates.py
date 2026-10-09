from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
from app.application.ports.wechat_official_account import WeChatMpTransientError
from app.application.services.wechat_single_edition_delivery import deliver_single
from app.domain.official_account_layout_templates import (
    DEFAULT_LAYOUT_TEMPLATE_ID,
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
async def test_without_a_choice_the_draft_is_byte_identical(tmp_path):
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
        )
    finally:
        journal.close()
    assert client.article.content == (
        '<section style="color:#0D57C8"><img src="https://mmbiz.qpic.cn/test.jpg"/></section>'
    )
