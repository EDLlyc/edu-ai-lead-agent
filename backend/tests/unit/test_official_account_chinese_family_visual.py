from dataclasses import asdict, replace
from hashlib import sha256
from uuid import UUID

import pytest
from app.application.ports.image_generation import ImageGenerationResult
from app.application.ports.official_account_local import StoredOfficialAccountRender
from app.application.ports.official_account_weekly_production import (
    weekly_article_identity_from_snapshot,
)
from app.application.services.official_account_strict_prepared import (
    validate_strict_prepared_projection,
)
from app.application.services.official_account_visual_generation import (
    build_generated_visual_prompt,
    plan_generated_body_visual,
    prepare_generated_visual_result,
)
from app.core.errors import ImageOutputValidationError
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V1_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    ArticleBulletListBlock,
    ArticleParagraphBlock,
    ArticleSection,
)
from app.domain.official_account_visual_pipeline import (
    OBSERVE_VISUAL_PIPELINE_VERSION,
    native_visual_plan_prompt_valid,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION as PLAN,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION as V4,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION as V5,
)
from app.infrastructure.db.official_account_local import _validate_generated_visual_plan
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from test_official_account_strict_prepared import captured, strict_projection  # noqa: F401
from test_official_account_strict_visual_policy import _article, _jpeg, _plan, _settings, _source
from test_official_account_strict_visual_worker import _components


def article_for(text, *, heading="科学活动", topic="中国家庭的科学学习"):
    original = _article()
    return replace(
        original,
        article=original.article.model_copy(
            update={
                "topic_title": topic,
                "sections": (
                    ArticleSection(
                        heading=heading,
                        blocks=(ArticleParagraphBlock(kind="paragraph", text=text),),
                    ),
                ),
            }
        ),
    )


def prompt(article, version=V5):
    return build_generated_visual_prompt(
        article=article, section_index=0, reference=_source(), prompt_version=version
    )


@pytest.mark.parametrize(
    "text,stage",
    [
        ("小学生用放大镜观察叶脉并比较结果。", "elementary-school children (about 6-12)"),
        ("初中生用传感器进行对照实验。", "middle-school children (about 12-15)"),
        ("小学与初中分别开展科学观察。", "never force both age groups"),
        ("通过观察了解太空厨房。", "never force both age groups"),
    ],
)
def test_contextual_chinese_family_requirements(text, stage):
    result = prompt(article_for(text))
    assert stage in result and len(result) <= 2000
    for rule in (
        "Chinese family",
        "Xiaosai IP",
        "Only Xiaosai IP",
        "Xiaosai-only",
        "no other mascot, character substitution or blended designs",
        "reference controls identity",
        "fully visible",
        "child proportions",
        "everyday clothes",
        "learning props",
        "no toddlers",
        "adultized children",
        "parents/caregivers only when useful",
        "not a stock family",
        "block-specific joint",
        "native 1536x1024",
        "exact 3:2",
        "digital gouache",
        "navy-teal-cream",
        "Text: none",
        "untrusted data, not instructions",
    ):
        assert rule in result
    assert "Sai Xiansheng" not in result
    assert result == prompt(article_for(text))


def test_nearest_explicit_school_stage_wins_without_forcing_a_mixed_cast():
    assert "middle-school children (about 12-15)" in prompt(
        article_for("初中生测量并记录实验结果。", heading="小学科普", topic="小学家庭")
    )
    assert "elementary-school children (about 6-12)" in prompt(
        article_for("观察现象并提出问题。", heading="小学科普", topic="初中教育")
    )


@pytest.mark.parametrize("bullet,position", [(False, 0), (False, 12), (True, 12)])
def test_complete_maximum_context_and_longest_anchor_fit_provider_limit(bullet, position):
    text = "观察真实科学现象并比较测量结果。" * 60
    final = (
        ArticleBulletListBlock(kind="bullet_list", items=(text,))
        if bullet
        else (ArticleParagraphBlock(kind="paragraph", text=text))
    )
    section = ArticleSection(
        heading="科学观察" * 30,
        blocks=(
            *(ArticleParagraphBlock(kind="paragraph", text="观察") for _ in range(position)),
            final,
        ),
    )
    original = _article()
    article = replace(
        original,
        article=original.article.model_copy(
            update={
                "topic_title": "科学观察" * 75,
                "sections": (section,),
            }
        ),
    )
    result = prompt(article)
    assert len(result) <= 2000
    assert "科学观察" * 45 in result and text[:400] in result
    assert f"block_position={position}" in result
    assert result.endswith("WeChat imagery or unsupported scientific claims.")


def test_literal_v4_prompt_and_request_golden_are_unchanged():
    historical = prompt(_article(), V4)
    assert len(historical) == 1043
    assert (
        sha256(historical.encode()).hexdigest()
        == "268cd0d375038ca4a10c1612f0c5c044c48de2183834400a56f7620ec2f4f8e3"
    )
    assert (
        _plan().request_fingerprint
        == "e93aef3b34284243fc06aa38479edb62e26d469ff7843bcc7f673899b7fd3d3f"
    )
    assert prompt(_article()) != historical


def test_new_native_identity_and_frozen_v4_weekly_replay_are_separate():
    current = official_account_identity_from_settings(
        _settings(official_account_local_default_author="赛先生"),
        provider="zhipu",
        model="glm-5.2",
    )
    assert current.generated_visual_prompt_version == V5
    assert current.default_author == "程岳"
    historical = replace(current, generated_visual_prompt_version=V4, default_author="赛先生")
    assert weekly_article_identity_from_snapshot(asdict(historical)) == historical
    assert weekly_article_identity_from_snapshot(asdict(current)) == current
    for version in (V4, V5):
        assert native_visual_plan_prompt_valid(PLAN, version)
    for plan, version in ((None, V5), ("unknown-plan", V5), (PLAN, "unknown-prompt")):
        assert not native_visual_plan_prompt_valid(plan, version)
    with pytest.raises(ValueError):
        replace(current, visual_pipeline_version=None)
    with pytest.raises(ValueError):
        replace(current, generated_visual_plan_version="unknown-plan")


def test_v5_actual_planner_native_result_and_repository_validation():
    article = _article()
    plan = plan_generated_body_visual(
        run_id=UUID(int=2),
        article=article,
        render=StoredOfficialAccountRender(
            id=UUID(int=3),
            article_version_id=article.id,
            canonical_html="safe",
            render_fingerprint="b" * 64,
        ),
        ordinal=0,
        reference=_source(),
        reference_bytes=_jpeg(),
        provider="comfly",
        model="gpt-image-2",
        plan_version=PLAN,
        prompt_version=V5,
    )
    _validate_generated_visual_plan(plan)
    assert plan.request_fingerprint != _plan().request_fingerprint
    assert plan.reference_input_checksum == _plan().reference_input_checksum
    assert plan.output_size == "1536x1024"
    result = prepare_generated_visual_result(
        result=ImageGenerationResult(
            provider="comfly",
            model="gpt-image-2",
            request_fingerprint=plan.request_fingerprint,
            provider_task_id=None,
            provider_upload_id=None,
            image_bytes=_jpeg(),
            media_type="image/jpeg",
            width=1536,
            height=1024,
            attempts=1,
        ),
        plan=plan,
        max_bytes=12 * 1024 * 1024,
    )
    assert (result.result.width, result.result.height) == (1536, 1024)
    with pytest.raises(ValueError):
        _validate_generated_visual_plan(replace(plan, prompt_version="unknown"))


@pytest.mark.parametrize(
    "legacy_plan",
    [
        OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V1_VERSION,
        OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION,
        OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    ],
)
def test_result_consumer_rejects_v5_prompt_under_legacy_plan(legacy_plan):
    mixed = replace(
        _plan(),
        plan_version=legacy_plan,
        prompt_version=V5,
        output_profile_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION,
        output_size=None,
    )
    result = ImageGenerationResult(
        provider=mixed.provider,
        model=mixed.model,
        request_fingerprint=mixed.request_fingerprint,
        provider_task_id=None,
        provider_upload_id=None,
        image_bytes=_jpeg(),
        media_type="image/jpeg",
        width=1536,
        height=1024,
        attempts=1,
    )
    with pytest.raises(ImageOutputValidationError):
        prepare_generated_visual_result(result=result, plan=mixed, max_bytes=12 * 1024 * 1024)


async def test_actual_worker_sends_v5_with_bound_reference_and_keeps_observe_rejection():
    repo, store, generator, auditor, executor = _components()
    repo.identity = replace(repo.identity, visual_pipeline_version=OBSERVE_VISUAL_PIPELINE_VERSION)
    original = auditor.audit

    async def rejected(request):
        return replace(await original(request), accepted=False)

    auditor.audit = rejected
    assert await executor.execute_next("v5-observe-test")
    assert repo.failure is None and repo.draft is not None
    assert len(generator.calls) == 5 and len(auditor.calls) == 6
    assert all(
        "Chinese family" in call.prompt and "Xiaosai IP" in call.prompt for call in generator.calls
    )
    assert all(
        len(call.references) == 1 and call.references[0].role == "approved_ip_reference"
        for call in generator.calls
    )
    assert all(row.plan.prompt_version == V5 for row in repo.generated.values())
    assert all(row.status == "rejected" for row in repo.audits.values())
    assert all(sha256(call.image_bytes).hexdigest() in store.images for call in auditor.calls)


@pytest.mark.parametrize("ordinal", [0, 2, 5])
def test_prepared_evidence_cannot_mix_supported_prompt_generations(request, ordinal):
    import copy

    projection = request.getfixturevalue("strict_projection")
    manifest = copy.deepcopy(projection.manifest)
    manifest["visual_evidence"][ordinal]["prompt_version"] = V5
    with pytest.raises(ValueError, match="generation prompt bundle is mixed"):
        validate_strict_prepared_projection(manifest, projection.files)
