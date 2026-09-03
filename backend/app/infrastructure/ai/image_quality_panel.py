"""Direct Zhipu GLM-5V-Turbo transport and pricing composition for image evaluation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from hashlib import sha256
from typing import Annotated, Any, Literal, Self, cast

import httpx
from evals.image_quality_panel.models import ALL_MODEL_SPECS
from evals.image_quality_panel.planning import MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS
from evals.model_panel import (
    AtomicPanelBudget,
    AttemptJournal,
    NativeCost,
    OneShotExecution,
    OpenAICompatibleEndpoint,
    OpenAICompatibleJudgeTransport,
    OpenAICompatibleRequestProfile,
    PanelManifest,
    PanelModelIdentity,
    ProviderNativeLimit,
    evidence_sha256,
)
from evals.model_panel.transport import NativeCostExtractor
from pydantic import BaseModel, ConfigDict, Field, model_validator

ZHIPU_CHAT_COMPLETIONS_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
ZHIPU_NATIVE_CAP = Decimal("100")
PRICE_QUANTUM = Decimal("0.00000001")
IMAGE_PANEL_TRANSPORT_ADAPTER_VERSION = "image-panel-zhipu-glm-5v-turbo-one-shot-v3"

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonNegativeRate = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=8)]
PositiveCost = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=8)]


class ImagePanelLiveAdapterError(ValueError):
    """A pricing, identity, route, or budget binding is not the frozen live plan."""


class FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class ImagePanelModelPrice(FrozenModel):
    model_ref: str = Field(min_length=1, max_length=192)
    provider: Literal["zhipu"]
    requested_model: str = Field(min_length=1, max_length=192)
    native_unit: Literal["cny"]
    input_per_million_tokens: NonNegativeRate
    output_per_million_tokens: NonNegativeRate
    reasoning_per_million_tokens: NonNegativeRate
    maximum_native_cost_per_call: PositiveCost

    @model_validator(mode="after")
    def conservative_reservation(self) -> Self:
        expected = price_token_usage(
            self,
            input_tokens=MAX_INPUT_TOKENS,
            output_tokens=MAX_OUTPUT_TOKENS,
            reasoning_tokens=MAX_OUTPUT_TOKENS,
        )
        if self.maximum_native_cost_per_call != expected:
            raise ValueError("per-call reservation must equal the conservative token ceiling")
        return self


class ImagePanelPricingSnapshot(FrozenModel):
    schema_version: Literal["image-panel-zhipu-pricing-snapshot-v1"]
    pricing_version: str = Field(min_length=1, max_length=192)
    effective_at: datetime
    expires_at: datetime
    pricing_source_sha256: Sha256Hex
    zhipu_cny_cap: Decimal
    models: tuple[ImagePanelModelPrice]
    snapshot_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if (
            self.effective_at.tzinfo is None
            or self.effective_at.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError("pricing validity window must be timezone-aware")
        if self.effective_at >= self.expires_at:
            raise ValueError("pricing validity window must be increasing")
        expected = {
            spec.model_ref: (spec.provider, spec.requested_model) for spec in ALL_MODEL_SPECS
        }
        actual = {item.model_ref: (item.provider, item.requested_model) for item in self.models}
        if actual != expected or tuple(item.model_ref for item in self.models) != tuple(
            sorted(expected)
        ):
            raise ValueError("pricing snapshot must contain only GLM-5V-Turbo on Zhipu")
        if self.models[0].native_unit != "cny":
            raise ValueError("pricing native unit must be CNY")
        if self.zhipu_cny_cap != ZHIPU_NATIVE_CAP:
            raise ValueError("pricing snapshot must preserve the approved Zhipu hard cap")
        payload = self.model_dump(mode="json", exclude={"snapshot_sha256"})
        if evidence_sha256(payload) != self.snapshot_sha256:
            raise ValueError("pricing snapshot SHA-256 does not match its payload")
        return self


def price_token_usage(
    price: ImagePanelModelPrice,
    *,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
) -> Decimal:
    if min(input_tokens, output_tokens, reasoning_tokens) < 0:
        raise ImagePanelLiveAdapterError("token usage cannot be negative")
    amount = (
        Decimal(input_tokens) * price.input_per_million_tokens
        + Decimal(output_tokens) * price.output_per_million_tokens
        + Decimal(reasoning_tokens) * price.reasoning_per_million_tokens
    ) / Decimal(1_000_000)
    return amount.quantize(PRICE_QUANTUM, rounding=ROUND_CEILING)


def build_panel_identities(
    snapshot: ImagePanelPricingSnapshot,
) -> tuple[PanelModelIdentity, ...]:
    prices = {item.model_ref: item for item in snapshot.models}
    identities = []
    for spec in ALL_MODEL_SPECS:
        endpoint = _endpoint_for_provider(spec.provider)
        identities.append(
            PanelModelIdentity(
                identity_ref=spec.model_ref,
                gateway=spec.gateway,
                provider=spec.provider,
                model_family=spec.model_ref,
                requested_model=spec.requested_model,
                returned_model=spec.requested_model,
                endpoint_host_sha256=sha256(endpoint.host.encode("ascii")).hexdigest(),
                adapter_version=IMAGE_PANEL_TRANSPORT_ADAPTER_VERSION,
                pricing_snapshot_sha256=snapshot.snapshot_sha256,
            )
        )
        if prices[spec.model_ref].requested_model != spec.requested_model:
            raise ImagePanelLiveAdapterError("pricing model identity drifted")
    return tuple(sorted(identities, key=lambda item: item.identity_ref))


def provider_native_limits(
    snapshot: ImagePanelPricingSnapshot,
) -> tuple[ProviderNativeLimit]:
    return (
        ProviderNativeLimit(
            provider_ref="zhipu",
            unit="cny",
            maximum=snapshot.zhipu_cny_cap,
        ),
    )


def maximum_native_cost_by_model(
    snapshot: ImagePanelPricingSnapshot,
) -> dict[str, Decimal]:
    return {item.model_ref: item.maximum_native_cost_per_call for item in snapshot.models}


def validate_manifest_pricing_binding(
    manifest: PanelManifest,
    snapshot: ImagePanelPricingSnapshot,
) -> None:
    if snapshot.effective_at > manifest.created_at:
        raise ImagePanelLiveAdapterError("pricing snapshot postdates the frozen manifest")
    if snapshot.expires_at < manifest.execution_window_end:
        raise ImagePanelLiveAdapterError(
            "pricing validity window does not cover the frozen execution window"
        )
    identities = build_panel_identities(snapshot)
    if manifest.identities != identities:
        raise ImagePanelLiveAdapterError("manifest identities do not match pricing and endpoints")
    if manifest.provider_native_limits != provider_native_limits(snapshot):
        raise ImagePanelLiveAdapterError("manifest provider hard caps or native units drifted")
    maximums = maximum_native_cost_by_model(snapshot)
    if any(
        binding.maximum_native_cost != maximums[binding.evaluator_model_ref]
        for binding in manifest.attempt_bindings
    ):
        raise ImagePanelLiveAdapterError("manifest per-call reservations drifted from pricing")
    provider_by_model = {
        identity.identity_ref: identity.provider for identity in manifest.identities
    }
    planned_maximums = {"zhipu": Decimal("0")}
    for binding in manifest.attempt_bindings:
        provider = provider_by_model[binding.evaluator_model_ref]
        planned_maximums[provider] += binding.maximum_native_cost
    caps = {limit.provider_ref: limit.maximum for limit in provider_native_limits(snapshot)}
    if any(planned_maximums[provider] > caps[provider] for provider in planned_maximums):
        raise ImagePanelLiveAdapterError("planned conservative native cost exceeds a hard cap")


def create_image_panel_executions(
    *,
    client: httpx.AsyncClient,
    manifest: PanelManifest,
    snapshot: ImagePanelPricingSnapshot,
    zhipu_bearer_token: str,
    budget: AtomicPanelBudget,
    journal: AttemptJournal,
    clock: Callable[[], datetime],
    monotonic: Callable[[], float],
) -> dict[str, OneShotExecution]:
    """Construct the unique direct Zhipu transport; no route selection or fallback remains."""

    validate_manifest_pricing_binding(manifest, snapshot)
    if not zhipu_bearer_token:
        raise ImagePanelLiveAdapterError("the Zhipu live credential is required")
    prices = {item.model_ref: item for item in snapshot.models}
    executions: dict[str, OneShotExecution] = {}
    for identity in manifest.identities:
        endpoint = _endpoint_for_provider(identity.provider)
        transport = OpenAICompatibleJudgeTransport(
            client=client,
            endpoint=OpenAICompatibleEndpoint(
                chat_completions_url=endpoint.url,
                allowed_hosts=(endpoint.host,),
                allowed_models=(identity.requested_model,),
            ),
            bearer_token=zhipu_bearer_token,
            native_cost_extractor=token_pricing_cost_extractor(prices[identity.identity_ref]),
            request_profile=OpenAICompatibleRequestProfile.ZHIPU_VISION,
        )
        executions[identity.identity_ref] = OneShotExecution(
            transport=transport,
            budget=budget,
            journal=journal,
            clock=clock,
            monotonic=monotonic,
        )
    if len(executions) != 1:
        raise ImagePanelLiveAdapterError("exactly one GLM-5V-Turbo transport is required")
    return executions


def token_pricing_cost_extractor(
    price: ImagePanelModelPrice,
) -> NativeCostExtractor:
    """Compute native cost from a frozen token-rate snapshot; missing usage stays unknown."""

    def extract(response: dict[str, Any]) -> NativeCost | None:
        usage = response.get("usage")
        if usage is None:
            return None
        if not isinstance(usage, dict):
            raise ValueError("provider usage has an invalid shape")
        input_tokens = _one_usage_integer(usage, "prompt_tokens", "input_tokens")
        output_tokens = _one_usage_integer(
            usage,
            "completion_tokens",
            "output_tokens",
        )
        reasoning_value = usage.get("reasoning_tokens")
        if reasoning_value is None:
            if price.reasoning_per_million_tokens > 0:
                return None
            reasoning_tokens = 0
        elif (
            isinstance(reasoning_value, bool)
            or not isinstance(reasoning_value, int)
            or not 0 <= reasoning_value <= 10_000_000
        ):
            raise ValueError("provider reasoning-token usage is invalid")
        else:
            reasoning_tokens = reasoning_value
        return NativeCost(
            unit=price.native_unit,
            amount=price_token_usage(
                price,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
            ),
        )

    return extract


class _Endpoint(FrozenModel):
    url: str
    host: str


def _endpoint_for_provider(provider: str) -> _Endpoint:
    if provider == "zhipu":
        return _Endpoint(
            url=ZHIPU_CHAT_COMPLETIONS_URL,
            host="open.bigmodel.cn",
        )
    raise ImagePanelLiveAdapterError("only the direct Zhipu route is allowlisted")


def _one_usage_integer(value: dict[str, Any], *keys: str) -> int:
    present = [value[key] for key in keys if key in value]
    if len(present) != 1:
        raise ValueError("provider usage must contain exactly one compatible token field")
    item = present[0]
    if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 10_000_000:
        raise ValueError("provider token usage is outside bounds")
    return cast(int, item)
