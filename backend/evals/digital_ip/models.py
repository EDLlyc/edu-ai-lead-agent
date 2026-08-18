"""Strict sanitized fixtures for digital-IP projection contract evaluation."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.domain.brand_knowledge import BrandDocumentKind
from app.domain.visual_assets import VisualAssetKind
from pydantic import BaseModel, ConfigDict, Field, model_validator

CASE_SCHEMA_VERSION = "digital-ip-eval-case-v1"


class DigitalIpEvalCategory(StrEnum):
    POSITIONING = "positioning"
    TONE = "tone"
    PROHIBITED_LANGUAGE = "prohibited_language"
    SAFETY = "safety"
    VISUAL = "visual"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FixtureDocument(_StrictModel):
    document_id: UUID
    version_id: UUID
    title: str = Field(min_length=1, max_length=120)
    document_kind: BrandDocumentKind
    tone_tags: tuple[str, ...] = Field(default=(), max_length=12)
    safety_tags: tuple[str, ...] = Field(default=(), max_length=12)
    visual_tags: tuple[str, ...] = Field(default=(), max_length=12)


class FixtureVisualAsset(_StrictModel):
    asset_ref: str = Field(min_length=16, max_length=16, pattern=r"^[a-f0-9]{16}$")
    display_name: str = Field(min_length=1, max_length=120)
    asset_kind: VisualAssetKind
    characters: tuple[str, ...] = Field(default=(), max_length=4)
    roles: tuple[str, ...] = Field(default=(), max_length=4)
    topics: tuple[str, ...] = Field(default=(), max_length=12)
    poses: tuple[str, ...] = Field(default=(), max_length=12)
    scene_tags: tuple[str, ...] = Field(default=(), max_length=12)


class DigitalIpEvalCase(_StrictModel):
    schema_version: Literal["digital-ip-eval-case-v1"]
    case_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    category: DigitalIpEvalCategory
    documents: tuple[FixtureDocument, ...] = Field(min_length=1, max_length=4)
    visual_assets: tuple[FixtureVisualAsset, ...] = Field(default=(), max_length=4)
    expected_document_kinds: tuple[BrandDocumentKind, ...] = Field(min_length=1, max_length=4)
    expected_tone_tags: tuple[str, ...] = Field(default=(), max_length=12)
    expected_safety_tags: tuple[str, ...] = Field(default=(), max_length=12)
    expected_visual_tags: tuple[str, ...] = Field(default=(), max_length=12)
    expected_visual_characters: tuple[str, ...] = Field(default=(), max_length=4)
    prohibited_rule_required: bool = False

    @model_validator(mode="after")
    def validate_case_contract(self) -> DigitalIpEvalCase:
        values = (
            self.expected_document_kinds,
            self.expected_tone_tags,
            self.expected_safety_tags,
            self.expected_visual_tags,
            self.expected_visual_characters,
        )
        if any(len(group) != len(set(group)) for group in values):
            raise ValueError("digital IP eval expectations must be unique")
        if self.prohibited_rule_required and (
            BrandDocumentKind.PROHIBITED_LANGUAGE not in self.expected_document_kinds
        ):
            raise ValueError("prohibited rule cases must expect the prohibited-language kind")
        return self
