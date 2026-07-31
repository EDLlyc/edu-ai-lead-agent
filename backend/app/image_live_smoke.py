# ruff: noqa: RUF001, E501, ASYNC240
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import SecretStr

from app.application.ports.image_generation import ImageGenerationRequest
from app.core.config import get_settings
from app.domain.image_generation import image_checksum, image_request_fingerprint
from app.infrastructure.ai.image_generation import ToApisImageGenerator

_DEFAULT_PROMPT = (
    "Use the supplied Sai Xiansheng and Xiaosai character artwork as the exact visual identity "
    "reference. Create a polished square 3D educational science illustration for a parent-facing "
    "Moments post about embodied AI: Sai Xiansheng and Xiaosai observe a friendly dexterous robot "
    "hand learning to adjust one finger after a simulated failure. Show a calm laboratory with "
    "subtle sensor paths and self-correction cues, deep science blue, clean white, and restrained "
    "orange accents. Warm, curious, accurate, and trustworthy rather than promotional. Preserve "
    "the owl character identity and proportions. No real children, no human faces, no logo "
    "reconstruction, no extra brand marks, no Chinese text, no promises, no watermark, no QR code."
)
_ZH_PROMPT = (
    "Use case: scientific-educational. Asset type: a square parent-facing social post. Input "
    "image: use the supplied Sai Xiansheng and Xiaosai artwork only as the exact character identity "
    "and proportion reference. Create the same polished 3D laboratory composition: both characters "
    "observe a friendly dexterous robot hand learning to adjust one finger after a simulated "
    "failure, with subtle sensor paths and self-correction cues. Use deep science blue, clean white, "
    "and restrained orange accents; keep the mood warm, curious, accurate, and non-promotional. "
    "Render only these Chinese strings, exactly and legibly: title '具身智能'; subtitle "
    "'从尝试中学习，在调整中成长'; labels '尝试', '调整', '进步', '感知输入', '学习进行中', "
    "and '自我纠正'. Do not render any English, Latin letters, digits, or any other words. Preserve "
    "Sai Xiansheng and Xiaosai identities, silhouettes, facial features, colors, and relative "
    "proportions from the reference. No extra text, logo reconstruction, extra brand marks, "
    "watermark, QR code, real children, human faces, promises, or promotional claims."
)
_ZH_MINIMAL_PROMPT = (
    "Use case: scientific-educational. Asset type: a square parent-facing social post. Input "
    "image: use the supplied Sai Xiansheng and Xiaosai artwork as the exact identity, silhouette, "
    "facial-feature, color, and proportion reference. Create the same polished 3D laboratory scene: "
    "both characters observe a friendly dexterous robot hand learning to adjust one finger after a "
    "simulated failure, with subtle sensor paths and self-correction cues. Use deep science blue, "
    "clean white, restrained orange accents, and a warm accurate non-promotional mood. Render only "
    "these four short Chinese strings, exactly and legibly: '具身智能', '尝试', '调整', '进步'. "
    "Do not render any other Chinese text, any English, Latin letters, digits, clothing labels, "
    "logos, extra marks, watermark, QR code, promises, real children, or human faces. Preserve both "
    "Sai Xiansheng and Xiaosai identities and relative proportions from the reference."
)
_ZH_BRAND_V2_PROMPT = (
    "Use case: text-localization and identity-preserve. Asset type: a square parent-facing social "
    "post. Input image: this is the single edit target, not a loose style reference. Preserve its "
    "composition, Sai Xiansheng and Xiaosai characters, central dexterous robot hand, poses, facial "
    "features, proportions, laboratory setting, lighting, colors, panels, spacing, and visual "
    "hierarchy as closely as possible. Change only the visible editorial text into this exact "
    "Chinese content: title '具身智能'; subtitle '在真实体验中学习，在不断调整中成长'; body lines "
    "'小赛在探索中尝试，在反馈中调整。', '每一次动手，都让理解更深。', and "
    "'每一次进步，都值得被看见。'; brand line '守护好奇心 · 锤炼思考力 · 培养创造力'; "
    "numbered process labels '尝试', '调整', and '进步'; bottom panel labels '感知输入', "
    "'学习进行中', and '自我纠正'. Render every supplied string verbatim, legibly, and in the same "
    "corresponding information area as the source image. The existing character clothing marks "
    "'Dr.S' and 'AI' may remain unchanged. Do not render any other English or Latin text, any extra "
    "Chinese text, invented logo, QR code, watermark, promotional promise, or additional mark. Do "
    "not change, replace, redesign, or add characters; do not alter the robot hand or scene."
)


def _prompt_for_profile(profile: str) -> str:
    if profile == "default":
        return _DEFAULT_PROMPT
    if profile == "zh":
        return _ZH_PROMPT
    if profile == "zh_minimal":
        return _ZH_MINIMAL_PROMPT
    if profile == "zh_brand_v2":
        return _ZH_BRAND_V2_PROMPT
    raise ValueError("unsupported image smoke prompt profile")


async def run(
    reference: Path,
    output: Path,
    model_override: str | None = None,
    business_run_id: str = "live-smoke-2026-07-31",
    prompt_profile: str = "default",
) -> None:
    settings = get_settings()
    if settings.toapis_api_key is None:
        raise RuntimeError("TOAPIS_API_KEY is not configured")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    reference_body = reference.read_bytes()
    model = model_override or settings.image_model
    prompt = _prompt_for_profile(prompt_profile)
    fingerprint = image_request_fingerprint(
        run_id=business_run_id,
        draft_version_id="embodied-ai-robot-self-correction",
        prompt=prompt,
        provider="toapis",
        model=model,
        prompt_version=settings.image_prompt_version,
        pipeline_version=settings.image_pipeline_version,
        reference_sha256=image_checksum(reference_body),
    )
    async with httpx.AsyncClient(follow_redirects=False) as client:
        generator = ToApisImageGenerator(
            client=client,
            base_url=settings.toapis_base_url,
            api_key=SecretStr(settings.toapis_api_key.get_secret_value()),
            model=model,
            max_attempts=settings.image_max_attempts,
            initial_poll_seconds=settings.image_poll_initial_seconds,
            poll_interval_seconds=settings.image_poll_interval_seconds,
            provider_window_seconds=settings.image_provider_window_seconds,
            timeout_seconds=settings.image_provider_timeout_seconds,
            max_download_bytes=settings.image_max_download_bytes,
        )
        result = await generator.generate(
            ImageGenerationRequest(
                run_id=uuid4(),
                draft_version_id=uuid4(),
                prompt=prompt,
                request_fingerprint=fingerprint,
                reference_image=reference_body,
                reference_filename=reference.name,
            )
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".png" and result.media_type != "image/png":
        raise RuntimeError("provider returned a non-PNG image for a PNG output path")
    with output.open("xb") as output_file:
        output_file.write(result.image_bytes)
    print(
        f"completed provider={result.provider} model={result.model} "
        f"size={result.width}x{result.height} bytes={len(result.image_bytes)} output={output}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one bounded ToAPIs image acceptance call")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=str)
    parser.add_argument("--business-run-id", default="live-smoke-2026-07-31")
    parser.add_argument(
        "--prompt-profile",
        choices=("default", "zh", "zh_minimal", "zh_brand_v2"),
        default="default",
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            args.reference,
            args.output,
            args.model,
            args.business_run_id,
            args.prompt_profile,
        )
    )


if __name__ == "__main__":
    main()
