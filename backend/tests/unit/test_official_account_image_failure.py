from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from app.application.ports.image_generation import ImageGenerationRequest
from app.application.ports.official_account_strict_visual import StrictGeneratedVisualClaim
from app.core.errors import (
    ImageGenerationFailure,
    ImageOutputValidationError,
    ImageProviderConfigurationError,
    ImageProviderQuotaError,
    ImageProviderRejectedError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    StrictImageGenerationError,
    classify_image_generation_failure,
)
from app.infrastructure.ai.official_account_visual_strict import (
    LazyStrictOfficialAccountImageGenerator,
)
from structlog.testing import capture_logs
from test_official_account_native_observe import _observe_components
from test_official_account_strict_visual_policy import _image_reference, _settings
from test_official_account_strict_visual_worker import _components

SENTINEL = "secret-private-body-https://private.example/token"


def _request():
    return ImageGenerationRequest(
        run_id=uuid4(),
        draft_version_id=uuid4(),
        prompt="Generate a new educational scene using the approved reference. " * 3,
        request_fingerprint="f" * 64,
        references=(_image_reference(),),
        reference_mode="single_reference",
        output_size="1536x1024",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,disposition,reason,status",
    [
        (httpx.ConnectError, "not_applied_retryable", "connect_failed", None),
        (httpx.ConnectTimeout, "not_applied_retryable", "connect_timeout", None),
        (httpx.PoolTimeout, "not_applied_retryable", "pool_timeout", None),
        (httpx.ReadTimeout, "unknown", "post_outcome_unknown", None),
        (httpx.WriteTimeout, "unknown", "post_outcome_unknown", None),
        (httpx.WriteError, "unknown", "post_outcome_unknown", None),
        (429, "not_applied_retryable", "post_rate_limited", 429),
        (500, "unknown", "post_outcome_unknown", 500),
        (502, "unknown", "post_outcome_unknown", 502),
        (401, "terminal", "provider_failure", 401),
        (403, "terminal", "provider_failure", 403),
        (400, "terminal", "provider_failure", 400),
        (200, "terminal", "provider_failure", 200),
    ],
)
async def test_actual_one_shot_adapter_proves_only_non_applied_errors_retry(
    failure, disposition, reason, status
):
    seen = []

    def handler(request):
        seen.append(request)
        if isinstance(failure, type):
            raise failure(SENTINEL, request=request)
        return httpx.Response(failure, json={"private_message": SENTINEL})

    adapter = LazyStrictOfficialAccountImageGenerator(
        _settings(), transport_factory=lambda: httpx.MockTransport(handler)
    )
    with pytest.raises(StrictImageGenerationError) as caught:
        await adapter.generate(_request())
    assert len(seen) == 1
    diagnostic = caught.value.diagnostic
    assert diagnostic.disposition == disposition
    assert diagnostic.reason == reason
    assert diagnostic.http_status == status
    assert caught.value.retryable == (disposition == "not_applied_retryable")
    assert SENTINEL not in str(caught.value)
    assert SENTINEL not in repr(caught.value)
    assert SENTINEL not in json.dumps(diagnostic.safe_metadata())
    assert (
        ImageGenerationFailure.from_safe_metadata(diagnostic.safe_metadata()["image_failure"])
        == diagnostic
    )


@pytest.mark.asyncio
async def test_poll_connect_failure_cannot_authorize_repeating_successful_post():
    seen = []

    def handler(request):
        seen.append(request.method)
        if request.method == "POST":
            return httpx.Response(
                200, json={"data": {"task_id": "synthetic-task", "status": "IN_PROGRESS"}}
            )
        raise httpx.ConnectError(SENTINEL, request=request)

    adapter = LazyStrictOfficialAccountImageGenerator(
        _settings(), transport_factory=lambda: httpx.MockTransport(handler)
    )
    with pytest.raises(StrictImageGenerationError) as caught:
        await adapter.generate(_request())
    assert seen == ["POST", "GET"]
    assert caught.value.diagnostic.disposition == "unknown"
    assert not caught.value.retryable


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 200])
async def test_post_accepted_then_poll_error_retains_unknown_outcome(status):
    seen = []

    def handler(request):
        seen.append(request.method)
        if request.method == "POST":
            return httpx.Response(
                200, json={"data": {"task_id": "synthetic-task", "status": "IN_PROGRESS"}}
            )
        return httpx.Response(status, json={"private_message": SENTINEL})

    adapter = LazyStrictOfficialAccountImageGenerator(
        _settings(), transport_factory=lambda: httpx.MockTransport(handler)
    )
    with pytest.raises(StrictImageGenerationError) as caught:
        await adapter.generate(_request())
    assert seen == ["POST", "GET"]
    assert caught.value.diagnostic.disposition == "unknown"
    assert caught.value.diagnostic.http_status == status
    assert not caught.value.retryable
    assert SENTINEL not in json.dumps(caught.value.diagnostic.safe_metadata())


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 403, 429, 500, 200])
async def test_download_failure_is_unknown_but_fetched_invalid_pixels_are_terminal(status):
    seen = []

    def handler(request):
        seen.append(request.method)
        if request.method == "POST":
            return httpx.Response(
                200, json={"data": [{"url": "https://93.184.216.34/fixture.png"}]}
            )
        assert "authorization" not in request.headers
        return httpx.Response(
            status, content=b"invalid-raster", headers={"content-type": "image/png"}
        )

    adapter = LazyStrictOfficialAccountImageGenerator(
        _settings(), transport_factory=lambda: httpx.MockTransport(handler)
    )
    with pytest.raises(StrictImageGenerationError) as caught:
        await adapter.generate(_request())
    assert seen == ["POST", "GET"]
    assert caught.value.diagnostic.disposition == ("terminal" if status == 200 else "unknown")
    assert caught.value.diagnostic.http_status == status
    assert not caught.value.retryable


@pytest.mark.asyncio
async def test_configuration_drift_is_terminal_without_constructing_paid_client():
    def no_transport():
        pytest.fail("invalid generation policy must not construct a transport")

    adapter = LazyStrictOfficialAccountImageGenerator(
        _settings().model_copy(update={"comfly_api_key": None}), transport_factory=no_transport
    )
    with pytest.raises(ImageProviderConfigurationError) as caught:
        await adapter.generate(_request())
    assert classify_image_generation_failure(caught.value).disposition == "terminal"


@pytest.mark.asyncio
@pytest.mark.parametrize("components", [_components, _observe_components])
@pytest.mark.parametrize("http_status", [429, 500])
async def test_real_transport_failure_reaches_worker_persistence_boundary(components, http_status):
    repo, _store, _generator, auditor, executor = components()
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(http_status, json={"private_message": SENTINEL})

    executor._strict_image_generator = LazyStrictOfficialAccountImageGenerator(
        _settings(), transport_factory=lambda: httpx.MockTransport(handler)
    )
    assert await executor.execute_next("transport-to-worker")
    assert len(seen) == 1 and not auditor.calls
    assert repo.failure_retryable == (http_status == 429)
    assert repo.generated[0].status == ("failed" if http_status == 429 else "result_unknown")


@pytest.mark.parametrize("error", [ProviderUnavailableError(), ProviderRateLimitError()])
def test_unproven_retryable_exception_is_unknown(error):
    assert error.retryable
    assert classify_image_generation_failure(error).disposition == "unknown"


@pytest.mark.parametrize(
    "mutation",
    [
        {"http_status": True},
        {"http_status": 700},
        {"reason": SENTINEL},
        {"reason": []},
        {"response_kind": SENTINEL},
        {"response_kind": []},
        {"raw_body": SENTINEL},
        {"disposition": "not_applied_retryable"},
        {"version": "other"},
    ],
)
def test_failure_metadata_decoder_is_closed_and_never_retries_forged_proof(mutation):
    original = classify_image_generation_failure(RuntimeError(SENTINEL))
    payload = original.safe_metadata()["image_failure"] | mutation
    assert ImageGenerationFailure.from_safe_metadata(payload) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("components", [_components, _observe_components])
@pytest.mark.parametrize(
    "error,unknown,retryable",
    [
        (
            StrictImageGenerationError(
                ImageGenerationFailure(
                    "provider_unavailable", "not_applied_retryable", "connect_failed"
                )
            ),
            False,
            True,
        ),
        (ProviderAuthenticationError(), False, False),
        (ImageProviderRejectedError(http_status=400), False, False),
        (ImageProviderQuotaError(), False, False),
        (ImageOutputValidationError("image_dimensions_invalid"), False, False),
        (ProviderUnavailableError(), True, False),
        (RuntimeError(SENTINEL), True, False),
    ],
)
async def test_real_worker_carries_safe_diagnostic_to_image_run_and_log(
    components, error, unknown, retryable
):
    repo, _store, generator, auditor, executor = components()
    observed = {}
    fail_image, fail_run = repo.fail_generated_visual, repo.fail

    async def record_image(**kwargs):
        observed["image"] = kwargs["diagnostic"]
        return await fail_image(**kwargs)

    async def record_run(**kwargs):
        observed["run"] = kwargs["safe_metadata"]
        return await fail_run(**kwargs)

    async def generate(request):
        generator.calls.append(request)
        raise error

    repo.fail_generated_visual, repo.fail, generator.generate = record_image, record_run, generate
    with capture_logs() as logs:
        assert await executor.execute_next("failure-classification")
    expected = classify_image_generation_failure(error)
    assert observed["image"] == expected
    assert observed["run"] == expected.safe_metadata()
    assert repo.failure[1] == unknown
    assert repo.failure_retryable == retryable
    assert repo.generated[0].status == ("result_unknown" if unknown else "failed")
    assert repo.draft is None and len(generator.calls) == 1 and not auditor.calls
    assert repo.article is not None and repo.render is not None
    log = next(item for item in logs if item["event"] == "official_account_image_generation_failed")
    assert log["safe_metadata"] == expected.safe_metadata()
    assert log["stage"] == "generating_body_visuals" and log["attempt"] == 1
    assert SENTINEL not in json.dumps(logs)
    if unknown:
        repo.claimed = False
        assert await executor.execute_next("unknown-cannot-replay")
        assert len(generator.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("components", [_components, _observe_components])
async def test_worker_resumes_safe_failed_slot_and_reuses_article_and_ready_images(components):
    repo, _store, generator, auditor, executor = components()
    original_generate = generator.generate
    failed = False
    dispatches = []

    async def generate(request):
        nonlocal failed
        dispatches.append(request.request_fingerprint)
        if len(generator.calls) == 2 and not failed:
            failed = True
            raise StrictImageGenerationError(
                ImageGenerationFailure(
                    "provider_unavailable", "not_applied_retryable", "connect_failed"
                )
            )
        return await original_generate(request)

    generator.generate = generate
    assert await executor.execute_next("initial-safe-failure")
    assert repo.failure_retryable and len(generator.calls) == 2
    article, rendered = repo.article, repo.render
    ready = dict(repo.generated)
    claim = repo.claim_strict_generated_visual

    async def reclaim_proven_slot(*, claimed, plan):
        # Unit fake grants the repository contract; PostgreSQL tests prove the durable predicate.
        if repo.generated.get(plan.ordinal) and repo.generated[plan.ordinal].status == "failed":
            assert plan.ordinal == 2
            value = replace(repo.generated[plan.ordinal], status="generating", error_code=None)
            repo.generated[plan.ordinal] = value
            return StrictGeneratedVisualClaim("newly_claimed", value)
        return await claim(claimed=claimed, plan=plan)

    repo.claim_strict_generated_visual = reclaim_proven_slot
    repo.claimed, repo.failure = False, None
    assert await executor.execute_next("resume-safe-failure")
    assert repo.failure is None and repo.draft is not None
    assert len(dispatches) == 6 and len(generator.calls) == 5 and len(auditor.calls) == 6
    assert dispatches[2] == dispatches[3]
    assert repo.article is article and repo.render is rendered
    assert all(repo.generated[index] is ready[index] for index in (0, 1))


@pytest.mark.asyncio
async def test_worker_cancellation_is_not_swallowed_or_recorded_as_known_failure():
    repo, _store, generator, auditor, executor = _components()

    async def generate(request):
        generator.calls.append(request)
        raise asyncio.CancelledError()

    generator.generate = generate
    with pytest.raises(asyncio.CancelledError):
        await executor.execute_next("cancel")
    assert repo.failure is None and repo.generated[0].status == "generating"
    repo.claimed = False
    assert await executor.execute_next("cancel-recovery")
    assert len(generator.calls) == 1 and not auditor.calls


@pytest.mark.asyncio
async def test_compensation_dispatch_preserves_logical_identity_but_uses_distinct_provider_key():
    repo, _store, generator, _auditor, executor = _components()
    original_claim = repo.claim_strict_generated_visual

    async def claim(**kwargs):
        result = await original_claim(**kwargs)
        return replace(result, provider_request_fingerprint="e" * 64)

    repo.claim_strict_generated_visual = claim
    assert await executor.execute_next("compensated")
    assert repo.draft is not None
    assert all(request.provider_request_fingerprint == "e" * 64 for request in generator.calls)
    assert all(request.request_fingerprint != "e" * 64 for request in generator.calls)
