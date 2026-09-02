"""Shared runtime construction for the persisted official-account article identity."""

from __future__ import annotations

from typing import Literal

from app.application.ports.official_account_local import OfficialAccountVersionIdentity
from app.core.config import Settings


def official_account_identity_from_settings(
    settings: Settings,
    *,
    provider: Literal["fake", "zhipu"],
    model: str,
) -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider=provider,
        model=model,
        generator_prompt_version=settings.official_account_local_generator_prompt_version,
        article_schema_version=settings.official_account_local_article_schema_version,
        media_plan_version=settings.official_account_local_media_plan_version,
        auditor_prompt_version=settings.official_account_local_auditor_prompt_version,
        audit_schema_version=settings.official_account_local_audit_schema_version,
        rule_version=settings.official_account_local_rule_version,
        renderer_version=settings.official_account_local_renderer_version,
        style_version=settings.official_account_local_style_version,
        template_version=settings.official_account_local_template_version,
        local_adapter_version=settings.official_account_local_adapter_version,
        default_author=settings.official_account_local_default_author,
        min_characters=settings.official_account_local_min_characters,
        target_min_characters=settings.official_account_local_target_min_characters,
        target_max_characters=settings.official_account_local_target_max_characters,
        max_characters=settings.official_account_local_max_characters,
        visual_query_version=settings.official_account_local_visual_query_version,
        visual_selector_version=settings.official_account_local_visual_selector_version,
        context_media_plan_version=settings.official_account_local_context_media_plan_version,
        generated_visual_plan_version=(
            settings.official_account_local_generated_visual_plan_version
            if provider == "zhipu" and settings.official_account_local_generated_visuals_enabled
            else None
        ),
        generated_visual_prompt_version=(
            settings.official_account_local_generated_visual_prompt_version
            if provider == "zhipu" and settings.official_account_local_generated_visuals_enabled
            else None
        ),
    )


__all__ = ["official_account_identity_from_settings"]
