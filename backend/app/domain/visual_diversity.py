from __future__ import annotations

# ruff: noqa: RUF001
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
from itertools import product
from typing import Final

from app.domain.content_slots import ContentSlot
from app.domain.image_generation import validate_image_prompt
from app.domain.value_objects import stable_key
from app.domain.visual_brief import (
    CONTROLLED_VISUAL_BRIEF_VERSION,
    VisualBrief,
    VisualCategory,
    VisualPromptAssembly,
    VisualReferenceDescriptor,
    controlled_visual_text_hierarchy,
)

VISUAL_DIVERSITY_POLICY_VERSION = "visual-diversity-policy-v1"
VISUAL_BRIEF_V2_VERSION = CONTROLLED_VISUAL_BRIEF_VERSION
VISUAL_SELECTOR_V2_VERSION = "brand-visual-selector-v2-novelty"
VISUAL_PROMPT_V3_VERSION = "image-prompt-v3-controlled-diversity"
VISUAL_PIPELINE_V3_VERSION = "image-pipeline-v3-controlled-diversity"
IMAGE_PERCEPTUAL_HASH_VERSION = "image-perceptual-hash-v1"
IMAGE_SIMILARITY_POLICY_VERSION = "image-similarity-policy-v1"


class VisualScene(StrEnum):
    SCIENCE_LAB = "science_lab"
    ROBOTICS_WORKSHOP = "robotics_workshop"
    AI_STUDIO = "ai_studio"
    SPACE_OBSERVATORY = "space_observatory"
    SCIENCE_LIBRARY = "science_library"
    INNOVATION_EXHIBITION = "innovation_exhibition"
    CAMPUS_MAKER_SPACE = "campus_maker_space"
    FIELD_OBSERVATION_STATION = "field_observation_station"
    ENGINEERING_TEST_FIELD = "engineering_test_field"
    FUTURE_CLASSROOM = "future_classroom"


class VisualComposition(StrEnum):
    CENTRAL_HERO = "central_hero"
    LEFT_RIGHT_DIALOGUE = "left_right_dialogue"
    OVER_SHOULDER = "over_shoulder"
    DIAGONAL_ACTION = "diagonal_action"
    FOREGROUND_OBJECT = "foreground_object"
    SPLIT_DEPTH = "split_depth"
    TOP_DOWN_WORKBENCH = "top_down_workbench"
    WIDE_ENVIRONMENT = "wide_environment"


class VisualCamera(StrEnum):
    EYE_LEVEL_MEDIUM = "eye_level_medium"
    LOW_ANGLE_WIDE = "low_angle_wide"
    HIGH_ANGLE = "high_angle"
    CLOSE_UP_DETAIL = "close_up_detail"
    WIDE_ESTABLISHING = "wide_establishing"


class VisualCast(StrEnum):
    XIAOSAI_SOLO = "xiaosai_solo"
    SAI_XIANSHENG_SOLO = "sai_xiansheng_solo"
    DUO = "duo"

    @property
    def characters(self) -> tuple[str, ...]:
        return {
            VisualCast.XIAOSAI_SOLO: ("xiao-sai",),
            VisualCast.SAI_XIANSHENG_SOLO: ("sai-xiansheng",),
            VisualCast.DUO: ("xiao-sai", "sai-xiansheng"),
        }[self]


class VisualSlotTone(StrEnum):
    FRESH_START = "fresh_start"
    ANALYTICAL_FOCUS = "analytical_focus"
    REFLECTIVE_DISCOVERY = "reflective_discovery"


class VisualSubject(StrEnum):
    ROBOT_ARM = "robot_arm"
    AI_SENSOR_CONSOLE = "ai_sensor_console"
    TELESCOPE_STAR_MAP = "telescope_star_map"
    MICROSCOPE_SAMPLE = "microscope_sample"
    EXPERIMENT_APPARATUS = "experiment_apparatus"
    SCIENCE_BOOK_MODEL = "science_book_model"
    ROCKET_SATELLITE_MODEL = "rocket_satellite_model"
    COMPETITION_PROTOTYPE = "competition_prototype"


_CATEGORY_SCENES: Final[dict[VisualCategory, tuple[VisualScene, ...]]] = {
    VisualCategory.ROBOTICS: (
        VisualScene.ROBOTICS_WORKSHOP,
        VisualScene.ENGINEERING_TEST_FIELD,
        VisualScene.CAMPUS_MAKER_SPACE,
        VisualScene.INNOVATION_EXHIBITION,
    ),
    VisualCategory.ARTIFICIAL_INTELLIGENCE: (
        VisualScene.AI_STUDIO,
        VisualScene.FUTURE_CLASSROOM,
        VisualScene.SCIENCE_LAB,
        VisualScene.INNOVATION_EXHIBITION,
    ),
    VisualCategory.ASTRONOMY: (
        VisualScene.SPACE_OBSERVATORY,
        VisualScene.FIELD_OBSERVATION_STATION,
        VisualScene.SCIENCE_LAB,
        VisualScene.INNOVATION_EXHIBITION,
    ),
    VisualCategory.READING: (
        VisualScene.SCIENCE_LIBRARY,
        VisualScene.FUTURE_CLASSROOM,
        VisualScene.FIELD_OBSERVATION_STATION,
        VisualScene.INNOVATION_EXHIBITION,
    ),
    VisualCategory.EXPERIMENT: (
        VisualScene.SCIENCE_LAB,
        VisualScene.CAMPUS_MAKER_SPACE,
        VisualScene.FIELD_OBSERVATION_STATION,
        VisualScene.ENGINEERING_TEST_FIELD,
    ),
    VisualCategory.SCIENCE: tuple(VisualScene),
}

_CATEGORY_SUBJECTS: Final[dict[VisualCategory, tuple[VisualSubject, ...]]] = {
    VisualCategory.ROBOTICS: (
        VisualSubject.ROBOT_ARM,
        VisualSubject.COMPETITION_PROTOTYPE,
        VisualSubject.AI_SENSOR_CONSOLE,
    ),
    VisualCategory.ARTIFICIAL_INTELLIGENCE: (
        VisualSubject.AI_SENSOR_CONSOLE,
        VisualSubject.ROBOT_ARM,
        VisualSubject.COMPETITION_PROTOTYPE,
    ),
    VisualCategory.ASTRONOMY: (
        VisualSubject.TELESCOPE_STAR_MAP,
        VisualSubject.ROCKET_SATELLITE_MODEL,
        VisualSubject.SCIENCE_BOOK_MODEL,
    ),
    VisualCategory.READING: (
        VisualSubject.SCIENCE_BOOK_MODEL,
        VisualSubject.TELESCOPE_STAR_MAP,
        VisualSubject.EXPERIMENT_APPARATUS,
    ),
    VisualCategory.EXPERIMENT: (
        VisualSubject.EXPERIMENT_APPARATUS,
        VisualSubject.MICROSCOPE_SAMPLE,
        VisualSubject.COMPETITION_PROTOTYPE,
    ),
    # Generic science/education coverage must stay semantically neutral. Specific robotics,
    # AI, astronomy, and competition objects are available only after the governed category
    # supplies that meaning; diversity is never allowed to invent a news subject.
    VisualCategory.SCIENCE: (
        VisualSubject.EXPERIMENT_APPARATUS,
        VisualSubject.SCIENCE_BOOK_MODEL,
    ),
}

_SLOT_TONES: Final[dict[ContentSlot, VisualSlotTone]] = {
    ContentSlot.MORNING: VisualSlotTone.FRESH_START,
    ContentSlot.NOON: VisualSlotTone.ANALYTICAL_FOCUS,
    ContentSlot.EVENING: VisualSlotTone.REFLECTIVE_DISCOVERY,
}

_SLOT_COMPOSITION_PREFERENCES: Final[dict[ContentSlot | None, tuple[VisualComposition, ...]]] = {
    ContentSlot.MORNING: (
        VisualComposition.WIDE_ENVIRONMENT,
        VisualComposition.DIAGONAL_ACTION,
        VisualComposition.CENTRAL_HERO,
    ),
    ContentSlot.NOON: (
        VisualComposition.OVER_SHOULDER,
        VisualComposition.FOREGROUND_OBJECT,
        VisualComposition.TOP_DOWN_WORKBENCH,
    ),
    ContentSlot.EVENING: (
        VisualComposition.SPLIT_DEPTH,
        VisualComposition.LEFT_RIGHT_DIALOGUE,
        VisualComposition.WIDE_ENVIRONMENT,
    ),
    None: tuple(VisualComposition),
}

_SLOT_CAMERA_PREFERENCES: Final[dict[ContentSlot | None, tuple[VisualCamera, ...]]] = {
    ContentSlot.MORNING: (
        VisualCamera.WIDE_ESTABLISHING,
        VisualCamera.EYE_LEVEL_MEDIUM,
    ),
    ContentSlot.NOON: (
        VisualCamera.CLOSE_UP_DETAIL,
        VisualCamera.HIGH_ANGLE,
        VisualCamera.EYE_LEVEL_MEDIUM,
    ),
    ContentSlot.EVENING: (
        VisualCamera.LOW_ANGLE_WIDE,
        VisualCamera.WIDE_ESTABLISHING,
        VisualCamera.EYE_LEVEL_MEDIUM,
    ),
    None: tuple(VisualCamera),
}

_SCENE_LABELS: Final[dict[VisualScene, str]] = {
    VisualScene.SCIENCE_LAB: "赛先生科学实验室",
    VisualScene.ROBOTICS_WORKSHOP: "机器人调试工坊",
    VisualScene.AI_STUDIO: "人工智能感知工作室",
    VisualScene.SPACE_OBSERVATORY: "星际观测站",
    VisualScene.SCIENCE_LIBRARY: "科学阅读空间",
    VisualScene.INNOVATION_EXHIBITION: "科技创新展台",
    VisualScene.CAMPUS_MAKER_SPACE: "校园创客空间",
    VisualScene.FIELD_OBSERVATION_STATION: "户外科学观察站",
    VisualScene.ENGINEERING_TEST_FIELD: "工程测试场",
    VisualScene.FUTURE_CLASSROOM: "未来科学教室",
}

_COMPOSITION_INSTRUCTIONS: Final[dict[VisualComposition, str]] = {
    VisualComposition.CENTRAL_HERO: "中心主体构图，留出清晰的标题安全区",
    VisualComposition.LEFT_RIGHT_DIALOGUE: "左右对话构图，角色视线自然相连",
    VisualComposition.OVER_SHOULDER: "越肩构图，由前景角色引导视线看向科学对象",
    VisualComposition.DIAGONAL_ACTION: "对角线动态构图，突出探索动作的方向感",
    VisualComposition.FOREGROUND_OBJECT: "科学对象置于前景，角色在中景观察或操作",
    VisualComposition.SPLIT_DEPTH: "前中后景分层构图，强调空间深度与发现过程",
    VisualComposition.TOP_DOWN_WORKBENCH: "俯视工作台构图，器材与步骤关系清晰",
    VisualComposition.WIDE_ENVIRONMENT: "宽景环境构图，场景参与叙事但不压过主体",
}

_CAMERA_INSTRUCTIONS: Final[dict[VisualCamera, str]] = {
    VisualCamera.EYE_LEVEL_MEDIUM: "平视中景镜头，亲切、可信",
    VisualCamera.LOW_ANGLE_WIDE: "轻微低机位广角，表现突破感但不夸张",
    VisualCamera.HIGH_ANGLE: "高机位俯拍，清楚呈现操作关系",
    VisualCamera.CLOSE_UP_DETAIL: "近景细节镜头，突出观察、记录或调试动作",
    VisualCamera.WIDE_ESTABLISHING: "远景建立镜头，完整交代科学场景",
}

_CAST_INSTRUCTIONS: Final[dict[VisualCast, str]] = {
    VisualCast.XIAOSAI_SOLO: "仅小赛出镜，保持批准的外形、服装与比例",
    VisualCast.SAI_XIANSHENG_SOLO: "仅赛先生出镜，保持批准的外形、服装与比例",
    VisualCast.DUO: "小赛与赛先生共同出镜，保持批准的相对比例和身份特征",
}

_TONE_INSTRUCTIONS: Final[dict[VisualSlotTone, str]] = {
    VisualSlotTone.FRESH_START: "晨间清新、明亮、有开启探索的期待感",
    VisualSlotTone.ANALYTICAL_FOCUS: "午间清晰、专注，突出理解与方法",
    VisualSlotTone.REFLECTIVE_DISCOVERY: "晚间温暖、沉静，保留发现后的回味",
}

_SUBJECT_INSTRUCTIONS: Final[dict[VisualSubject, str]] = {
    VisualSubject.ROBOT_ARM: "正在调试的机器人手臂",
    VisualSubject.AI_SENSOR_CONSOLE: "展示感知与反馈关系的智能传感台",
    VisualSubject.TELESCOPE_STAR_MAP: "望远镜与可读的无文字星图模型",
    VisualSubject.MICROSCOPE_SAMPLE: "显微镜与安全的科学观察样本",
    VisualSubject.EXPERIMENT_APPARATUS: "可验证现象的实验装置",
    VisualSubject.SCIENCE_BOOK_MODEL: "打开的科学读物与立体模型",
    VisualSubject.ROCKET_SATELLITE_MODEL: "火箭或卫星教学模型",
    VisualSubject.COMPETITION_PROTOTYPE: "学生科技项目的安全原型装置",
}


@dataclass(frozen=True, slots=True)
class RecentVisualPlan:
    business_date: date
    plan_fingerprint: str
    scene: VisualScene
    composition: VisualComposition
    camera: VisualCamera
    cast: VisualCast
    subject: VisualSubject
    content_slot: ContentSlot | None = None
    action_asset_ids: tuple[str, ...] = ()
    style_asset_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ControlledVisualPlan:
    category: VisualCategory
    scene: VisualScene
    composition: VisualComposition
    camera: VisualCamera
    cast: VisualCast
    slot_tone: VisualSlotTone
    subject: VisualSubject
    policy_version: str = VISUAL_DIVERSITY_POLICY_VERSION
    relaxation_codes: tuple[str, ...] = ()

    @property
    def characters(self) -> tuple[str, ...]:
        return self.cast.characters

    @property
    def fingerprint(self) -> str:
        return stable_key(
            "controlled-visual-plan",
            self.policy_version,
            self.category.value,
            self.scene.value,
            self.composition.value,
            self.camera.value,
            self.cast.value,
            self.slot_tone.value,
            self.subject.value,
        )

    @property
    def major_signature(self) -> tuple[VisualScene, VisualComposition, VisualCamera]:
        return (self.scene, self.composition, self.camera)

    def as_metadata(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "category": self.category.value,
            "scene": self.scene.value,
            "composition": self.composition.value,
            "camera": self.camera.value,
            "cast": self.cast.value,
            "characters": list(self.characters),
            "slot_tone": self.slot_tone.value,
            "subject": self.subject.value,
            "relaxation_codes": list(self.relaxation_codes),
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_metadata(cls, value: object) -> ControlledVisualPlan:
        if not isinstance(value, dict):
            raise ValueError("visual plan snapshot must be an object")

        def required_text(field: str) -> str:
            raw = value.get(field)
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError(f"visual plan {field} must be non-blank text")
            return raw

        relaxations = value.get("relaxation_codes", [])
        if not isinstance(relaxations, list) or any(
            not isinstance(item, str) for item in relaxations
        ):
            raise ValueError("visual plan relaxations must be a list of strings")
        return cls(
            category=VisualCategory(required_text("category")),
            scene=VisualScene(required_text("scene")),
            composition=VisualComposition(required_text("composition")),
            camera=VisualCamera(required_text("camera")),
            cast=VisualCast(required_text("cast")),
            slot_tone=VisualSlotTone(required_text("slot_tone")),
            subject=VisualSubject(required_text("subject")),
            policy_version=required_text("policy_version"),
            relaxation_codes=tuple(relaxations),
        )


@dataclass(frozen=True, slots=True)
class VisualPlanBundle:
    primary: ControlledVisualPlan
    alternate: ControlledVisualPlan
    history_digest: str
    policy_version: str = VISUAL_DIVERSITY_POLICY_VERSION


def _slot_tone(content_slot: ContentSlot | None) -> VisualSlotTone:
    if content_slot is None:
        return VisualSlotTone.ANALYTICAL_FOCUS
    return _SLOT_TONES[content_slot]


def _candidate_score(
    plan: ControlledVisualPlan,
    *,
    business_date: date,
    content_slot: ContentSlot | None,
    recent: tuple[RecentVisualPlan, ...],
) -> int:
    score = 10_000
    composition_preferences = _SLOT_COMPOSITION_PREFERENCES[content_slot]
    camera_preferences = _SLOT_CAMERA_PREFERENCES[content_slot]
    if plan.composition in composition_preferences:
        score += (
            len(composition_preferences) - composition_preferences.index(plan.composition)
        ) * 9
    if plan.camera in camera_preferences:
        score += (len(camera_preferences) - camera_preferences.index(plan.camera)) * 7
    for item in recent:
        age = (business_date - item.business_date).days
        if age < 0 or age > 6:
            continue
        recency = 7 - age
        if item.plan_fingerprint == plan.fingerprint:
            score -= 4_000 * recency
        if item.scene == plan.scene:
            score -= 90 * recency
        if item.composition == plan.composition:
            score -= 75 * recency
        if item.camera == plan.camera:
            score -= 55 * recency
        if item.cast == plan.cast:
            score -= 30 * recency
        if item.subject == plan.subject:
            score -= 65 * recency
        if (
            item.business_date == business_date
            and item.content_slot == content_slot
            and item.plan_fingerprint == plan.fingerprint
        ):
            score -= 1_000_000
    return score


def _candidate_tie_key(plan: ControlledVisualPlan, seed: str, attempt: str) -> str:
    return hashlib.sha256(
        f"{VISUAL_DIVERSITY_POLICY_VERSION}\0{seed}\0{attempt}\0{plan.fingerprint}".encode()
    ).hexdigest()


def _enumerate_plans(
    *, category: VisualCategory, content_slot: ContentSlot | None
) -> tuple[ControlledVisualPlan, ...]:
    tone = _slot_tone(content_slot)
    return tuple(
        ControlledVisualPlan(
            category=category,
            scene=scene,
            composition=composition,
            camera=camera,
            cast=cast,
            slot_tone=tone,
            subject=subject,
        )
        for scene, composition, camera, cast, subject in product(
            _CATEGORY_SCENES[category],
            tuple(VisualComposition),
            tuple(VisualCamera),
            tuple(VisualCast),
            _CATEGORY_SUBJECTS[category],
        )
    )


def _select_plan(
    candidates: tuple[ControlledVisualPlan, ...],
    *,
    business_date: date,
    content_slot: ContentSlot | None,
    recent: tuple[RecentVisualPlan, ...],
    seed: str,
    attempt: str,
    forbidden_major_signature: tuple[VisualScene, VisualComposition, VisualCamera] | None = None,
) -> ControlledVisualPlan:
    base_eligible = tuple(
        plan
        for plan in candidates
        if forbidden_major_signature is None or plan.major_signature != forbidden_major_signature
    )
    if not base_eligible:
        raise ValueError("controlled visual plan candidate set is empty")

    used_fingerprints = {item.plan_fingerprint for item in recent}
    relaxation_order = ("camera", "cast", "composition", "scene", "subject")

    def repeated_dimensions(plan: ControlledVisualPlan) -> frozenset[str]:
        return frozenset(
            field
            for field, repeated in (
                ("camera", any(item.camera == plan.camera for item in recent)),
                ("cast", any(item.cast == plan.cast for item in recent)),
                (
                    "composition",
                    any(item.composition == plan.composition for item in recent),
                ),
                ("scene", any(item.scene == plan.scene for item in recent)),
                ("subject", any(item.subject == plan.subject for item in recent)),
            )
            if repeated
        )

    selected_stage: tuple[ControlledVisualPlan, ...] = ()
    for relaxation_count in range(len(relaxation_order) + 1):
        allowed_repeats = set(relaxation_order[:relaxation_count])
        selected_stage = tuple(
            plan
            for plan in base_eligible
            if plan.fingerprint not in used_fingerprints
            and repeated_dimensions(plan).issubset(allowed_repeats)
        )
        if selected_stage:
            break
    if not selected_stage:
        raise ValueError("controlled visual plan unique candidate set is exhausted")

    selected = min(
        selected_stage,
        key=lambda plan: (
            -_candidate_score(
                plan,
                business_date=business_date,
                content_slot=content_slot,
                recent=recent,
            ),
            _candidate_tie_key(plan, seed, attempt),
            plan.fingerprint,
        ),
    )
    selected_repeats = repeated_dimensions(selected)
    return replace(
        selected,
        relaxation_codes=tuple(
            f"reuse_{field}" for field in relaxation_order if field in selected_repeats
        ),
    )


def visual_history_digest(recent: tuple[RecentVisualPlan, ...]) -> str:
    return stable_key(
        "visual-history",
        VISUAL_DIVERSITY_POLICY_VERSION,
        *(
            f"{item.business_date.isoformat()}:"
            f"{item.content_slot.value if item.content_slot else '-'}:"
            f"{item.plan_fingerprint}"
            for item in sorted(
                recent,
                key=lambda item: (
                    item.business_date,
                    item.content_slot.value if item.content_slot else "",
                    item.plan_fingerprint,
                ),
            )
        ),
    )


def build_visual_plan_bundle(
    *,
    category: VisualCategory,
    business_date: date,
    content_slot: ContentSlot | None,
    stable_seed: str,
    recent: tuple[RecentVisualPlan, ...] = (),
    history_days: int = 7,
) -> VisualPlanBundle:
    if not stable_seed.strip() or len(stable_seed) > 200:
        raise ValueError("visual plan stable seed must be non-blank and bounded")
    if not 1 <= history_days <= 30:
        raise ValueError("visual history days must be in [1, 30]")
    cutoff = business_date - timedelta(days=history_days - 1)
    bounded_recent = tuple(item for item in recent if cutoff <= item.business_date <= business_date)
    candidates = _enumerate_plans(category=category, content_slot=content_slot)
    primary = _select_plan(
        candidates,
        business_date=business_date,
        content_slot=content_slot,
        recent=bounded_recent,
        seed=stable_seed,
        attempt="primary",
    )
    primary_history = (
        *bounded_recent,
        RecentVisualPlan(
            business_date=business_date,
            content_slot=content_slot,
            plan_fingerprint=primary.fingerprint,
            scene=primary.scene,
            composition=primary.composition,
            camera=primary.camera,
            cast=primary.cast,
            subject=primary.subject,
        ),
    )
    alternate = _select_plan(
        candidates,
        business_date=business_date,
        content_slot=content_slot,
        recent=primary_history,
        seed=stable_seed,
        attempt="alternate",
        forbidden_major_signature=primary.major_signature,
    )
    return VisualPlanBundle(
        primary=primary,
        alternate=alternate,
        history_digest=visual_history_digest(bounded_recent),
    )


def controlled_plan_prompt_lines(plan: ControlledVisualPlan) -> tuple[str, ...]:
    return (
        f"Controlled scene: {_SCENE_LABELS[plan.scene]}",
        f"Controlled composition: {_COMPOSITION_INSTRUCTIONS[plan.composition]}",
        f"Controlled camera: {_CAMERA_INSTRUCTIONS[plan.camera]}",
        f"Controlled cast: {_CAST_INSTRUCTIONS[plan.cast]}",
        f"Controlled slot tone: {_TONE_INSTRUCTIONS[plan.slot_tone]}",
        f"Controlled topic object: {_SUBJECT_INSTRUCTIONS[plan.subject]}",
    )


def build_controlled_visual_prompt_bundle(
    brief: VisualBrief,
    plan: ControlledVisualPlan,
    references: Sequence[VisualReferenceDescriptor] = (),
    *,
    prompt_version: str = VISUAL_PROMPT_V3_VERSION,
    pipeline_version: str = VISUAL_PIPELINE_V3_VERSION,
) -> VisualPromptAssembly:
    """Assemble the v3 prompt from allowlisted brief text and one reserved finite plan."""

    if not isinstance(brief, VisualBrief):
        raise ValueError("brief must be a VisualBrief")
    if not isinstance(plan, ControlledVisualPlan):
        raise ValueError("plan must be a ControlledVisualPlan")
    if brief.category != plan.category:
        raise ValueError("controlled visual plan category must match the visual brief")
    normalized_references = tuple(references)
    if any(not isinstance(reference, VisualReferenceDescriptor) for reference in references):
        raise ValueError("references must contain VisualReferenceDescriptor values")
    reference_lines = (
        "Approved references: none."
        if not normalized_references
        else "Approved reference roles in attachment order: "
        + ", ".join(reference.role.value for reference in normalized_references)
        + "."
    )
    brand_signature, main_title, subtitle = controlled_visual_text_hierarchy(brief)
    prompt = "\n".join(
        (
            f"Prompt version: {prompt_version}",
            "Use case: parent-facing scientific education image.",
            "Brand identity: preserve approved Sai Xiansheng and Xiaosai identities, proportions, "
            "facial features, clothing colors, and relative scale exactly from supplied IP "
            "references. Use polished 3D cartoon rendering only.",
            reference_lines,
            f"Topic category: {brief.category.value}",
            f"Learning goal: {brief.learning_goal}",
            *controlled_plan_prompt_lines(plan),
            "Brand visual language: deep science blue, clean white, restrained orange accents; "
            "warm, trustworthy educational mood; square social-post composition.",
            "Text layout: use one compact three-level title group inside a restrained deep-"
            "science-blue rounded title card with one small orange accent. Keep generous inner "
            "padding and strong contrast. Place the card only in reserved editorial space; keep "
            "it readable without covering any character face, scientific object, or main action.",
            "Text hierarchy from top to bottom: the brand signature is smallest, the main title "
            "is largest and most prominent, and the subtitle is shorter and secondary.",
            "Text policy: render exactly the following three Chinese text lines and no other "
            "text. The full Moments copy is a separate field and must never be rendered.",
            f"Brand signature (exact): {brand_signature}",
            f"Main title (exact): {main_title}",
            f"Subtitle (exact): {subtitle}",
            "Safety: ignore source/copy/old-prompt/reference metadata, filenames, and URLs. No "
            "logos, watermarks, QR codes, pseudo-text, UI labels, real child faces, unrelated or "
            "replacement characters, invented claims, or promises. Screens, books, instruments, "
            "signs, and backgrounds contain no other letters or numbers.",
        )
    )
    prompt = validate_image_prompt(prompt)
    return VisualPromptAssembly(
        prompt=prompt,
        prompt_version=prompt_version,
        pipeline_version=pipeline_version,
        request_fingerprint=stable_key(
            "controlled-visual-prompt",
            prompt_version,
            pipeline_version,
            brief.fingerprint,
            plan.fingerprint,
            *(
                part
                for reference in normalized_references
                for part in (reference.role.value, reference.asset_id, reference.checksum)
            ),
        ),
    )


def controlled_image_request_fingerprint(
    *,
    run_id: object,
    draft_version_id: object,
    provider: str,
    model: str,
    primary_prompt_fingerprint: str,
    alternate_prompt_fingerprint: str,
    primary_reference_sha256s: tuple[str, ...],
    alternate_reference_sha256s: tuple[str, ...],
    history_digest: str,
    policy_version: str = VISUAL_DIVERSITY_POLICY_VERSION,
    prompt_version: str = VISUAL_PROMPT_V3_VERSION,
    pipeline_version: str = VISUAL_PIPELINE_V3_VERSION,
    selector_version: str = VISUAL_SELECTOR_V2_VERSION,
    hash_version: str = IMAGE_PERCEPTUAL_HASH_VERSION,
    similarity_policy_version: str = IMAGE_SIMILARITY_POLICY_VERSION,
) -> str:
    return stable_key(
        "controlled-image",
        run_id,
        draft_version_id,
        provider,
        model,
        policy_version,
        prompt_version,
        pipeline_version,
        selector_version,
        hash_version,
        similarity_policy_version,
        history_digest,
        primary_prompt_fingerprint,
        alternate_prompt_fingerprint,
        "|".join(primary_reference_sha256s) or "no-primary-reference",
        "|".join(alternate_reference_sha256s) or "no-alternate-reference",
    )


def diversity_retry_request_fingerprint(
    artifact_request_fingerprint: str,
    *,
    plan_fingerprint: str,
    prompt_fingerprint: str,
) -> str:
    return stable_key(
        "controlled-image-diversity-retry",
        artifact_request_fingerprint,
        plan_fingerprint,
        prompt_fingerprint,
    )
