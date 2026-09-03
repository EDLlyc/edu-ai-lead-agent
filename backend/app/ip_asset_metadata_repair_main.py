from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import TypeAlias

import httpx

from app.application.services.ip_asset_metadata_repair import (
    IP_ASSET_METADATA_REPAIR_DEFAULT_PACING_SECONDS,
    IP_ASSET_METADATA_REPAIR_MAX_PACING_SECONDS,
    IP_ASSET_METADATA_REPAIR_MIN_PACING_SECONDS,
    apply_metadata_repair_plan,
    create_metadata_repair_canary,
    create_metadata_repair_plan,
    prepare_approved_repair_assets,
    restore_metadata_repair_result,
    validate_metadata_repair_canary,
    validate_metadata_repair_plan,
    validate_metadata_repair_result,
    verify_approved_repair_assets,
)
from app.core.config import Settings, get_settings
from app.domain.ip_asset_metadata_repair import (
    IP_ASSET_METADATA_REPAIR_ACKNOWLEDGEMENT,
    IP_ASSET_METADATA_REPAIR_MODEL,
    IpAssetMetadataRepairCanary,
    IpAssetMetadataRepairItemStatus,
    IpAssetMetadataRepairPlan,
    IpAssetMetadataRepairResult,
)
from app.infrastructure.ai.factory import create_ip_asset_recognition_model
from app.infrastructure.brand.visual_catalog import load_visual_catalog
from app.infrastructure.db.ip_assets import PostgresIpAssetRepository
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.ip_asset_metadata_repair_artifacts import (
    read_private_artifact,
    reserve_private_artifact,
    write_private_artifact,
)
from app.infrastructure.storage.minio_ip_asset_store import MinioIpAssetStore

_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "output" / "ip-asset-metadata-repair"
_RepairInputArtifact: TypeAlias = (
    IpAssetMetadataRepairCanary | IpAssetMetadataRepairPlan | IpAssetMetadataRepairResult
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or apply the private local IP asset metadata repair plan"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Call the vision model and write a read-only plan")
    plan.add_argument("--output", required=True, type=Path)
    plan.add_argument("--canary", required=True, type=Path)
    plan.add_argument("--acknowledgement", required=True)
    plan.add_argument(
        "--pacing-seconds",
        type=_pacing_seconds,
        default=IP_ASSET_METADATA_REPAIR_DEFAULT_PACING_SECONDS,
        help="Delay between provider-bound asset requests",
    )

    subparsers.add_parser(
        "preflight", help="Verify the exact approved set and originals without a provider call"
    )

    canary = subparsers.add_parser("canary", help="Run exactly one compatibility classification")
    canary.add_argument("--output", required=True, type=Path)
    canary.add_argument("--acknowledgement", required=True)

    apply = subparsers.add_parser("apply", help="Apply one previously validated plan")
    apply.add_argument("--plan", required=True, type=Path)
    apply.add_argument("--output", required=True, type=Path)
    apply.add_argument("--acknowledgement", required=True)

    restore = subparsers.add_parser("restore", help="Restore metadata from an apply result")
    restore.add_argument("--result", required=True, type=Path)
    restore.add_argument("--output", required=True, type=Path)
    restore.add_argument("--acknowledgement", required=True)

    validate_plan = subparsers.add_parser("validate-plan", help="Validate without provider or DB")
    validate_plan.add_argument("--plan", required=True, type=Path)

    validate_result = subparsers.add_parser(
        "validate-result", help="Validate a result without provider or DB"
    )
    validate_result.add_argument("--result", required=True, type=Path)
    validate_canary = subparsers.add_parser(
        "validate-canary", help="Validate a canary without provider or DB"
    )
    validate_canary.add_argument("--canary", required=True, type=Path)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    if args.command == "validate-canary":
        canary = read_private_artifact(
            _local_artifact_path(args.canary), IpAssetMetadataRepairCanary
        )
        validate_metadata_repair_canary(canary, require_pass=False)
        _print_canary_summary(canary, operation="validated")
        return 0 if _canary_passed(canary) else 1
    if args.command == "validate-plan":
        plan = read_private_artifact(_local_artifact_path(args.plan), IpAssetMetadataRepairPlan)
        validate_metadata_repair_plan(plan, require_exact_set=True)
        _print_plan_summary(plan, operation="validated")
        return 0
    if args.command == "validate-result":
        result = read_private_artifact(
            _local_artifact_path(args.result), IpAssetMetadataRepairResult
        )
        validate_metadata_repair_result(result)
        _print_result_summary(result, operation="validated")
        return 0
    if (
        args.command in {"canary", "plan", "apply", "restore"}
        and args.acknowledgement != IP_ASSET_METADATA_REPAIR_ACKNOWLEDGEMENT
    ):
        raise ValueError("IP asset repair requires the exact local acknowledgement")

    output_reservation = (
        reserve_private_artifact(_local_artifact_path(args.output))
        if args.command in {"canary", "plan", "apply", "restore"}
        else None
    )
    if output_reservation is not None:
        with output_reservation:
            return await _run_side_effecting_command(
                args,
                input_artifact=_read_side_effecting_input(args),
            )
    return await _run_side_effecting_command(args)


async def _run_side_effecting_command(
    args: argparse.Namespace,
    *,
    input_artifact: _RepairInputArtifact | None = None,
) -> int:
    """Run commands after any side-effecting output has been reserved."""

    settings = get_settings()
    if not settings.ip_asset_hub_enabled:
        raise ValueError("IP asset repair requires the enabled local hub")
    engine = create_engine(settings)
    repository = PostgresIpAssetRepository(create_session_factory(engine))
    store = MinioIpAssetStore(settings)
    try:
        if args.command in {"preflight", "canary", "plan"}:
            loaded = await asyncio.to_thread(load_visual_catalog, settings.image_asset_manifest)
            approved_checksums = tuple(
                asset.checksum for asset in loaded.catalog.assets if asset.approved
            )
            selected = await prepare_approved_repair_assets(
                repository=repository,
                approved_checksums=approved_checksums,
            )
        if args.command == "preflight":
            preflight = await verify_approved_repair_assets(
                selected=selected,
                store=store,
            )
            print(
                json.dumps(
                    {
                        "operation": "preflight",
                        "selected_count": preflight.selected_count,
                        "verified_count": preflight.verified_count,
                        "character_distribution": dict(preflight.character_distribution),
                        "asset_type_distribution": dict(preflight.asset_type_distribution),
                    },
                    separators=(",", ":"),
                )
            )
            return 0
        if args.command in {"canary", "plan"}:
            provider_settings = _repair_provider_settings(settings)
            async with httpx.AsyncClient(follow_redirects=False) as client:
                model = create_ip_asset_recognition_model(provider_settings, client=client)
                if model is None:
                    raise ValueError("IP asset repair recognition provider is unavailable")
                if args.command == "canary":
                    canary = await create_metadata_repair_canary(
                        selected=selected,
                        store=store,
                        recognition_model=model,
                    )
                else:
                    if not isinstance(input_artifact, IpAssetMetadataRepairCanary):
                        raise ValueError("IP asset repair plan requires a v2 canary artifact")
                    repair_plan = await create_metadata_repair_plan(
                        selected=selected,
                        store=store,
                        recognition_model=model,
                        canary=input_artifact,
                        inter_request_pacing_seconds=args.pacing_seconds,
                    )
            if args.command == "canary":
                write_private_artifact(_local_artifact_path(args.output), canary)
                _print_canary_summary(canary, operation="canary")
                return 0 if _canary_passed(canary) else 1
            write_private_artifact(_local_artifact_path(args.output), repair_plan)
            _print_plan_summary(repair_plan, operation="planned")
            return 0 if repair_plan.failed_count == 0 else 1
        if args.command == "apply":
            if not isinstance(input_artifact, IpAssetMetadataRepairPlan):
                raise ValueError("IP asset repair apply requires a v2 plan artifact")
            result = await apply_metadata_repair_plan(
                repository=repository,
                store=store,
                plan=input_artifact,
            )
            write_private_artifact(_local_artifact_path(args.output), result)
            _print_result_summary(result, operation="applied")
            return (
                0
                if input_artifact.failed_count == 0
                and result.drift_count == 0
                and result.failed_count == 0
                else 1
            )
        if args.command == "restore":
            if not isinstance(input_artifact, IpAssetMetadataRepairResult):
                raise ValueError("IP asset repair restore requires a v2 result artifact")
            restored = await restore_metadata_repair_result(
                repository=repository,
                store=store,
                applied=input_artifact,
            )
            write_private_artifact(_local_artifact_path(args.output), restored)
            _print_result_summary(restored, operation="restored")
            return 0 if restored.drift_count == 0 and restored.failed_count == 0 else 1
        raise ValueError("IP asset repair command is unsupported")
    finally:
        await engine.dispose()


def _print_plan_summary(plan: IpAssetMetadataRepairPlan, *, operation: str) -> None:
    print(
        json.dumps(
            {
                "operation": operation,
                "schema_version": plan.schema_version,
                "model": plan.model,
                "selected_count": plan.selected_count,
                "scanned_count": plan.scanned_count,
                "suggested_count": plan.suggested_count,
                "changed_count": plan.changed_count,
                "unchanged_count": plan.unchanged_count,
                "failed_count": plan.failed_count,
                "provider_call_count": plan.provider_call_count,
                "inter_request_pacing_seconds": plan.inter_request_pacing_seconds,
            },
            separators=(",", ":"),
        )
    )


def _print_canary_summary(canary: IpAssetMetadataRepairCanary, *, operation: str) -> None:
    passed = _canary_passed(canary)
    print(
        json.dumps(
            {
                "operation": operation,
                "schema_version": canary.schema_version,
                "model": canary.model,
                "provider_call_count": canary.provider_call_count,
                "local_schema_valid": passed,
                "provider_json_mode_requested": False,
                "passed": passed,
                "error_code": (
                    canary.item.error_code.value if canary.item.error_code is not None else None
                ),
            },
            separators=(",", ":"),
        )
    )


def _canary_passed(canary: IpAssetMetadataRepairCanary) -> bool:
    return canary.provider_call_count == 1 and canary.item.status in {
        IpAssetMetadataRepairItemStatus.CHANGED,
        IpAssetMetadataRepairItemStatus.UNCHANGED,
    }


def _print_result_summary(result: IpAssetMetadataRepairResult, *, operation: str) -> None:
    print(
        json.dumps(
            {
                "operation": operation,
                "changed_count": result.changed_count,
                "already_applied_count": result.already_applied_count,
                "drift_count": result.drift_count,
                "failed_count": result.failed_count,
                "skipped_count": result.skipped_count,
            },
            separators=(",", ":"),
        )
    )


def _local_artifact_path(path: Path) -> Path:
    # Keep the caller's lexical path so the artifact layer can reject every symlink
    # component. Resolving here would silently erase the evidence that a CLI input or
    # output was reached through a symlink.
    resolved = Path(os.path.abspath(path))
    root = _OUTPUT_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(
            "IP asset repair artifacts must stay under the private output root"
        ) from None
    return resolved


def _read_side_effecting_input(args: argparse.Namespace) -> _RepairInputArtifact | None:
    """Reject obsolete or malformed inputs before provider/database setup."""

    if args.command == "plan":
        return read_private_artifact(_local_artifact_path(args.canary), IpAssetMetadataRepairCanary)
    if args.command == "apply":
        return read_private_artifact(_local_artifact_path(args.plan), IpAssetMetadataRepairPlan)
    if args.command == "restore":
        return read_private_artifact(_local_artifact_path(args.result), IpAssetMetadataRepairResult)
    return None


def _pacing_seconds(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("pacing must be a number") from None
    if (
        not IP_ASSET_METADATA_REPAIR_MIN_PACING_SECONDS
        <= value
        <= (IP_ASSET_METADATA_REPAIR_MAX_PACING_SECONDS)
    ):
        raise argparse.ArgumentTypeError("pacing is outside the safe bound")
    return value


def _repair_provider_settings(settings: Settings) -> Settings:
    """Bind the generic recognition factory to this immutable repair contract."""

    return settings.model_copy(
        update={
            "ip_asset_recognition_model": IP_ASSET_METADATA_REPAIR_MODEL,
            "ip_asset_recognition_concurrency": 1,
        }
    )


def main() -> None:
    args = _arguments()
    try:
        code = asyncio.run(_run(args))
    except Exception:
        print('{"operation":"failed","error_code":"ip_asset_metadata_repair_failed"}')
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
