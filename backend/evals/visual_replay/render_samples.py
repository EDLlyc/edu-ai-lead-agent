"""Render a few selector-v3 illustrations for human review (paid, one call per sample).

For each requested production artifact, rebuild its visual brief and primary plan from the
exported snapshot, take the references the v3 app selector chose in the strategy replay, build
the same controlled v3 prompt production builds, and call the configured image provider once.
Outputs stay local: PNGs plus a JSON manifest of prompt fingerprints and reference asset ids.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from app.application.ports.image_generation import ImageGenerationRequest, ImageReference
from app.core.config import Settings
from app.domain.visual_brief import (
    VisualBrief,
    VisualCategory,
    VisualReferenceDescriptor,
    VisualReferenceRole,
    VisualRenderTextMode,
    VisualTextLayer,
)
from app.domain.visual_diversity import (
    VISUAL_PIPELINE_V3_VERSION,
    VISUAL_PROMPT_V3_VERSION,
    ControlledVisualPlan,
    build_controlled_visual_prompt_bundle,
)
from app.infrastructure.ai.factory import create_image_generator
from app.infrastructure.brand.visual_catalog import (
    LoadedVisualCatalog,
    load_visual_catalog,
    read_visual_asset_bytes,
)


def brief_from_snapshot(snapshot: dict[str, Any]) -> VisualBrief:
    text = snapshot["text_layer"]
    return VisualBrief(
        category=VisualCategory(snapshot["category"]),
        learning_goal=snapshot["learning_goal"],
        scene=snapshot["scene"],
        main_action=snapshot["main_action"],
        characters=tuple(snapshot["characters"]),
        asset_tags=tuple(snapshot["asset_tags"]),
        text_layer=VisualTextLayer(
            title=text["title"],
            learning_line=text["learning_line"],
            keywords=tuple(text.get("keywords") or ()),
            brand_values=tuple(text.get("brand_values") or ()),
            brand_signature=text.get("brand_signature") or "",
        ),
        version=snapshot["version"],
        reference_roles=tuple(VisualReferenceRole(role) for role in snapshot["reference_roles"]),
        render_text_mode=VisualRenderTextMode(snapshot["render_text_mode"]),
    )


async def render(
    *,
    settings: Settings,
    loaded: LoadedVisualCatalog,
    briefs: dict[str, dict[str, Any]],
    picks: dict[str, list[dict[str, Any]]],
    wanted: Sequence[str],
) -> tuple[list[tuple[str, bytes]], list[dict[str, Any]]]:
    by_id = loaded.catalog.asset_by_id
    images: list[tuple[str, bytes]] = []
    manifest: list[dict[str, Any]] = []
    async with httpx.AsyncClient(follow_redirects=False) as client:
        generator = create_image_generator(settings, client=client)
        for artifact_id in wanted:
            row = briefs[artifact_id]
            snapshot = row["visual_brief_snapshot"]
            brief = brief_from_snapshot(snapshot)
            plan = ControlledVisualPlan.from_metadata(snapshot["controlled_plan"])
            refs = [ref for ref in picks[artifact_id] if ref["role"] != "style_reference"]
            descriptors = tuple(
                VisualReferenceDescriptor(
                    asset_id=ref["asset_id"],
                    role=VisualReferenceRole(ref["role"]),
                    filename=by_id[ref["asset_id"]].filename,
                    checksum=by_id[ref["asset_id"]].checksum,
                )
                for ref in refs
            )
            bundle = build_controlled_visual_prompt_bundle(
                brief,
                plan,
                descriptors,
                prompt_version=VISUAL_PROMPT_V3_VERSION,
                pipeline_version=VISUAL_PIPELINE_V3_VERSION,
            )
            references = tuple(
                ImageReference(
                    role=ref["role"],
                    asset_id=ref["asset_id"],
                    filename=by_id[ref["asset_id"]].filename,
                    sha256=by_id[ref["asset_id"]].checksum,
                    image_bytes=read_visual_asset_bytes(loaded, by_id[ref["asset_id"]]),
                    selection_reason=ref.get("reason", ""),
                )
                for ref in refs
            )
            fingerprint = hashlib.sha256(
                f"visual-v3-sample\0{artifact_id}\0{bundle.request_fingerprint}".encode()
            ).hexdigest()
            try:
                result = await generator.generate(
                    ImageGenerationRequest(
                        run_id=UUID(row["run_id"]),
                        draft_version_id=uuid4(),
                        prompt=bundle.prompt,
                        request_fingerprint=fingerprint,
                        references=references,
                        reference_mode="budgeted_multi_reference",
                    )
                )
            except Exception as error:
                cause = error.__context__
                print(
                    json.dumps(
                        {
                            "failed": artifact_id[:8],
                            "error": type(error).__name__,
                            "cause": type(cause).__name__ if cause else None,
                        }
                    ),
                    file=sys.stderr,
                )
                continue
            file_name = f"{artifact_id[:8]}-v3.png"
            images.append((file_name, result.image_bytes))
            manifest.append(
                {
                    "artifact_id": artifact_id,
                    "file": file_name,
                    "model": result.model,
                    "prompt_fingerprint": bundle.request_fingerprint,
                    "references": [
                        {"role": ref["role"], "asset_id": ref["asset_id"]} for ref in refs
                    ],
                }
            )
            print(json.dumps({"rendered": file_name}), file=sys.stderr)
    return images, manifest


def run(args: argparse.Namespace) -> int:
    settings = Settings(
        _env_file=args.env_file,
        visual_semantic_enabled=False,
        image_model=args.model,
        image_max_attempts=1,
    )
    loaded = load_visual_catalog(settings.image_asset_manifest)
    briefs = {row["id"]: row for row in json.loads(Path(args.briefs).read_text("utf-8"))}
    picks = {
        row["artifact_id"]: row["picks"][args.arm]["refs"]
        for row in json.loads(Path(args.results).read_text("utf-8"))
    }
    wanted = [
        next(artifact for artifact in briefs if artifact.startswith(prefix))
        for prefix in args.artifact
    ]
    if len(wanted) > args.max_calls:
        raise SystemExit(f"{len(wanted)} samples exceed the {args.max_calls}-call cap")
    print(json.dumps({"samples": len(wanted), "model": args.model}), file=sys.stderr)
    if args.plan:
        return 0
    images, manifest = asyncio.run(
        render(settings=settings, loaded=loaded, briefs=briefs, picks=picks, wanted=wanted)
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for file_name, body in images:
        (output / file_name).write_bytes(body)
    (output / "samples.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--briefs", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--artifact", action="append", required=True)
    parser.add_argument("--arm", default="v3_app_rules")
    parser.add_argument("--model", default="gpt-image-2.5-sunburst")
    parser.add_argument("--max-calls", type=int, default=6)
    parser.add_argument("--env-file", default="/root/projects/edu-ai-lead-agent/.env")
    parser.add_argument("--plan", action="store_true")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
