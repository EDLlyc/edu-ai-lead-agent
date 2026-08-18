"""Capture recruiter-facing Agent Workbench evidence from real loopback services."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from app.schemas.agent_workbench import AgentWorkbenchRunResponse
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"
CASE_MANIFEST_PATH = REPOSITORY_ROOT / "docs/portfolio/agent-workbench-cases.v1.json"
CAPTURE_ROOT = REPOSITORY_ROOT / "docs/portfolio/runs/agent-workbench"
CURRENT_OVERVIEW_PATH = (
    REPOSITORY_ROOT / "docs/portfolio/assets/agent-workbench-real-runs-overview.png"
)
LIVE_OUTPUT_PATH = CAPTURE_ROOT / "live-zhipu"
NODE_CAPTURE_PATH = (
    REPOSITORY_ROOT / "docs/portfolio/capture-agent-workbench-real-runs.mjs"
)
API_ORIGIN = "http://127.0.0.1:8010"
UI_ORIGIN = "http://127.0.0.1:5173"
RUN_URL = f"{API_ORIGIN}/api/v1/agent-workbench/runs"
HEALTH_URL = f"{API_ORIGIN}/healthz"
READ_ONLY_TOOLS = frozenset(
    {"search_evidence", "get_event", "retrieve_brand_context", "validate_copy"}
)
_SAFE_CASE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PRIVATE_TEXT = re.compile(
    r"(?i)(?:/root/|/home/[^/\s]+/|[a-z]:\\users\\|bearer\s+[a-z0-9._~-]{8,}|"
    r"(?:sk|ak)-[a-z0-9_-]{12,}|postgres(?:ql)?://|qyapi\.weixin\.qq\.com)"
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_METADATA_CHUNKS = frozenset({b"eXIf", b"iTXt", b"tEXt", b"tIME", b"zTXt"})
_BROWSER_CAPTURE_TIMEOUT_SECONDS = 120.0
_SENSITIVE_ENVIRONMENT_KEYS = frozenset(
    {
        "AGENT_WORKBENCH_OPENAI_API_KEY",
        "AGENT_WORKBENCH_OPENAI_BASE_URL",
        "AGENT_WORKBENCH_OPENAI_MODEL",
        "AI_PLATFORM_API_KEY",
        "AI_PLATFORM_BASE_URL",
        "AI_CHAT_MODEL",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class CitationCountRule(_StrictModel):
    minimum: int = Field(ge=0, le=20)
    maximum: int = Field(ge=0, le=20)

    @model_validator(mode="after")
    def ordered_bounds(self) -> CitationCountRule:
        if self.minimum > self.maximum:
            raise ValueError("citation minimum cannot exceed maximum")
        return self


class PortfolioCase(_StrictModel):
    case_id: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=500)
    scenario_id: Literal[
        "evidence", "event", "brand", "copy_validation", "multi_tool", "insufficient"
    ]
    expected_status: Literal["completed", "refused", "budget_exhausted", "failed"]
    expected_tools: tuple[
        Literal[
            "search_evidence", "get_event", "retrieve_brand_context", "validate_copy"
        ],
        ...,
    ] = Field(max_length=4)
    citation_count: CitationCountRule
    expected_summary_marker: str = Field(min_length=1, max_length=160)
    screenshot_label: str = Field(min_length=1, max_length=160)

    @field_validator("case_id")
    @classmethod
    def safe_case_id(cls, value: str) -> str:
        if _SAFE_CASE_ID.fullmatch(value) is None:
            raise ValueError("case ID must be lowercase kebab-case")
        return value

    @field_validator("query", "expected_summary_marker", "screenshot_label")
    @classmethod
    def safe_public_text(cls, value: str) -> str:
        if value != value.strip() or _CONTROL_CHARACTER.search(value) is not None:
            raise ValueError(
                "portfolio case text contains unsafe whitespace or controls"
            )
        if _PRIVATE_TEXT.search(value) is not None:
            raise ValueError(
                "portfolio case text contains private or credential-like content"
            )
        return value

    @model_validator(mode="after")
    def unique_expected_tools(self) -> PortfolioCase:
        if len(set(self.expected_tools)) != len(self.expected_tools):
            raise ValueError("expected tool sequence contains duplicates")
        if self.expected_status == "refused" and self.expected_tools:
            raise ValueError("policy-refusal portfolio cases must expect zero tools")
        return self


class PortfolioCaseManifest(_StrictModel):
    schema_version: Literal["agent-workbench-portfolio-cases-v1"]
    cases: tuple[PortfolioCase, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def unique_case_ids(self) -> PortfolioCaseManifest:
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("portfolio case IDs must be unique")
        required = {"multi-tool-research", "copy-validation", "safety-refusal"}
        if set(case_ids) != required:
            raise ValueError("portfolio manifest must own the three approved cases")
        return self


class LiveConfiguration(_StrictModel):
    base_url: str
    api_key: str = Field(min_length=1, repr=False)
    model: str = Field(min_length=1, max_length=120)

    @field_validator("base_url")
    @classmethod
    def public_https_base_url(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        hostname = (parts.hostname or "").casefold().rstrip(".")
        if (
            parts.scheme != "https"
            or hostname != "open.bigmodel.cn"
            or parts.path.rstrip("/") != "/api/paas/v4"
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError(
                "live Zhipu base URL must be the credential-free official API root"
            )
        return value.strip().rstrip("/")

    @field_validator("api_key")
    @classmethod
    def bounded_api_key(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 512
            or any(char in normalized for char in "\r\n")
        ):
            raise ValueError("live model credential is invalid")
        return normalized

    @field_validator("model")
    @classmethod
    def safe_model_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(char.isspace() for char in normalized):
            raise ValueError("live model identity is invalid")
        return normalized


class CaptureError(RuntimeError):
    """Safe capture failure whose message contains no provider or credential data."""


def load_case_manifest(path: Path = CASE_MANIFEST_PATH) -> PortfolioCaseManifest:
    return PortfolioCaseManifest.model_validate_json(path.read_text(encoding="utf-8"))


def validate_loopback_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "http" or parts.hostname != "127.0.0.1":
        raise ValueError("capture endpoints must use the exact IPv4 loopback host")
    if (
        parts.port not in {5173, 8010}
        or parts.username is not None
        or parts.password is not None
    ):
        raise ValueError("capture endpoint port or credentials are not allowlisted")
    return value


def ensure_port_available(host: str, port: int) -> None:
    if host != "127.0.0.1" or port not in {5173, 8010}:
        raise ValueError("capture port probe is outside the allowlist")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError as error:
            raise CaptureError(
                f"required loopback port {port} is already in use"
            ) from error


def semantic_projection(response: AgentWorkbenchRunResponse) -> dict[str, Any]:
    return {
        "status": response.status.value,
        "tools": tool_sequence(response),
        "citation_count": len(response.citations),
        "claim_kinds": [claim.kind.value for claim in response.claims],
        "claim_citation_counts": [len(claim.citation_ids) for claim in response.claims],
        "steps": [
            {
                "kind": step.kind.value,
                "status": step.status.value,
                "tool_name": step.tool_name,
                "code": step.code,
                "item_count": step.item_count,
                "issue_count": step.issue_count,
                "citation_count": len(step.citation_ids),
            }
            for step in response.steps
        ],
    }


def compare_semantics(
    api_response: AgentWorkbenchRunResponse,
    ui_response: AgentWorkbenchRunResponse,
) -> None:
    if semantic_projection(api_response) != semantic_projection(ui_response):
        raise CaptureError(
            "direct API and browser UI responses have different safe semantics"
        )


def tool_sequence(response: AgentWorkbenchRunResponse) -> list[str]:
    return [
        step.tool_name
        for step in response.steps
        if step.kind.value == "tool_call" and step.tool_name is not None
    ]


def validate_response_safety(response: AgentWorkbenchRunResponse) -> None:
    metrics = response.metrics
    if metrics.model_turns > 4 or metrics.tool_calls > 4:
        raise CaptureError("captured response exceeded the bounded Agent budget")
    observed_tools = set(tool_sequence(response))
    if not observed_tools.issubset(READ_ONLY_TOOLS):
        raise CaptureError(
            "captured response proposed a tool outside the read-only registry"
        )
    catalog_ids = {citation.id for citation in response.citations}
    for claim in response.claims:
        if not set(claim.citation_ids).issubset(catalog_ids):
            raise CaptureError("captured response contains an unbound claim citation")


def validate_case_response(
    case: PortfolioCase,
    response: AgentWorkbenchRunResponse,
    *,
    exact_expectations: bool,
) -> bool:
    validate_response_safety(response)
    matches = (
        response.status.value == case.expected_status
        and tool_sequence(response) == list(case.expected_tools)
        and case.citation_count.minimum
        <= len(response.citations)
        <= case.citation_count.maximum
        and case.expected_summary_marker in response.summary
    )
    if exact_expectations and not matches:
        raise CaptureError(f"captured response did not satisfy case {case.case_id!r}")
    return matches


def terminate_process(
    process: subprocess.Popen[bytes], *, grace_seconds: float = 5.0
) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=grace_seconds)


def strip_png_metadata(path: Path) -> None:
    source = path.read_bytes()
    if not source.startswith(_PNG_SIGNATURE):
        raise CaptureError(f"capture artifact {path.name!r} is not a PNG")
    output = bytearray(_PNG_SIGNATURE)
    offset = len(_PNG_SIGNATURE)
    saw_end = False
    while offset < len(source):
        if offset + 12 > len(source):
            raise CaptureError(
                f"capture artifact {path.name!r} has a truncated PNG chunk"
            )
        length = struct.unpack(">I", source[offset : offset + 4])[0]
        chunk_end = offset + 12 + length
        if chunk_end > len(source):
            raise CaptureError(
                f"capture artifact {path.name!r} has an invalid PNG chunk"
            )
        chunk_type = source[offset + 4 : offset + 8]
        chunk_data = source[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", source[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise CaptureError(
                f"capture artifact {path.name!r} has an invalid PNG checksum"
            )
        if chunk_type not in _PNG_METADATA_CHUNKS:
            output.extend(source[offset:chunk_end])
        if chunk_type == b"IEND":
            saw_end = True
            if chunk_end != len(source):
                raise CaptureError(
                    f"capture artifact {path.name!r} has trailing PNG bytes"
                )
        offset = chunk_end
    if not saw_end:
        raise CaptureError(f"capture artifact {path.name!r} has no PNG end marker")
    temporary = path.with_suffix(".clean.png")
    temporary.write_bytes(bytes(output))
    temporary.replace(path)


def png_metadata_chunks(path: Path) -> tuple[str, ...]:
    source = path.read_bytes()
    if not source.startswith(_PNG_SIGNATURE):
        raise CaptureError(f"capture artifact {path.name!r} is not a PNG")
    found: list[str] = []
    offset = len(_PNG_SIGNATURE)
    while offset < len(source):
        length = struct.unpack(">I", source[offset : offset + 4])[0]
        chunk_type = source[offset + 4 : offset + 8]
        if chunk_type in _PNG_METADATA_CHUNKS:
            found.append(chunk_type.decode("ascii"))
        offset += 12 + length
    return tuple(found)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def relative_repository_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError as error:
        raise CaptureError("capture artifact escaped the repository") from error


def _safe_environment_base() -> dict[str, str]:
    environment = dict(os.environ)
    for key in tuple(environment):
        normalized = key.upper()
        if key in _SENSITIVE_ENVIRONMENT_KEYS or normalized.endswith(
            ("API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
        ):
            environment.pop(key, None)
    environment.pop("HTTP_PROXY", None)
    environment.pop("HTTPS_PROXY", None)
    environment.pop("ALL_PROXY", None)
    environment["NO_PROXY"] = "127.0.0.1,::1"
    return environment


def deterministic_api_environment() -> dict[str, str]:
    environment = _safe_environment_base()
    environment.update(
        {
            "APP_ENV": "development",
            "AGENT_WORKBENCH_ENABLED": "true",
            "AGENT_WORKBENCH_DATA_MODE": "fixture",
            "AGENT_WORKBENCH_MODEL_MODE": "deterministic",
            "AGENT_WORKBENCH_LIVE_ENABLED": "false",
        }
    )
    return environment


def live_api_environment(configuration: LiveConfiguration) -> dict[str, str]:
    environment = _safe_environment_base()
    environment.update(
        {
            "APP_ENV": "development",
            "AGENT_WORKBENCH_ENABLED": "true",
            "AGENT_WORKBENCH_DATA_MODE": "fixture",
            "AGENT_WORKBENCH_MODEL_MODE": "openai",
            "AGENT_WORKBENCH_LIVE_ENABLED": "true",
            "AGENT_WORKBENCH_OPENAI_BASE_URL": configuration.base_url,
            "AGENT_WORKBENCH_OPENAI_API_KEY": configuration.api_key,
            "AGENT_WORKBENCH_OPENAI_MODEL": configuration.model,
        }
    )
    return environment


def vite_environment() -> dict[str, str]:
    environment = _safe_environment_base()
    environment.update(
        {
            "VITE_AGENT_WORKBENCH_ENABLED": "true",
            "VITE_AGENT_WORKBENCH_API_BASE_URL": API_ORIGIN,
        }
    )
    return environment


def load_live_configuration(env_path: Path | None = None) -> LiveConfiguration:
    resolved_path = env_path or REPOSITORY_ROOT / ".env"
    values = (
        dotenv_values(resolved_path, interpolate=False)
        if resolved_path.exists()
        else {}
    )

    def configured(name: str, fallback: str) -> str:
        value = os.environ.get(name) or values.get(name)
        fallback_value = os.environ.get(fallback) or values.get(fallback)
        selected = value or fallback_value
        return selected if isinstance(selected, str) else ""

    return LiveConfiguration(
        base_url=configured("AGENT_WORKBENCH_OPENAI_BASE_URL", "AI_PLATFORM_BASE_URL"),
        api_key=configured("AGENT_WORKBENCH_OPENAI_API_KEY", "AI_PLATFORM_API_KEY"),
        model=configured("AGENT_WORKBENCH_OPENAI_MODEL", "AI_CHAT_MODEL") or "glm-5.2",
    )


def _wait_for_url(
    url: str, process: subprocess.Popen[bytes], *, timeout_seconds: float
) -> None:
    validate_loopback_url(url)
    deadline = time.monotonic() + timeout_seconds
    with httpx.Client(timeout=1.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise CaptureError("a local capture service exited during startup")
            try:
                response = client.get(url)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
    raise CaptureError("a local capture service did not become ready in time")


@contextmanager
def local_services(
    *,
    temporary_root: Path,
    mode: Literal["deterministic", "live-zhipu"],
    live_configuration: LiveConfiguration | None,
) -> Iterator[None]:
    ensure_port_available("127.0.0.1", 8010)
    ensure_port_available("127.0.0.1", 5173)
    api_log = (temporary_root / "api.log").open("wb")
    vite_log = (temporary_root / "vite.log").open("wb")
    api_environment = (
        deterministic_api_environment()
        if mode == "deterministic"
        else live_api_environment(
            live_configuration
            if live_configuration is not None
            else _raise_missing_live_configuration()
        )
    )
    api_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.agent_workbench_api_main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8010",
        ],
        cwd=BACKEND_ROOT,
        env=api_environment,
        stdout=api_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    vite_process: subprocess.Popen[bytes] | None = None
    try:
        _wait_for_url(HEALTH_URL, api_process, timeout_seconds=20.0)
        vite_process = subprocess.Popen(
            [
                "npm",
                "run",
                "dev",
                "--prefix",
                str(FRONTEND_ROOT),
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                "5173",
                "--strictPort",
            ],
            cwd=REPOSITORY_ROOT,
            env=vite_environment(),
            stdout=vite_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _wait_for_url(UI_ORIGIN, vite_process, timeout_seconds=30.0)
        yield
    finally:
        if vite_process is not None:
            terminate_process(vite_process)
        terminate_process(api_process)
        api_log.close()
        vite_log.close()


def _raise_missing_live_configuration() -> LiveConfiguration:
    raise CaptureError("live capture configuration was not supplied")


def _post_direct_case(case: PortfolioCase) -> AgentWorkbenchRunResponse:
    with httpx.Client(timeout=30.0, trust_env=False) as client:
        response = client.post(
            RUN_URL,
            headers={"Content-Type": "application/json", "Origin": UI_ORIGIN},
            json={
                "query": case.query,
                "scenario_id": case.scenario_id,
                "model_mode": "deterministic",
            },
        )
    if response.status_code != 200:
        raise CaptureError("direct loopback API probe returned a non-success response")
    try:
        return AgentWorkbenchRunResponse.model_validate_json(response.content)
    except ValueError as error:
        raise CaptureError(
            "direct loopback API probe returned an invalid typed response"
        ) from error


def _run_browser_capture(
    *,
    cases_path: Path,
    output_dir: Path,
    mode: Literal["deterministic", "live-zhipu"],
    observation_path: Path,
) -> None:
    process = subprocess.Popen(
        [
            "node",
            str(NODE_CAPTURE_PATH),
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--mode",
            mode,
            "--observation-output",
            str(observation_path),
        ],
        cwd=REPOSITORY_ROOT,
        env=vite_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        process.communicate(timeout=_BROWSER_CAPTURE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        terminate_process(process)
        raise CaptureError(
            "real browser capture exceeded its bounded deadline"
        ) from error
    except BaseException:
        terminate_process(process)
        raise
    if process.returncode != 0:
        raise CaptureError("real browser capture failed before evidence verification")


def _read_browser_observations(path: Path) -> dict[str, Mapping[str, object]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaptureError(
            "browser capture did not produce valid network observations"
        ) from error
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise CaptureError("browser capture observations have an invalid shape")
    observations: dict[str, Mapping[str, object]] = {}
    for item in raw["cases"]:
        if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
            raise CaptureError("browser capture observation is invalid")
        case_id = item["case_id"]
        if case_id in observations:
            raise CaptureError("browser capture returned a duplicate case observation")
        observations[case_id] = item
    return observations


def _load_ui_response(
    output_dir: Path, case: PortfolioCase
) -> AgentWorkbenchRunResponse:
    path = output_dir / f"{case.case_id}.response.json"
    try:
        response = AgentWorkbenchRunResponse.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise CaptureError(
            f"browser response for case {case.case_id!r} is not typed"
        ) from error
    write_json(path, response.model_dump(mode="json"))
    return response


def _provider_projection(
    response: AgentWorkbenchRunResponse,
) -> tuple[str | None, str | None]:
    for step in response.steps:
        if step.provider is not None or step.model is not None:
            return step.provider, step.model
    return None, None


def _case_summary(
    *,
    case: PortfolioCase,
    response: AgentWorkbenchRunResponse,
    capture_id: str,
    source_commit: str,
    api_probe: AgentWorkbenchRunResponse | None,
    semantic_match: bool | None,
    expectation_match: bool,
    mode: str,
) -> str:
    tools = tool_sequence(response)
    tool_label = " → ".join(f"`{tool}`" for tool in tools) if tools else "none"
    probe_line = (
        f"- Direct API probe run: `{api_probe.run_id}`\n"
        if api_probe is not None
        else "- Direct API probe: omitted to preserve the authorized single live Agent run\n"
    )
    semantic_line = (
        f"- Direct API/UI semantics match: `{str(semantic_match).lower()}`\n"
        if semantic_match is not None
        else "- Browser API POST count: `1`\n"
    )
    return (
        f"# {case.screenshot_label}\n\n"
        f"- Capture: `{capture_id}`\n"
        f"- Source commit: `{source_commit}`\n"
        f"- Mode: `{mode}`\n"
        f"- Sanitized query: {case.query}\n"
        f"- UI-linked run: `{response.run_id}`\n"
        f"{probe_line}"
        f"- Terminal status: `{response.status.value}`\n"
        f"- Tool sequence: {tool_label}\n"
        f"- Claims / citations / trace steps: `{len(response.claims)}` / "
        f"`{len(response.citations)}` / `{len(response.steps)}`\n"
        f"- Model decisions / tool calls: `{response.metrics.model_turns}` / "
        f"`{response.metrics.tool_calls}`\n"
        f"- Captured duration: `{response.metrics.duration_ms} ms`\n"
        f"- Expected deterministic contract matched: `{str(expectation_match).lower()}`\n"
        f"{semantic_line}\n"
        f"## Safe response summary\n\n{response.summary}\n\n"
        "The JSON and screenshot come from the same browser-originated loopback HTTP response. "
        "No provider body, prompt, credential, private path, or durable trace is stored.\n"
    )


def _overview_markdown(
    *,
    capture_id: str,
    source_commit: str,
    captured_at: str,
    mode: str,
    cases: Sequence[tuple[PortfolioCase, AgentWorkbenchRunResponse, bool]],
) -> str:
    rows = []
    for case, response, expectation_match in cases:
        tools = " → ".join(tool_sequence(response)) or "none"
        rows.append(
            f"| `{case.case_id}` | `{response.status.value}` | {tools} | "
            f"{len(response.citations)} | {len(response.steps)} | "
            f"{response.metrics.model_turns} / {response.metrics.tool_calls} | "
            f"{'yes' if expectation_match else 'no'} |"
        )
    authority = (
        "This deterministic fixture capture proves the reproducible execution chain and safety "
        "contract; it is not evidence of live-model intelligence."
        if mode == "deterministic-fixture"
        else "This is one non-deterministic, non-CI-authoritative live-model run. It does not "
        "replace the deterministic baseline."
    )
    return (
        "# Agent Workbench real loopback run evidence\n\n"
        f"- Capture ID: `{capture_id}`\n"
        f"- Source commit: `{source_commit}`\n"
        f"- Captured at: `{captured_at}`\n"
        f"- Mode: `{mode}`\n\n"
        f"{authority}\n\n"
        "| Case | Terminal | Tools | Citations | Steps | Model / tool calls | Expected |\n"
        "| --- | --- | --- | ---: | ---: | ---: | --- |\n" + "\n".join(rows) + "\n\n"
        "Generate a new evidence package with `make agent-portfolio-capture`. The command starts "
        "real Uvicorn and Vite services on exact loopback ports, uses Playwright without route "
        "interception, verifies API/UI semantics, strips PNG metadata, hashes artifacts, and "
        "cleans up child processes.\n"
    )


def _artifact_record(path: Path) -> dict[str, str]:
    return {"path": relative_repository_path(path), "sha256": sha256_file(path)}


def _network_record(
    *,
    case: PortfolioCase,
    observation: Mapping[str, object],
    output_dir: Path,
) -> Path:
    request_count = observation.get("request_count")
    server_address = observation.get("server_address")
    request_url = observation.get("request_url")
    if (
        request_count != 1
        or request_url != RUN_URL
        or server_address != "127.0.0.1:8010"
    ):
        raise CaptureError(
            f"case {case.case_id!r} lacks exact real-loopback network evidence"
        )
    path = output_dir / f"{case.case_id}.network.json"
    write_json(path, _expected_network_record(case))
    return path


def _expected_network_record(case: PortfolioCase) -> dict[str, object]:
    return {
        "api_interception": "none",
        "browser_service_workers": "blocked",
        "case_id": case.case_id,
        "method": "POST",
        "request_count": 1,
        "request_url": RUN_URL,
        "server_address": "127.0.0.1:8010",
        "ui_origin": UI_ORIGIN,
    }


def _build_capture_manifest(
    *,
    capture_id: str,
    source_commit: str,
    captured_at: str,
    mode: Literal["deterministic-fixture", "live-zhipu"],
    output_dir: Path,
    repository_dirty: bool,
    cases: Sequence[
        tuple[
            PortfolioCase,
            AgentWorkbenchRunResponse,
            AgentWorkbenchRunResponse | None,
            bool | None,
            bool,
            Path,
        ]
    ],
) -> dict[str, object]:
    case_records: list[dict[str, object]] = []
    for (
        case,
        response,
        api_probe,
        semantic_match,
        expectation_match,
        network_path,
    ) in cases:
        provider, model = _provider_projection(response)
        response_path = output_dir / f"{case.case_id}.response.json"
        summary_path = output_dir / f"{case.case_id}.summary.md"
        screenshot_path = output_dir / f"{case.case_id}.png"
        record: dict[str, object] = {
            "case_id": case.case_id,
            "screenshot_label": case.screenshot_label,
            "query": case.query,
            "query_sha256": hashlib.sha256(case.query.encode()).hexdigest(),
            "scenario_id": case.scenario_id,
            "run_id": str(response.run_id),
            "terminal_status": response.status.value,
            "tool_sequence": tool_sequence(response),
            "claim_count": len(response.claims),
            "citation_count": len(response.citations),
            "step_count": len(response.steps),
            "model_decisions": response.metrics.model_turns,
            "tool_calls": response.metrics.tool_calls,
            "successful_tool_calls": response.metrics.successful_tool_calls,
            "duration_ms": response.metrics.duration_ms,
            "prompt_tokens": response.metrics.prompt_tokens,
            "completion_tokens": response.metrics.completion_tokens,
            "reasoning_tokens": response.metrics.reasoning_tokens,
            "provider": provider,
            "model": model,
            "expected_contract_match": expectation_match,
            "api_ui_semantic_match": semantic_match,
            "artifacts": {
                "response": _artifact_record(response_path),
                "summary": _artifact_record(summary_path),
                "screenshot": _artifact_record(screenshot_path),
                "network": _artifact_record(network_path),
            },
        }
        if api_probe is not None:
            probe_path = output_dir / f"{case.case_id}.api-probe.response.json"
            record["api_probe_run_id"] = str(api_probe.run_id)
            artifacts = record["artifacts"]
            if isinstance(artifacts, dict):
                artifacts["api_probe_response"] = _artifact_record(probe_path)
        case_records.append(record)
    overview_path = output_dir / "overview.png"
    return {
        "schema_version": "agent-workbench-real-capture-v1",
        "capture_id": capture_id,
        "source_commit": source_commit,
        "captured_at": captured_at,
        "repository_dirty_at_capture": repository_dirty,
        "mode": mode,
        "fixture_data_only": True,
        "ci_authoritative": mode == "deterministic-fixture",
        "agent_run_count": len(cases) * (2 if mode == "deterministic-fixture" else 1),
        "max_model_decisions_per_run": 4,
        "max_tool_calls_per_run": 4,
        "browser_api_interception": "none",
        "api_origin": API_ORIGIN,
        "ui_origin": UI_ORIGIN,
        "case_manifest": relative_repository_path(CASE_MANIFEST_PATH),
        "generation_command": (
            "make agent-portfolio-capture"
            if mode == "deterministic-fixture"
            else "make agent-portfolio-live-zhipu-capture"
        ),
        "overview": _artifact_record(overview_path),
        "overview_summary": _artifact_record(output_dir / "overview.md"),
        "cases": case_records,
    }


def _scan_artifacts(root: Path, *, forbidden_secrets: Sequence[str]) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_bytes()
        for secret in forbidden_secrets:
            if secret and secret.encode() in content:
                raise CaptureError(
                    f"artifact {path.name!r} contains configured credential data"
                )
        if path.suffix.lower() in {".json", ".md", ".txt"}:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise CaptureError(
                    f"text artifact {path.name!r} is not UTF-8"
                ) from error
            if _PRIVATE_TEXT.search(text) is not None:
                raise CaptureError(
                    f"artifact {path.name!r} contains private or credential-like text"
                )


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CaptureError(f"{label} is invalid")
    return value


def _require_manifest_value(
    mapping: Mapping[str, object],
    key: str,
    expected: object,
    *,
    label: str,
) -> None:
    if mapping.get(key) != expected:
        raise CaptureError(f"{label} field {key!r} is inconsistent")


def _verify_artifact_record(
    value: object,
    *,
    expected_path: Path,
    capture_root: Path,
    label: str,
) -> Path:
    record = _require_mapping(value, label=f"{label} artifact record")
    expected_relative_path = relative_repository_path(expected_path)
    _require_manifest_value(
        record, "path", expected_relative_path, label=f"{label} artifact record"
    )
    expected_hash = record.get("sha256")
    if (
        not isinstance(expected_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
    ):
        raise CaptureError(f"{label} artifact hash is invalid")
    artifact_path = (REPOSITORY_ROOT / expected_relative_path).resolve()
    if not artifact_path.is_relative_to(capture_root) or not artifact_path.is_file():
        raise CaptureError(f"{label} artifact is missing or escaped its capture")
    if sha256_file(artifact_path) != expected_hash:
        raise CaptureError(f"capture artifact hash mismatch for {artifact_path.name!r}")
    if artifact_path.suffix.lower() == ".png" and png_metadata_chunks(artifact_path):
        raise CaptureError(f"capture PNG {artifact_path.name!r} contains metadata")
    return artifact_path


def _verify_case_record(
    *,
    case: PortfolioCase,
    raw_record: object,
    capture_root: Path,
    capture_id: str,
    source_commit: str,
    mode: Literal["deterministic-fixture", "live-zhipu"],
) -> tuple[AgentWorkbenchRunResponse, bool]:
    record = _require_mapping(raw_record, label=f"case {case.case_id!r}")
    response_path = capture_root / f"{case.case_id}.response.json"
    try:
        response = AgentWorkbenchRunResponse.model_validate_json(
            response_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise CaptureError(
            f"case {case.case_id!r} response is not a typed projection"
        ) from error
    exact_expectations = mode == "deterministic-fixture"
    expectation_match = validate_case_response(
        case, response, exact_expectations=exact_expectations
    )
    provider, model = _provider_projection(response)
    expected_values: dict[str, object] = {
        "case_id": case.case_id,
        "screenshot_label": case.screenshot_label,
        "query": case.query,
        "query_sha256": hashlib.sha256(case.query.encode()).hexdigest(),
        "scenario_id": case.scenario_id,
        "run_id": str(response.run_id),
        "terminal_status": response.status.value,
        "tool_sequence": tool_sequence(response),
        "claim_count": len(response.claims),
        "citation_count": len(response.citations),
        "step_count": len(response.steps),
        "model_decisions": response.metrics.model_turns,
        "tool_calls": response.metrics.tool_calls,
        "successful_tool_calls": response.metrics.successful_tool_calls,
        "duration_ms": response.metrics.duration_ms,
        "prompt_tokens": response.metrics.prompt_tokens,
        "completion_tokens": response.metrics.completion_tokens,
        "reasoning_tokens": response.metrics.reasoning_tokens,
        "provider": provider,
        "model": model,
        "expected_contract_match": expectation_match,
        "api_ui_semantic_match": True if exact_expectations else None,
    }
    for key, expected in expected_values.items():
        _require_manifest_value(record, key, expected, label=f"case {case.case_id!r}")

    artifacts = _require_mapping(
        record.get("artifacts"), label=f"case {case.case_id!r} artifacts"
    )
    expected_artifact_keys = {"response", "summary", "screenshot", "network"}
    if exact_expectations:
        expected_artifact_keys.add("api_probe_response")
    if set(artifacts) != expected_artifact_keys:
        raise CaptureError(f"case {case.case_id!r} artifact catalog is inconsistent")
    _verify_artifact_record(
        artifacts.get("response"),
        expected_path=response_path,
        capture_root=capture_root,
        label=f"case {case.case_id!r} response",
    )
    summary_path = _verify_artifact_record(
        artifacts.get("summary"),
        expected_path=capture_root / f"{case.case_id}.summary.md",
        capture_root=capture_root,
        label=f"case {case.case_id!r} summary",
    )
    _verify_artifact_record(
        artifacts.get("screenshot"),
        expected_path=capture_root / f"{case.case_id}.png",
        capture_root=capture_root,
        label=f"case {case.case_id!r} screenshot",
    )
    network_path = _verify_artifact_record(
        artifacts.get("network"),
        expected_path=capture_root / f"{case.case_id}.network.json",
        capture_root=capture_root,
        label=f"case {case.case_id!r} network",
    )
    try:
        network = json.loads(network_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaptureError(
            f"case {case.case_id!r} network evidence is invalid"
        ) from error
    if network != _expected_network_record(case):
        raise CaptureError(f"case {case.case_id!r} network evidence is inconsistent")

    api_probe: AgentWorkbenchRunResponse | None = None
    semantic_match: bool | None = None
    if exact_expectations:
        probe_path = _verify_artifact_record(
            artifacts.get("api_probe_response"),
            expected_path=capture_root / f"{case.case_id}.api-probe.response.json",
            capture_root=capture_root,
            label=f"case {case.case_id!r} API probe",
        )
        try:
            api_probe = AgentWorkbenchRunResponse.model_validate_json(
                probe_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise CaptureError(
                f"case {case.case_id!r} API probe is not typed"
            ) from error
        validate_case_response(case, api_probe, exact_expectations=True)
        compare_semantics(api_probe, response)
        semantic_match = True
        _require_manifest_value(
            record,
            "api_probe_run_id",
            str(api_probe.run_id),
            label=f"case {case.case_id!r}",
        )
    elif "api_probe_run_id" in record:
        raise CaptureError(
            f"live case {case.case_id!r} unexpectedly claims an API probe"
        )

    expected_summary = _case_summary(
        case=case,
        response=response,
        capture_id=capture_id,
        source_commit=source_commit,
        api_probe=api_probe,
        semantic_match=semantic_match,
        expectation_match=expectation_match,
        mode=mode,
    )
    if summary_path.read_text(encoding="utf-8") != expected_summary:
        raise CaptureError(f"case {case.case_id!r} summary is inconsistent")
    return response, expectation_match


def verify_capture(capture_dir: Path, *, forbidden_secrets: Sequence[str] = ()) -> None:
    resolved_root = capture_dir.resolve()
    if not resolved_root.is_relative_to(CAPTURE_ROOT.resolve()):
        raise CaptureError(
            "capture verification target is outside the portfolio run root"
        )
    manifest_path = resolved_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaptureError("capture manifest is missing or invalid") from error
    if not isinstance(manifest, dict):
        raise CaptureError("capture manifest schema version is invalid")
    manifest_mapping: Mapping[str, object] = manifest
    if manifest_mapping.get("schema_version") != "agent-workbench-real-capture-v1":
        raise CaptureError("capture manifest schema version is invalid")
    mode = manifest_mapping.get("mode")
    if mode == "deterministic-fixture":
        typed_mode: Literal["deterministic-fixture", "live-zhipu"] = (
            "deterministic-fixture"
        )
    elif mode == "live-zhipu":
        typed_mode = "live-zhipu"
    else:
        raise CaptureError("capture manifest mode is invalid")
    capture_id = manifest_mapping.get("capture_id")
    source_commit = manifest_mapping.get("source_commit")
    captured_at = manifest_mapping.get("captured_at")
    if not isinstance(capture_id, str) or not isinstance(captured_at, str):
        raise CaptureError("capture identity is invalid")
    if (
        not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
    ):
        raise CaptureError("capture source commit is invalid")
    if typed_mode == "deterministic-fixture" and capture_id != resolved_root.name:
        raise CaptureError("deterministic capture identity is inconsistent")
    expected_cases = load_case_manifest().cases
    if typed_mode == "live-zhipu":
        expected_cases = tuple(
            case for case in expected_cases if case.case_id == "multi-tool-research"
        )
    top_level_values: dict[str, object] = {
        "fixture_data_only": True,
        "ci_authoritative": typed_mode == "deterministic-fixture",
        "agent_run_count": len(expected_cases)
        * (2 if typed_mode == "deterministic-fixture" else 1),
        "max_model_decisions_per_run": 4,
        "max_tool_calls_per_run": 4,
        "browser_api_interception": "none",
        "api_origin": API_ORIGIN,
        "ui_origin": UI_ORIGIN,
        "case_manifest": relative_repository_path(CASE_MANIFEST_PATH),
        "generation_command": (
            "make agent-portfolio-capture"
            if typed_mode == "deterministic-fixture"
            else "make agent-portfolio-live-zhipu-capture"
        ),
    }
    for key, expected in top_level_values.items():
        _require_manifest_value(
            manifest_mapping, key, expected, label="capture manifest"
        )
    if not isinstance(manifest_mapping.get("repository_dirty_at_capture"), bool):
        raise CaptureError("capture dirty-worktree marker is invalid")
    raw_cases = manifest_mapping.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != len(expected_cases):
        raise CaptureError("capture manifest case catalog is invalid")
    verified_cases: list[tuple[PortfolioCase, AgentWorkbenchRunResponse, bool]] = []
    for case, raw_record in zip(expected_cases, raw_cases, strict=True):
        response, expectation_match = _verify_case_record(
            case=case,
            raw_record=raw_record,
            capture_root=resolved_root,
            capture_id=capture_id,
            source_commit=source_commit,
            mode=typed_mode,
        )
        verified_cases.append((case, response, expectation_match))
    _verify_artifact_record(
        manifest_mapping.get("overview"),
        expected_path=resolved_root / "overview.png",
        capture_root=resolved_root,
        label="capture overview",
    )
    overview_summary_path = _verify_artifact_record(
        manifest_mapping.get("overview_summary"),
        expected_path=resolved_root / "overview.md",
        capture_root=resolved_root,
        label="capture overview summary",
    )
    expected_overview = _overview_markdown(
        capture_id=capture_id,
        source_commit=source_commit,
        captured_at=captured_at,
        mode=typed_mode,
        cases=verified_cases,
    )
    if overview_summary_path.read_text(encoding="utf-8") != expected_overview:
        raise CaptureError("capture overview summary is inconsistent")
    manifest_hash_path = resolved_root / "manifest.sha256"
    expected_manifest_line = f"{sha256_file(manifest_path)}  manifest.json\n"
    if manifest_hash_path.read_text(encoding="ascii") != expected_manifest_line:
        raise CaptureError("capture manifest checksum file is stale")
    _scan_artifacts(resolved_root, forbidden_secrets=forbidden_secrets)


def _git_text(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _capture_identity() -> tuple[str, str, str, bool]:
    source_commit = _git_text("rev-parse", "HEAD")
    short_commit = source_commit[:12]
    captured = datetime.now(UTC).replace(microsecond=0)
    captured_at = captured.isoformat().replace("+00:00", "Z")
    capture_id = f"{short_commit}-{captured.strftime('%Y%m%dT%H%M%SZ')}"
    repository_dirty = bool(
        _git_text("status", "--porcelain", "--untracked-files=normal")
    )
    return capture_id, source_commit, captured_at, repository_dirty


def _capture(
    *,
    mode: Literal["deterministic", "live-zhipu"],
    output_dir: Path,
    capture_id: str,
    source_commit: str,
    captured_at: str,
    repository_dirty: bool,
    live_configuration: LiveConfiguration | None,
    create_output: bool = True,
) -> None:
    case_manifest = load_case_manifest()
    selected_cases = (
        case_manifest.cases
        if mode == "deterministic"
        else tuple(
            case
            for case in case_manifest.cases
            if case.case_id == "multi-tool-research"
        )
    )
    if len(selected_cases) != (3 if mode == "deterministic" else 1):
        raise CaptureError("approved portfolio case selection is invalid")
    if create_output:
        output_dir.mkdir(parents=True, exist_ok=False)
    elif not output_dir.is_dir():
        raise CaptureError("pre-created one-shot output directory is missing")
    browser_observation_path = output_dir / ".browser-observations.json"
    api_probes: dict[str, AgentWorkbenchRunResponse] = {}
    with (
        tempfile.TemporaryDirectory(
            prefix="agent-workbench-services-"
        ) as service_directory,
        local_services(
            temporary_root=Path(service_directory),
            mode=mode,
            live_configuration=live_configuration,
        ),
    ):
        if mode == "deterministic":
            for case in selected_cases:
                probe = _post_direct_case(case)
                validate_case_response(case, probe, exact_expectations=True)
                api_probes[case.case_id] = probe
                write_json(
                    output_dir / f"{case.case_id}.api-probe.response.json",
                    probe.model_dump(mode="json"),
                )
        _run_browser_capture(
            cases_path=CASE_MANIFEST_PATH,
            output_dir=output_dir,
            mode=mode,
            observation_path=browser_observation_path,
        )
    observations = _read_browser_observations(browser_observation_path)
    browser_observation_path.unlink()
    built_cases: list[
        tuple[
            PortfolioCase,
            AgentWorkbenchRunResponse,
            AgentWorkbenchRunResponse | None,
            bool | None,
            bool,
            Path,
        ]
    ] = []
    overview_cases: list[tuple[PortfolioCase, AgentWorkbenchRunResponse, bool]] = []
    for case in selected_cases:
        response = _load_ui_response(output_dir, case)
        expectation_match = validate_case_response(
            case, response, exact_expectations=mode == "deterministic"
        )
        api_probe = api_probes.get(case.case_id)
        semantic_match: bool | None = None
        if api_probe is not None:
            compare_semantics(api_probe, response)
            semantic_match = True
        observation = observations.get(case.case_id)
        if observation is None:
            raise CaptureError(f"case {case.case_id!r} lacks browser network evidence")
        network_path = _network_record(
            case=case, observation=observation, output_dir=output_dir
        )
        screenshot_path = output_dir / f"{case.case_id}.png"
        strip_png_metadata(screenshot_path)
        summary_path = output_dir / f"{case.case_id}.summary.md"
        summary_path.write_text(
            _case_summary(
                case=case,
                response=response,
                capture_id=capture_id,
                source_commit=source_commit,
                api_probe=api_probe,
                semantic_match=semantic_match,
                expectation_match=expectation_match,
                mode="deterministic-fixture"
                if mode == "deterministic"
                else "live-zhipu",
            ),
            encoding="utf-8",
        )
        built_cases.append(
            (case, response, api_probe, semantic_match, expectation_match, network_path)
        )
        overview_cases.append((case, response, expectation_match))
    overview_png = output_dir / "overview.png"
    strip_png_metadata(overview_png)
    overview_md = output_dir / "overview.md"
    manifest_mode: Literal["deterministic-fixture", "live-zhipu"] = (
        "deterministic-fixture" if mode == "deterministic" else "live-zhipu"
    )
    overview_md.write_text(
        _overview_markdown(
            capture_id=capture_id,
            source_commit=source_commit,
            captured_at=captured_at,
            mode=manifest_mode,
            cases=overview_cases,
        ),
        encoding="utf-8",
    )
    forbidden_secrets = (
        (live_configuration.api_key,) if live_configuration is not None else ()
    )
    _scan_artifacts(output_dir, forbidden_secrets=forbidden_secrets)
    manifest = _build_capture_manifest(
        capture_id=capture_id,
        source_commit=source_commit,
        captured_at=captured_at,
        mode=manifest_mode,
        output_dir=output_dir,
        repository_dirty=repository_dirty,
        cases=built_cases,
    )
    manifest_path = output_dir / "manifest.json"
    write_json(manifest_path, manifest)
    (output_dir / "manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  manifest.json\n", encoding="ascii"
    )
    verify_capture(output_dir, forbidden_secrets=forbidden_secrets)
    if mode == "deterministic":
        CURRENT_OVERVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(overview_png, CURRENT_OVERVIEW_PATH)


def capture_deterministic(capture_id_override: str | None = None) -> Path:
    capture_id, source_commit, captured_at, repository_dirty = _capture_identity()
    if capture_id_override is not None:
        if _SAFE_CASE_ID.fullmatch(capture_id_override) is None:
            raise CaptureError("capture ID override must be lowercase kebab-case")
        capture_id = capture_id_override
    CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
    final_output = CAPTURE_ROOT / capture_id
    if final_output.exists():
        raise CaptureError("deterministic capture output already exists")
    try:
        _capture(
            mode="deterministic",
            output_dir=final_output,
            capture_id=capture_id,
            source_commit=source_commit,
            captured_at=captured_at,
            repository_dirty=repository_dirty,
            live_configuration=None,
        )
    except Exception:
        if final_output.is_dir() and final_output.is_relative_to(CAPTURE_ROOT):
            shutil.rmtree(final_output)
        raise
    verify_capture(final_output)
    return final_output


def capture_live_once() -> Path:
    configuration = load_live_configuration()
    capture_id, source_commit, captured_at, repository_dirty = _capture_identity()
    if LIVE_OUTPUT_PATH.exists():
        raise CaptureError(
            "the one-shot live Zhipu capture path has already been attempted"
        )
    LIVE_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIVE_OUTPUT_PATH.mkdir()
    attempt_path = LIVE_OUTPUT_PATH / "attempt.json"
    write_json(
        attempt_path,
        {
            "attempted_at": captured_at,
            "case_id": "multi-tool-research",
            "max_agent_runs": 1,
            "max_model_decisions": 4,
            "status": "started",
        },
    )
    try:
        _capture(
            mode="live-zhipu",
            output_dir=LIVE_OUTPUT_PATH,
            capture_id=f"live-zhipu-{capture_id}",
            source_commit=source_commit,
            captured_at=captured_at,
            repository_dirty=repository_dirty,
            live_configuration=configuration,
            create_output=False,
        )
        write_json(
            attempt_path,
            {
                "attempted_at": captured_at,
                "case_id": "multi-tool-research",
                "max_agent_runs": 1,
                "max_model_decisions": 4,
                "status": "completed",
            },
        )
    except Exception:
        write_json(
            attempt_path,
            {
                "attempted_at": captured_at,
                "capture_phase": "before_evidence_verification",
                "case_id": "multi-tool-research",
                "max_agent_runs": 1,
                "max_model_decisions": 4,
                "retry_performed": False,
                "screenshot_preserved": False,
                "status": "failed_closed",
                "typed_response_preserved": (
                    LIVE_OUTPUT_PATH / "multi-tool-research.response.json"
                ).is_file(),
            },
        )
        write_json(
            LIVE_OUTPUT_PATH / "safe-failure.json",
            {
                "attempted_at": captured_at,
                "case_id": "multi-tool-research",
                "message": "The one authorized live capture stopped safely and was not retried.",
                "status": "failed_closed",
            },
        )
        raise
    return LIVE_OUTPUT_PATH


def live_preflight() -> None:
    load_case_manifest()
    load_live_configuration()
    if LIVE_OUTPUT_PATH.exists():
        raise CaptureError("the one-shot live Zhipu output path already exists")
    for executable in ("git", "node", "npm"):
        if shutil.which(executable) is None:
            raise CaptureError(f"required executable {executable!r} is unavailable")
    ensure_port_available("127.0.0.1", 8010)
    ensure_port_available("127.0.0.1", 5173)
    browser_probe = subprocess.run(
        [
            "node",
            "-e",
            (
                "const {createRequire}=require('node:module');"
                "const {existsSync}=require('node:fs');"
                "const r=createRequire(process.argv[1]);"
                "const {chromium}=r('@playwright/test');"
                "process.exit(existsSync(chromium.executablePath())?0:1)"
            ),
            str(FRONTEND_ROOT / "package.json"),
        ],
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        env=vite_environment(),
    )
    if browser_probe.returncode != 0:
        raise CaptureError("the checked Playwright Chromium binary is unavailable")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    deterministic = subparsers.add_parser(
        "deterministic", help="Capture the three provider-free real loopback cases."
    )
    deterministic.add_argument("--capture-id", default=None)
    live = subparsers.add_parser(
        "live-zhipu",
        help="Execute the single authorized live Zhipu browser run exactly once.",
    )
    live.add_argument("--execute-authorized-once", action="store_true", required=True)
    subparsers.add_parser(
        "preflight-live", help="Validate the one-shot live path without a call."
    )
    verify = subparsers.add_parser(
        "verify", help="Verify hashes, links, privacy, and PNG metadata."
    )
    verify.add_argument("capture_dir", type=Path)
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(arguments)
    try:
        if args.command == "deterministic":
            output = capture_deterministic(args.capture_id)
            print(f"Verified deterministic capture: {relative_repository_path(output)}")
        elif args.command == "live-zhipu":
            output = capture_live_once()
            print(f"Verified one-shot live capture: {relative_repository_path(output)}")
        elif args.command == "preflight-live":
            live_preflight()
            print(
                "Live preflight ready: one fixture-only Agent run, at most four model decisions, "
                f"output {relative_repository_path(LIVE_OUTPUT_PATH)}"
            )
        elif args.command == "verify":
            verify_capture(args.capture_dir)
            print(f"Verified capture: {relative_repository_path(args.capture_dir)}")
        else:
            raise CaptureError("unknown capture command")
    except (CaptureError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Agent Workbench capture failed safely: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
