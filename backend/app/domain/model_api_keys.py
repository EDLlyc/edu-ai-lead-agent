# ruff: noqa: RUF001
"""运营后台 · 模型配置: the model provider keys an owner may rotate.

Only keys rotate here. Base URLs and model names are pinned by settings validation and the strict
visual policy (prompts, audits and stored vectors depend on them), so they need a code release.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelKeyProvider:
    id: str
    name: str
    used_for: str
    # The Settings field the stored key replaces.
    settings_field: str


MODEL_KEY_PROVIDERS: tuple[ModelKeyProvider, ...] = (
    ModelKeyProvider(
        id="zhipu",
        name="智谱",
        used_for="写文案、审核、识图、文字向量",
        settings_field="ai_platform_api_key",
    ),
    ModelKeyProvider(
        id="comfly",
        name="Comfly",
        used_for="生成配图",
        settings_field="comfly_api_key",
    ),
    ModelKeyProvider(
        id="alibaba-visual",
        name="阿里云百炼",
        used_for="图片向量（品牌素材检索）",
        settings_field="visual_embedding_api_key",
    ),
)

_BY_ID = {provider.id: provider for provider in MODEL_KEY_PROVIDERS}


def model_key_provider(provider_id: str) -> ModelKeyProvider | None:
    return _BY_ID.get(provider_id)


def sealed_key_purpose(provider_id: str) -> str:
    """Associated data for the sealed key, so a ciphertext only opens for its own provider."""

    return f"model_api_key:{provider_id}"


def valid_api_key(value: str) -> bool:
    return 8 <= len(value) <= 300 and value.isprintable() and not any(c.isspace() for c in value)


__all__ = [
    "MODEL_KEY_PROVIDERS",
    "ModelKeyProvider",
    "model_key_provider",
    "sealed_key_purpose",
    "valid_api_key",
]
