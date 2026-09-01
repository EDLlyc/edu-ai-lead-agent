"""Deterministic V2 projections for the local WeChat editor handoff."""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional rendered copy.

from __future__ import annotations

import json
import re
from hashlib import sha256
from html import escape
from typing import Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import official_account_editor_handoff as v1
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V2
from app.domain.official_account_editor_handoff import (
    EditorHandoffCheck,
    EditorHandoffMediaAsset,
)
from app.domain.official_account_editor_handoff_theme import (
    XIAOSAI_GZH_THEME_ID,
    XIAOSAI_GZH_THEME_SHA256,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
    fingerprint,
)

EDITOR_HANDOFF_V2_RENDERER_VERSION: Final = "wechat-editor-handoff-renderer-v2-gzh-xiaosai-semantic"
EDITOR_HANDOFF_V2_STYLE_VERSION: Final = "wechat-editor-handoff-style-v2-xiaosai-adaptive"
EDITOR_HANDOFF_V2_TEMPLATE_VERSION: Final = (
    "wechat-editor-handoff-template-v2-block-interleaved-mobile"
)
EDITOR_HANDOFF_V2_BUNDLE_VERSION: Final = "official-account-editor-handoff-bundle-v2"
EDITOR_HANDOFF_V2_PREFLIGHT_VERSION: Final = "wechat-editor-handoff-preflight-v2"
EDITOR_HANDOFF_V2_RELEASE_POLICY_VERSION: Final = "editor-handoff-release-policy-v2"
EDITOR_HANDOFF_V2_PLACEMENT_VERSION: Final = "editor-handoff-context-placement-v2"
EDITOR_HANDOFF_V2_EMPHASIS_VERSION: Final = "editor-handoff-semantic-emphasis-v2"
EDITOR_HANDOFF_V2_RECIPE_VERSION: Final = "editor-handoff-layout-recipe-v2"
EDITOR_HANDOFF_V2_MOBILE_VERSION: Final = "editor-handoff-mobile-binding-v2"
EDITOR_HANDOFF_V2_BODY_VISUAL_VERSION: Final = "editor-handoff-body-visual-lineage-v1"

_VISIBLE_BLOCK_TYPES = (ArticleParagraphBlock, ArticleBulletListBlock, ArticleQuoteBlock)
_CLAUSE_RE = re.compile(r"[^，。！？；：,.!?;:\n]+")
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d{1,4}(?:\.\d+)?(?:%|％|年|月|日|分钟|小时)")
_CONNECTIVE_RE = re.compile(
    r"(?:但是|而是|因为|所以|同时|如果|那么|通过|从而|以及|并且|这意味着|换句话说|也许)"
)
_BAD_STARTS = ("的", "了", "着", "而", "也", "就", "在", "与", "和", "或", "把", "让", "从")
_BAD_ENDS = ("的", "了", "着", "而", "也", "和", "与", "或", "在", "把", "让", "从", "一")
_GENERIC_UNITS = frozenset({"提醒我们", "值得注意", "需要指出", "可以看出", "不难发现"})
_KNOWN_TERMS = (
    "人工智能",
    "科创教育",
    "底层竞争力",
    "问题意识",
    "科学思维",
    "真实问题",
    "动手实践",
    "证据链",
    "学习能力",
    "自主判断",
    "AI时代",
)
SemanticEmphasisReason = Literal["context_overlap", "known_term", "numeric", "informative_phrase"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EditorHandoffV2Identity(_FrozenModel):
    renderer_version: Literal["wechat-editor-handoff-renderer-v2-gzh-xiaosai-semantic"] = (
        EDITOR_HANDOFF_V2_RENDERER_VERSION
    )
    style_version: Literal["wechat-editor-handoff-style-v2-xiaosai-adaptive"] = (
        EDITOR_HANDOFF_V2_STYLE_VERSION
    )
    template_version: Literal["wechat-editor-handoff-template-v2-block-interleaved-mobile"] = (
        EDITOR_HANDOFF_V2_TEMPLATE_VERSION
    )
    bundle_version: Literal["official-account-editor-handoff-bundle-v2"] = (
        EDITOR_HANDOFF_V2_BUNDLE_VERSION
    )
    preflight_version: Literal["wechat-editor-handoff-preflight-v2"] = (
        EDITOR_HANDOFF_V2_PREFLIGHT_VERSION
    )
    release_policy_version: Literal["editor-handoff-release-policy-v2"] = (
        EDITOR_HANDOFF_V2_RELEASE_POLICY_VERSION
    )
    placement_version: Literal["editor-handoff-context-placement-v2"] = (
        EDITOR_HANDOFF_V2_PLACEMENT_VERSION
    )
    emphasis_version: Literal["editor-handoff-semantic-emphasis-v2"] = (
        EDITOR_HANDOFF_V2_EMPHASIS_VERSION
    )
    recipe_version: Literal["editor-handoff-layout-recipe-v2"] = EDITOR_HANDOFF_V2_RECIPE_VERSION
    mobile_binding_version: Literal["editor-handoff-mobile-binding-v2"] = (
        EDITOR_HANDOFF_V2_MOBILE_VERSION
    )
    body_visual_lineage_version: Literal["editor-handoff-body-visual-lineage-v1"] = (
        EDITOR_HANDOFF_V2_BODY_VISUAL_VERSION
    )
    rights_policy_version: Literal["editor-handoff-context-rights-v1-direct-use-disclosed"] = (
        v1.EDITOR_HANDOFF_RIGHTS_POLICY_VERSION
    )
    theme_id: Literal["xiaosai-moyu-layout-v1"] = XIAOSAI_GZH_THEME_ID
    theme_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", default=XIAOSAI_GZH_THEME_SHA256)


class EditorHandoffRelease(_FrozenModel):
    policy: Literal["manual_only", "quality_auto"]
    policy_version: Literal["editor-handoff-release-policy-v2"] = (
        EDITOR_HANDOFF_V2_RELEASE_POLICY_VERSION
    )
    kind: Literal["manual", "machine"]
    decision: Literal["released"] = "released"
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_codes: tuple[str, ...] = Field(min_length=1)
    manual_review_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_truth(self) -> EditorHandoffRelease:
        if self.kind == "manual" and self.manual_review_fingerprint is None:
            raise ValueError("manual release requires a manual review fingerprint")
        if self.kind == "machine" and self.manual_review_fingerprint is not None:
            raise ValueError("machine release cannot claim a manual review fingerprint")
        return self


class SemanticEmphasisSpan(_FrozenModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=4, max_length=15)
    reason: SemanticEmphasisReason
    score: int = Field(ge=1, le=1_000)

    @model_validator(mode="after")
    def validate_bounds(self) -> SemanticEmphasisSpan:
        if self.end <= self.start or self.end - self.start != len(self.text):
            raise ValueError("semantic emphasis bounds are invalid")
        return self


class SemanticEmphasisBlock(_FrozenModel):
    block_path: str = Field(
        pattern=r"^(?:lead|conclusion|section-[0-6]-block-[0-9]+(?:-item-[0-9]+)?)$"
    )
    source_text: str = Field(min_length=1)
    spans: tuple[SemanticEmphasisSpan, ...] = Field(max_length=3)


class ContextBlockPlacement(_FrozenModel):
    media_path: str = Field(pattern=r"^assets/context-0[01]\.(?:jpg|png|webp)$")
    section_index: int = Field(ge=0, le=6)
    target_block_index: int = Field(ge=0, le=49)
    insertion: Literal["after"] = "after"
    reason_code: Literal["semantic_text_overlap", "first_prose_fallback", "collision_shifted"]
    algorithm_version: Literal["editor-handoff-context-placement-v2"] = (
        EDITOR_HANDOFF_V2_PLACEMENT_VERSION
    )
    matched_terms: tuple[str, ...] = Field(default=(), max_length=6)


CharacterLabel = Literal["xiao-sai", "sai-xiansheng"]


class BodyVisualReferenceProjection(_FrozenModel):
    public_ref: str = Field(pattern=r"^[0-9a-f]{16}$")
    catalog_version: str = Field(min_length=1, max_length=80)
    role: Literal["action_reference", "identity_reference"]
    character_labels: tuple[CharacterLabel, ...] = Field(min_length=1, max_length=2)
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_version: Literal["image-reference-input-v2-png-preserve-jpeg-normalize"] = cast(
        Literal["image-reference-input-v2-png-preserve-jpeg-normalize"],
        IMAGE_REFERENCE_INPUT_V2,
    )
    input_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_characters(self) -> BodyVisualReferenceProjection:
        if len(set(self.character_labels)) != len(self.character_labels):
            raise ValueError("body-visual reference character labels must be unique")
        return self


class BodyVisualLineage(_FrozenModel):
    version: Literal["editor-handoff-body-visual-lineage-v1"] = (
        EDITOR_HANDOFF_V2_BODY_VISUAL_VERSION
    )
    ordinal: int = Field(ge=0, le=4)
    section_index: int = Field(ge=0, le=6)
    block_index: int = Field(ge=0, le=12)
    block_kind: Literal["paragraph", "bullet_list", "quote", "callout"]
    block_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    scene_brief: str = Field(min_length=8, max_length=480)
    scene_brief_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference: BodyVisualReferenceProjection
    selection_method: Literal[
        "deterministic_tag",
        "deterministic_fixture_semantic",
        "multimodal_embedding",
    ]
    similarity_band: Literal["very_high", "high", "medium", "low"] | None = None
    generation_kind: Literal[
        "frozen_reference_conditioned_fixture",
        "persisted_reference_conditioned_output",
    ]
    provider_execution: Literal[
        "not_claimed",
        "authorized_local_imagegen_result",
        "persisted_result",
    ]
    plan_version: Literal["official-account-generated-visual-plan-v3-visible-ip"] = cast(
        Literal["official-account-generated-visual-plan-v3-visible-ip"],
        OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    )
    prompt_version: Literal[
        "official-account-generated-visual-prompt-v3-visible-ip-block-scene"
    ] = cast(
        Literal["official-account-generated-visual-prompt-v3-visible-ip-block-scene"],
        OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    )
    output_profile_version: Literal["official-account-generated-body-publication-v2-3x2-jpeg"] = (
        cast(
            Literal["official-account-generated-body-publication-v2-3x2-jpeg"],
            OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION,
        )
    )
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_media_type: Literal["image/jpeg"] = "image/jpeg"
    output_byte_size: int = Field(ge=1, le=15 * 1024 * 1024)
    output_width: Literal[1536] = 1536
    output_height: Literal[1024] = 1024
    visible_character_labels: tuple[CharacterLabel, ...] = Field(min_length=1, max_length=2)
    visibility_status: Literal[
        "passed_local_visual_inspection",
        "durable_image_audit_accepted",
    ]

    @model_validator(mode="after")
    def validate_truth(self) -> BodyVisualLineage:
        semantic = self.selection_method == "multimodal_embedding"
        if semantic != (self.similarity_band is not None):
            raise ValueError("body-visual semantic selection truth is inconsistent")
        if self.generation_kind == "frozen_reference_conditioned_fixture":
            if self.provider_execution not in {
                "not_claimed",
                "authorized_local_imagegen_result",
            }:
                raise ValueError("frozen body visual provider execution is invalid")
            if self.visibility_status != "passed_local_visual_inspection":
                raise ValueError("frozen body visual requires local visibility evidence")
        elif self.provider_execution != "persisted_result":
            raise ValueError("persisted body visual requires a durable provider result")
        if len(set(self.visible_character_labels)) != len(self.visible_character_labels):
            raise ValueError("visible body-visual character labels must be unique")
        expected_brief_fingerprint = fingerprint_v2(
            "editor-handoff-body-visual-scene-brief-v1",
            self.section_index,
            self.block_index,
            self.block_kind,
            self.scene_brief,
        )
        if self.scene_brief_fingerprint != expected_brief_fingerprint:
            raise ValueError("body-visual scene brief fingerprint changed")
        return self


class EditorHandoffLayoutRecipe(_FrozenModel):
    kind: Literal["news_analysis", "tutorial_list", "case_opinion", "analysis"]
    version: Literal["editor-handoff-layout-recipe-v2"] = EDITOR_HANDOFF_V2_RECIPE_VERSION
    title_size_px: Literal[21, 24, 28]
    toc_width_px: Literal[104, 126, 148]
    toc_size_px: Literal[11, 12, 13]
    deep_anchor_limit: Literal[5] = 5


class EditorHandoffMobileValidation(_FrozenModel):
    status: Literal["not_run", "passed"]
    version: Literal["editor-handoff-mobile-binding-v2"] = EDITOR_HANDOFF_V2_MOBILE_VERSION
    content_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    body_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    media_sha256s: tuple[str, ...] = ()
    viewports: tuple[Literal[320], Literal[430]] = (320, 430)
    external_requests: Literal[0] | None = None
    copy_root_matches_body: Literal[True] | None = None

    @model_validator(mode="after")
    def validate_binding(self) -> EditorHandoffMobileValidation:
        bindings = (self.content_fingerprint, self.body_sha256)
        if self.status == "passed":
            if (
                None in bindings
                or not self.media_sha256s
                or self.external_requests != 0
                or self.copy_root_matches_body is not True
            ):
                raise ValueError("passed mobile validation requires exact content bindings")
        elif any(item is not None for item in bindings) or self.media_sha256s:
            raise ValueError("not-run mobile validation cannot claim content bindings")
        return self


class EditorHandoffV2Preflight(_FrozenModel):
    rule_version: Literal["wechat-editor-handoff-preflight-v2"] = (
        EDITOR_HANDOFF_V2_PREFLIGHT_VERSION
    )
    passed: bool
    checks: tuple[EditorHandoffCheck, ...]
    blocking_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]


class RenderedEditorHandoffV2(_FrozenModel):
    body_html: str
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe: EditorHandoffLayoutRecipe
    placements: tuple[ContextBlockPlacement, ...]
    emphasis: tuple[SemanticEmphasisBlock, ...]


def select_layout_recipe(
    article: ArticlePackage, media: tuple[EditorHandoffMediaAsset, ...]
) -> EditorHandoffLayoutRecipe:
    visible_count = 0
    bullet_count = 0
    quote_count = 0
    for section in article.sections:
        for block in section.blocks:
            if isinstance(block, _VISIBLE_BLOCK_TYPES):
                visible_count += 1
            if isinstance(block, ArticleBulletListBlock):
                bullet_count += 1
            elif isinstance(block, ArticleQuoteBlock):
                quote_count += 1
    if any(item.role == "context" for item in media):
        kind: Literal["news_analysis", "tutorial_list", "case_opinion", "analysis"] = (
            "news_analysis"
        )
    elif bullet_count >= max(2, visible_count // 3):
        kind = "tutorial_list"
    elif quote_count >= 2:
        kind = "case_opinion"
    else:
        kind = "analysis"
    title_length = len(article.title.strip())
    title_size: Literal[21, 24, 28] = 28 if title_length <= 16 else 24 if title_length <= 24 else 21
    longest_toc = max((len(item.heading.strip()) for item in article.sections[:3]), default=0)
    toc_width: Literal[104, 126, 148] = (
        104 if longest_toc <= 10 else 126 if longest_toc <= 18 else 148
    )
    toc_size: Literal[11, 12, 13] = 13 if longest_toc <= 10 else 12 if longest_toc <= 18 else 11
    return EditorHandoffLayoutRecipe(
        kind=kind,
        title_size_px=title_size,
        toc_width_px=toc_width,
        toc_size_px=toc_size,
    )


def select_semantic_emphasis(
    text: str, *, context_terms: tuple[str, ...] = ()
) -> tuple[SemanticEmphasisSpan, ...]:
    """Select exact, non-overlapping substrings without rewriting source text."""
    candidates: dict[tuple[int, int], tuple[int, SemanticEmphasisReason]] = {}

    def offer(start: int, end: int, score: int, reason: SemanticEmphasisReason) -> None:
        value = text[start:end]
        if (
            not 4 <= len(value) <= 15
            or not value.strip()
            or value in _GENERIC_UNITS
            or value.startswith(_BAD_STARTS)
            or value.endswith(_BAD_ENDS)
            or value.count("“") != value.count("”")
        ):
            return
        key = (start, end)
        current = candidates.get(key)
        if current is None or score > current[0]:
            candidates[key] = (score, reason)

    for term in (*context_terms, *_KNOWN_TERMS):
        normalized = term.strip()
        if not 4 <= len(normalized) <= 15:
            continue
        start = text.find(normalized)
        while start >= 0:
            offer(
                start,
                start + len(normalized),
                900 if normalized in context_terms else 760,
                "context_overlap" if normalized in context_terms else "known_term",
            )
            start = text.find(normalized, start + 1)
    for match in _NUMBER_RE.finditer(text):
        offer(match.start(), match.end(), 680, "numeric")
    for match in _CLAUSE_RE.finditer(text):
        clause = match.group()
        for unit, relative_start in _whole_semantic_units(clause):
            offset = match.start() + relative_start
            informative = len(set(unit)) + sum(char.isdigit() for char in unit) * 2
            offer(offset, offset + len(unit), 300 + informative, "informative_phrase")

    selected: list[tuple[int, int, int, SemanticEmphasisReason]] = []
    limit = 3 if len(text) >= 120 else 2
    for (start, end), (score, reason) in sorted(
        candidates.items(), key=lambda item: (-item[1][0], item[0][0], -(item[0][1] - item[0][0]))
    ):
        if any(
            not (end <= other_start or start >= other_end)
            for other_start, other_end, _, _ in selected
        ):
            continue
        selected.append((start, end, score, reason))
        if len(selected) == limit:
            break
    return tuple(
        SemanticEmphasisSpan(
            start=start,
            end=end,
            text=text[start:end],
            score=score,
            reason=reason,
        )
        for start, end, score, reason in sorted(selected)
    )


def plan_context_placements(
    *, article: ArticlePackage, media: tuple[EditorHandoffMediaAsset, ...]
) -> tuple[ContextBlockPlacement, ...]:
    planned: list[ContextBlockPlacement] = []
    used: dict[int, list[int]] = {}
    contexts = sorted(
        (item for item in media if item.role == "context"), key=lambda item: item.ordinal
    )
    for asset in contexts:
        if asset.assigned_section_index is None:
            raise ValueError("context media requires a section anchor")
        section_index = asset.assigned_section_index
        if section_index >= len(article.sections):
            raise ValueError("context media section anchor is out of range")
        blocks = article.sections[section_index].blocks
        eligible = [
            index
            for index, block in enumerate(blocks)
            if isinstance(block, _VISIBLE_BLOCK_TYPES)
            and not (index + 1 < len(blocks) and isinstance(blocks[index + 1], ArticleImageBlock))
        ]
        if not eligible:
            raise ValueError("context media section has no safe prose placement")
        source_text = " ".join(
            value for value in (asset.alt_text, asset.caption or "", asset.credit or "") if value
        )
        source_terms = _semantic_terms(source_text)
        scored: list[tuple[int, int, tuple[str, ...]]] = []
        for index in eligible:
            block_text = _block_text(blocks[index])
            matched = tuple(term for term in source_terms if term in block_text)[:6]
            scored.append((len(matched), index, matched))
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected_score, selected_index, matched_terms = scored[0]
        reason: Literal["semantic_text_overlap", "first_prose_fallback", "collision_shifted"] = (
            "semantic_text_overlap" if selected_score else "first_prose_fallback"
        )
        occupied = used.setdefault(section_index, [])
        if any(abs(selected_index - existing) <= 1 for existing in occupied):
            shifted = next(
                (
                    index
                    for index in eligible
                    if all(abs(index - existing) > 1 for existing in occupied)
                ),
                None,
            )
            if shifted is None:
                raise ValueError("context media cannot be separated by a visible prose block")
            selected_index = shifted
            matched_terms = tuple(
                term for term in source_terms if term in _block_text(blocks[selected_index])
            )[:6]
            reason = "collision_shifted"
        occupied.append(selected_index)
        planned.append(
            ContextBlockPlacement(
                media_path=asset.path,
                section_index=section_index,
                target_block_index=selected_index,
                reason_code=reason,
                matched_terms=matched_terms,
            )
        )
    return tuple(planned)


def render_editor_handoff_v2_body(
    *, article: ArticlePackage, media: tuple[EditorHandoffMediaAsset, ...]
) -> RenderedEditorHandoffV2:
    recipe = select_layout_recipe(article, media)
    placements = plan_context_placements(article=article, media=media)
    context_by_target = {
        (item.section_index, item.target_block_index): next(
            asset for asset in media if asset.path == item.media_path
        )
        for item in placements
    }
    body_by_ordinal = {item.ordinal: item for item in media if item.role == "body"}
    emphasis: list[SemanticEmphasisBlock] = []
    global_terms = _semantic_terms(
        " ".join(
            (article.title, article.digest, *(section.heading for section in article.sections))
        )
    )
    lead_spans = select_semantic_emphasis(article.lead, context_terms=global_terms)
    emphasis.append(
        SemanticEmphasisBlock(block_path="lead", source_text=article.lead, spans=lead_spans)
    )
    sections: list[str] = [
        v1._global_open(),
        _cover(article, recipe),
        _toc(article, recipe),
        _lead_card(article.lead, lead_spans),
    ]
    quote_ordinal = 0
    for section_index, section in enumerate(article.sections):
        sections.append(v1._chapter_heading(section_index, section.heading))
        block_terms = (*global_terms, *_semantic_terms(section.heading))
        for block_index, block in enumerate(section.blocks):
            block_path = f"section-{section_index}-block-{block_index}"
            if isinstance(block, ArticleParagraphBlock):
                spans = select_semantic_emphasis(block.text, context_terms=block_terms)
                emphasis.append(
                    SemanticEmphasisBlock(
                        block_path=block_path, source_text=block.text, spans=spans
                    )
                )
                sections.append(_paragraph(block.text, spans))
            elif isinstance(block, ArticleBulletListBlock):
                for item_index, item in enumerate(block.items):
                    spans = select_semantic_emphasis(item, context_terms=block_terms)
                    emphasis.append(
                        SemanticEmphasisBlock(
                            block_path=f"{block_path}-item-{item_index}",
                            source_text=item,
                            spans=spans,
                        )
                    )
                    sections.append(_bullet(item, spans))
            elif isinstance(block, ArticleQuoteBlock):
                spans = select_semantic_emphasis(block.text, context_terms=block_terms)
                emphasis.append(
                    SemanticEmphasisBlock(
                        block_path=block_path, source_text=block.text, spans=spans
                    )
                )
                sections.append(_quote(block.text, spans, quote_ordinal))
                quote_ordinal += 1
            elif isinstance(block, ArticleImageBlock):
                ordinal = int(block.slot_key.removeprefix("body-"))
                asset = body_by_ordinal.get(ordinal)
                if asset is None:
                    raise ValueError("article image block has no verified V2 handoff asset")
                sections.append(v1._image(asset, disclose_rights=False))
            else:  # pragma: no cover - ArticleBlock is discriminated
                raise TypeError("unsupported article block")
            context = context_by_target.get((section_index, block_index))
            if context is not None:
                sections.append(v1._image(context, disclose_rights=True))
    conclusion_spans = select_semantic_emphasis(article.conclusion, context_terms=global_terms)
    emphasis.append(
        SemanticEmphasisBlock(
            block_path="conclusion", source_text=article.conclusion, spans=conclusion_spans
        )
    )
    sections.extend(
        (
            _conclusion(article.conclusion, conclusion_spans),
            v1._sources(article),
            v1._signature(article.author),
            "</section>",
        )
    )
    body_html = "".join(sections)
    return RenderedEditorHandoffV2(
        body_html=body_html,
        body_sha256=sha256(body_html.encode("utf-8")).hexdigest(),
        recipe=recipe,
        placements=placements,
        emphasis=tuple(emphasis),
    )


def run_editor_handoff_v2_preflight(
    *,
    article: ArticlePackage,
    body_html: str,
    preview_html: str,
    media: tuple[EditorHandoffMediaAsset, ...],
    body_visuals: tuple[BodyVisualLineage, ...],
    release: EditorHandoffRelease,
    placements: tuple[ContextBlockPlacement, ...],
    emphasis: tuple[SemanticEmphasisBlock, ...],
    mobile_validation: EditorHandoffMobileValidation,
    content_fingerprint: str,
    extra_checks: tuple[EditorHandoffCheck, ...] = (),
) -> EditorHandoffV2Preflight:
    base = v1.run_editor_handoff_preflight(
        body_html=body_html,
        preview_html=preview_html,
        media=media,
        approved=True,
    )
    checks = [
        *extra_checks,
        EditorHandoffCheck(
            code="release_authorized",
            severity="info",
            passed=True,
            field="release",
            detail="人工批准或自动质量策略已生成可审计放行记录",
        ),
        *(
            item
            for item in base.checks
            if item.code not in {"immutable_review_approved", "mobile_browser_validation_not_run"}
        ),
    ]
    context_paths = {item.path for item in media if item.role == "context"}
    placement_paths = {item.media_path for item in placements}
    checks.append(
        EditorHandoffCheck(
            code="context_block_placements_valid",
            severity="info" if placement_paths == context_paths else "error",
            passed=placement_paths == context_paths,
            field="placements",
            detail="新闻上下文图均绑定稳定正文块且不替换 IP 正文图",
        )
    )
    body_media = tuple(
        sorted((item for item in media if item.role == "body"), key=lambda x: x.ordinal)
    )
    body_slots = tuple(
        (int(block.slot_key.removeprefix("body-")), section_index)
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    body_visuals_valid = (
        tuple(item.ordinal for item in body_visuals) == tuple(range(len(body_media)))
        and tuple(item.ordinal for item in body_media) == tuple(range(len(body_media)))
        and tuple((item.ordinal, item.section_index) for item in body_visuals) == body_slots
        and len({item.reference.public_ref for item in body_visuals}) == len(body_visuals)
        and len({item.output_sha256 for item in body_visuals}) == len(body_visuals)
        and {character for item in body_visuals for character in item.visible_character_labels}
        == {"xiao-sai", "sai-xiansheng"}
        and all(
            item.output_sha256 == asset.sha256
            and item.output_media_type == asset.media_type
            and item.output_byte_size == asset.byte_size
            and item.output_width == asset.width
            and item.output_height == asset.height
            and item.block_index < len(article.sections[item.section_index].blocks)
            and _body_visual_block_kind(
                article.sections[item.section_index].blocks[item.block_index]
            )
            == item.block_kind
            and _body_visual_block_fingerprint(article, item) == item.block_fingerprint
            for item, asset in zip(body_visuals, body_media, strict=True)
        )
    )
    checks.append(
        EditorHandoffCheck(
            code="reference_conditioned_body_visuals_valid",
            severity="info" if body_visuals_valid else "error",
            passed=body_visuals_valid,
            field="body_visuals",
            detail=("每张正文图均绑定精确正文块、批准 IP 参考、生成计划和可见角色校验"),
        )
    )
    emphasis_valid = all(
        len(item.spans) <= 3
        and all(item.source_text[span.start : span.end] == span.text for span in item.spans)
        and all(
            left.end <= right.start for left, right in zip(item.spans, item.spans[1:], strict=False)
        )
        for item in emphasis
    )
    checks.append(
        EditorHandoffCheck(
            code="semantic_emphasis_roundtrip_valid",
            severity="info" if emphasis_valid else "error",
            passed=emphasis_valid,
            field="emphasis",
            detail="语义重点均来自原文且每个文本块最多三处",
        )
    )
    mobile_matches = mobile_validation.status == "not_run" or (
        mobile_validation.content_fingerprint == content_fingerprint
        and mobile_validation.body_sha256 == sha256(body_html.encode("utf-8")).hexdigest()
        and mobile_validation.media_sha256s == tuple(item.sha256 for item in media)
    )
    checks.append(
        EditorHandoffCheck(
            code=(
                "mobile_browser_validation_bound"
                if mobile_validation.status == "passed"
                else "mobile_browser_validation_not_run"
            ),
            severity=("info" if mobile_validation.status == "passed" else "warning"),
            passed=mobile_validation.status == "passed",
            field="mobile_validation",
            detail=(
                "320px/430px 浏览器验收与当前正文和媒体指纹精确匹配"
                if mobile_validation.status == "passed"
                else "当前运行时未执行浏览器验收，未套用其他文章结果"
            ),
        )
    )
    if not mobile_matches:
        checks.append(
            EditorHandoffCheck(
                code="mobile_browser_validation_binding_mismatch",
                severity="error",
                passed=False,
                field="mobile_validation",
                detail="浏览器验收报告与当前正文或媒体指纹不匹配",
            )
        )
    blocking = tuple(item.code for item in checks if item.severity == "error" and not item.passed)
    warnings = tuple(item.code for item in checks if item.severity == "warning" and not item.passed)
    return EditorHandoffV2Preflight(
        passed=not blocking,
        checks=tuple(checks),
        blocking_codes=blocking,
        warning_codes=warnings,
    )


def fingerprint_v2(*parts: object) -> str:
    payload = json.dumps(
        parts, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _semantic_terms(text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for match in _CLAUSE_RE.finditer(text):
        candidates.extend(unit for unit, _start in _whole_semantic_units(match.group()))
    candidates.extend(term for term in _KNOWN_TERMS if term in text)
    return tuple(dict.fromkeys(candidates))[:24]


def _whole_semantic_units(clause: str) -> tuple[tuple[str, int], ...]:
    """Return complete semantic units; never slice a long clause to fit a limit."""
    units: list[tuple[str, int]] = []
    cursor = 0
    for connective in _CONNECTIVE_RE.finditer(clause):
        raw = clause[cursor : connective.start()]
        _append_whole_unit(units, raw, cursor)
        cursor = connective.end()
    _append_whole_unit(units, clause[cursor:], cursor)
    return tuple(units)


def _append_whole_unit(units: list[tuple[str, int]], raw: str, offset: int) -> None:
    value = raw.strip()
    if not 4 <= len(value) <= 15:
        return
    leading = len(raw) - len(raw.lstrip())
    if value.startswith(_BAD_STARTS) or value.endswith(_BAD_ENDS):
        return
    if value.count("“") != value.count("”"):
        return
    units.append((value, offset + leading))


def _block_text(block: object) -> str:
    if isinstance(block, ArticleBulletListBlock):
        return " ".join(block.items)
    if isinstance(block, (ArticleParagraphBlock, ArticleQuoteBlock)):
        return block.text
    return ""


def _body_visual_block_kind(
    block: object,
) -> Literal["paragraph", "bullet_list", "quote", "callout"] | None:
    if isinstance(block, ArticleParagraphBlock):
        return "paragraph"
    if isinstance(block, ArticleBulletListBlock):
        return "bullet_list"
    if isinstance(block, ArticleQuoteBlock):
        return block.kind
    return None


def _body_visual_block_fingerprint(
    article: ArticlePackage,
    visual: BodyVisualLineage,
) -> str:
    block = article.sections[visual.section_index].blocks[visual.block_index]
    if isinstance(block, ArticleBulletListBlock):
        source = "; ".join(block.items)
    elif isinstance(block, (ArticleParagraphBlock, ArticleQuoteBlock)):
        source = block.text
    else:
        return ""
    scene_text = " ".join(source.split())[:480]
    return fingerprint(
        "official-account-generated-visual-block-v1",
        visual.section_index,
        visual.block_index,
        visual.block_kind,
        scene_text,
    )


def _leaf(text: str) -> str:
    return f'<span leaf="">{escape(text, quote=False)}</span>'


def _emphasized(text: str, spans: tuple[SemanticEmphasisSpan, ...]) -> str:
    pieces: list[str] = []
    cursor = 0
    for span in spans:
        if cursor < span.start:
            pieces.append(_leaf(text[cursor : span.start]))
        pieces.append(
            '<span style="border-bottom:2px solid #29B6EE;padding-bottom:1px;">'
            f"{_leaf(text[span.start : span.end])}</span>"
        )
        cursor = span.end
    if cursor < len(text):
        pieces.append(_leaf(text[cursor:]))
    return "".join(pieces) or _leaf(text)


def _cover(article: ArticlePackage, recipe: EditorHandoffLayoutRecipe) -> str:
    recipe_label = {
        "news_analysis": "NEWS · 新闻解读",
        "tutorial_list": "GUIDE · 方法清单",
        "case_opinion": "CASE · 观点案例",
        "analysis": "FIELD NOTES · 深度观察",
    }[recipe.kind]
    return (
        '<section style="margin:0 0 32px;background:#FFFFFF;border:1.5px solid '
        "rgba(13,87,200,0.15);border-radius:20px;overflow:hidden;box-shadow:0 4px 20px "
        'rgba(0,0,0,0.06);width:100%;">'
        '<section style="padding:30px 24px 26px;">'
        '<p style="font-size:11px;font-weight:700;letter-spacing:2px;color:#0D57C8;'
        f'margin:0 0 18px;">{_leaf(recipe_label)}</p>'
        f'<p style="font-size:{recipe.title_size_px}px;font-weight:900;color:#0D57C8;'
        f'margin:0 0 16px;line-height:1.3;letter-spacing:-0.5px;">{_leaf(article.title)}</p>'
        '<section style="width:48px;height:3px;background:linear-gradient(to right,#0D57C8,'
        '#22D7D6);border-radius:2px;margin-bottom:12px;"><span leaf=""><br></span></section>'
        '<p style="font-size:13px;color:#607086;margin:0;line-height:1.75;">'
        f"{_leaf(article.digest)}</p>"
        '</section><section style="background:linear-gradient(135deg,#0D57C8,#285ACE);'
        'padding:12px 24px;display:flex;align-items:center;justify-content:space-between;">'
        '<p style="font-size:12px;color:#FFFFFF;margin:0;font-weight:600;">'
        '<span leaf="">小赛 AI · 科创教育观察</span></p>'
        '<p style="font-size:10px;color:#FFFFFF;margin:0;">'
        '<span leaf="">事实 · 方法 · 实践</span></p>'
        "</section></section>"
    )


def _toc(article: ArticlePackage, recipe: EditorHandoffLayoutRecipe) -> str:
    cards: list[str] = []
    for index, section in enumerate(article.sections[:3]):
        active = index == 0
        background = "linear-gradient(135deg,#0D57C8,#285ACE)" if active else "#FFFFFF"
        color = "#FFFFFF" if active else "#0D57C8"
        border = "0" if active else "1px solid #DCEAF5"
        cards.append(
            '<section style="display:inline-block;white-space:normal;vertical-align:top;'
            f"width:{recipe.toc_width_px}px;background:{background};border:{border};"
            'border-radius:12px;padding:12px;margin-right:8px;">'
            f'<p style="font-size:9px;font-weight:700;color:{color};letter-spacing:1px;'
            f'margin:0 0 5px;">{_leaf(f"PART {index + 1:02d}")}</p>'
            f'<p style="font-size:{recipe.toc_size_px}px;font-weight:800;color:{color};'
            f'margin:0;line-height:1.55;">{_leaf(section.heading)}</p></section>'
        )
    return (
        '<section style="margin:0 20px 32px;">'
        '<section style="display:flex;align-items:center;justify-content:space-between;'
        'margin-bottom:10px;">'
        f'<p style="font-size:10px;color:#607086;margin:0;letter-spacing:2px;font-weight:600;">'
        f"{_leaf(f'精选 {len(cards)} 个核心章节')}</p>"
        f'<p style="font-size:10px;color:#607086;margin:0;">{_leaf("👉 滑动")}</p></section>'
        '<section style="overflow-x:scroll;-webkit-overflow-scrolling:touch;white-space:nowrap;'
        f'padding-bottom:8px;">{"".join(cards)}</section></section>'
    )


def _lead_card(text: str, spans: tuple[SemanticEmphasisSpan, ...]) -> str:
    return (
        '<section style="margin:0 20px 36px;padding:20px 22px;background:#EAF7FF;'
        'border-left:4px solid #0D57C8;border-radius:0 14px 14px 0;">'
        '<p style="font-size:16px;color:#0D57C8;font-weight:700;line-height:1.8;margin:0;">'
        f"{_emphasized(text, spans)}</p></section>"
    )


def _paragraph(text: str, spans: tuple[SemanticEmphasisSpan, ...]) -> str:
    return (
        '<p style="font-size:14px;color:#26364A;line-height:1.9;margin:0 20px 18px;'
        f'text-align:justify;">{_emphasized(text, spans)}</p>'
    )


def _bullet(text: str, spans: tuple[SemanticEmphasisSpan, ...]) -> str:
    return (
        '<section style="margin:0 20px 12px;padding:13px 16px;background:#F3FBFF;'
        'border-radius:10px;display:flex;gap:10px;align-items:flex-start;">'
        '<span style="color:#FC9103;font-weight:900;"><span leaf="">●</span></span>'
        '<p style="font-size:14px;color:#26364A;line-height:1.8;margin:0;flex:1;">'
        f"{_emphasized(text, spans)}</p></section>"
    )


def _quote(text: str, spans: tuple[SemanticEmphasisSpan, ...], ordinal: int) -> str:
    variant = ordinal % 3
    if variant == 0:
        style = "background:#0D57C8;border-radius:14px;"
        text_style = "color:#FFFFFF;font-weight:700;"
    elif variant == 1:
        style = "background:#EAF7FF;border-left:4px solid #0D57C8;border-radius:0 14px 14px 0;"
        text_style = "color:#0D57C8;font-weight:700;"
    else:
        style = "background:#FFFFFF;border-left:4px solid #29B6EE;border-radius:0 10px 10px 0;"
        text_style = "color:#26364A;font-weight:600;"
    return (
        f'<section style="margin:22px 20px;padding:18px 20px;{style}">'
        f'<p style="font-size:15px;{text_style}line-height:1.8;margin:0;">'
        f"{_emphasized(text, spans)}</p></section>"
    )


def _conclusion(text: str, spans: tuple[SemanticEmphasisSpan, ...]) -> str:
    return (
        '<section style="margin:44px 20px 24px;padding:24px;background:linear-gradient(135deg,'
        '#EAF7FF,#F3FBFF);border-radius:16px;border:1px solid #C7DDEF;">'
        '<p style="font-size:10px;color:#0D57C8;font-weight:800;letter-spacing:2px;'
        f'margin:0 0 10px;">{_leaf("LAST · 写在最后")}</p>'
        f'<p style="font-size:15px;color:#26364A;line-height:1.9;margin:0;">'
        f"{_emphasized(text, spans)}</p></section>"
    )
