from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.brand_knowledge import (
    STRUCTURED_BRAND_DERIVATION_VERSIONS,
    STRUCTURED_BRAND_RETRIEVAL_VERSION,
    SUPPORTED_BRAND_DERIVATION_VERSIONS,
    SUPPORTED_BRAND_RETRIEVAL_VERSIONS,
)
from app.domain.content_slots import DEFAULT_SLOT_RANKING_VERSION, ContentSlot, ContentSlotSchedule
from app.domain.copy_generation import ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION
from app.domain.image_generation import IMAGE_REFERENCE_BUDGET_BYTES
from app.domain.image_similarity import DEFAULT_IMAGE_SIMILARITY_THRESHOLD
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
    OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
    OFFICIAL_ACCOUNT_RULE_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
)
from app.domain.topic_rerank import (
    DEFAULT_TOPIC_RERANK_POLICY_VERSION,
    SUPPORTED_TOPIC_RERANK_POLICY_VERSIONS,
)
from app.domain.visual_diversity import (
    IMAGE_PERCEPTUAL_HASH_VERSION,
    IMAGE_SIMILARITY_POLICY_VERSION,
    VISUAL_BRIEF_V2_VERSION,
    VISUAL_DIVERSITY_POLICY_VERSION,
    VISUAL_PIPELINE_V3_VERSION,
    VISUAL_PROMPT_V3_VERSION,
    VISUAL_SELECTOR_V2_VERSION,
)
from app.domain.visual_retrieval import VisualEmbeddingIdentity


class Settings(BaseSettings):
    """Validated local configuration with safe development defaults."""

    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_browser_origins: str = Field(
        default="http://127.0.0.1:5173", min_length=1, max_length=1_000
    )
    business_timezone: str = "Asia/Shanghai"

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://edu_ai:edu_ai_local_change_me@127.0.0.1:5432/edu_ai"
    )
    minio_endpoint: str = "http://127.0.0.1:9000"
    minio_bucket: str = "edu-ai-materials"
    minio_secure: bool = False
    minio_access_key: SecretStr = SecretStr("edu_ai_minio")
    minio_secret_key: SecretStr = SecretStr("edu_ai_minio_local_change_me")

    acquisition_schedule_hour: int = Field(default=6, ge=0, le=23)
    acquisition_schedule_minute: int = Field(default=30, ge=0, le=59)
    acquisition_catchup_hours: int = Field(default=12, ge=1, le=24)
    acquisition_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    acquisition_worker_concurrency: int = Field(default=4, ge=1, le=32)
    acquisition_lease_seconds: int = Field(default=120, ge=30, le=3600)
    acquisition_heartbeat_seconds: int = Field(default=30, ge=5, le=600)
    acquisition_max_attempts: int = Field(default=3, ge=1, le=10)
    acquisition_max_response_bytes: int = Field(
        default=5 * 1024 * 1024, ge=64 * 1024, le=50 * 1024 * 1024
    )
    acquisition_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    acquisition_read_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    acquisition_total_timeout_seconds: float = Field(default=45.0, gt=0, le=180)
    acquisition_max_redirects: int = Field(default=3, ge=0, le=10)
    acquisition_max_retry_after_seconds: int = Field(default=300, ge=0, le=3600)
    acquisition_user_agent: str = (
        "EduAILeadAgent/0.1 (+https://github.com/EDLlyc/edu-ai-lead-agent)"
    )
    acquisition_first_run_item_limit: int = Field(default=20, ge=1, le=100)
    acquisition_daily_item_limit: int = Field(default=10, ge=1, le=50)
    acquisition_first_run_scan_limit: int = Field(default=100, ge=1, le=500)
    acquisition_daily_scan_limit: int = Field(default=50, ge=1, le=200)
    acquisition_freshness_window_days: int = Field(default=10, ge=1, le=365)
    acquisition_version: str = "acquisition-v6-broad-hard-tech"

    governance_enabled: bool = False
    governance_scheduler_enabled: bool = False
    governance_worker_enabled: bool = False
    governance_poll_seconds: float = Field(default=5.0, ge=0.1, le=300)
    governance_worker_concurrency: int = Field(default=2, ge=1, le=16)
    governance_lease_seconds: int = Field(default=300, ge=60, le=3600)
    governance_heartbeat_seconds: int = Field(default=60, ge=5, le=600)
    governance_max_attempts: int = Field(default=3, ge=1, le=10)
    governance_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    governance_pipeline_version: str = "governance-v1"
    governance_normalization_version: str = "normalization-v1"
    governance_passage_schema_version: str = "passage-v1"
    governance_taxonomy_version: str = "ai-factual-taxonomy-v1"
    governance_prompt_version: str = "factual-analysis-v1"
    governance_analysis_schema_version: str = "factual-analysis-schema-v1"
    governance_embedding_input_version: str = "embedding-input-v1"
    governance_similarity_rule_version: str = "semantic-v1"
    governance_event_assignment_version: str = "event-assignment-v1"
    governance_checkpoint_database_url: SecretStr = SecretStr(
        "postgresql://edu_ai:edu_ai_local_change_me@127.0.0.1:5432/edu_ai"
    )

    content_enabled: bool = False
    content_scheduler_enabled: bool = False
    content_worker_enabled: bool = False
    content_schedule_hour: int = Field(default=7, ge=0, le=23)
    content_schedule_minute: int = Field(default=30, ge=0, le=59)
    content_catchup_hours: int = Field(default=12, ge=1, le=24)
    content_poll_seconds: float = Field(default=2.0, ge=0.1, le=300)
    content_worker_concurrency: int = Field(default=1, ge=1, le=8)
    content_lease_seconds: int = Field(default=120, ge=30, le=3600)
    content_heartbeat_seconds: int = Field(default=30, ge=5, le=600)
    content_max_attempts: int = Field(default=3, ge=1, le=10)
    content_freshness_window_days: int = Field(default=10, ge=1, le=365)
    content_scoring_version: str = "scoring-v1-preview.11-qualified-authoritative-priority"
    content_scoring_profile: str = "preview"
    content_selection_priority_rule_version: str | None = (
        "qualified-authoritative-priority-v1"
    )
    content_llm_rerank_enabled: bool = True
    content_llm_rerank_policy_version: str = Field(
        default=DEFAULT_TOPIC_RERANK_POLICY_VERSION, min_length=1, max_length=80
    )
    content_llm_rerank_candidate_limit: int = Field(default=8, ge=1, le=8)
    content_llm_rerank_max_output_tokens: int = Field(default=1_024, ge=128, le=4_096)
    content_slot_mode_enabled: bool = False
    content_morning_enabled: bool = False
    content_noon_enabled: bool = False
    content_evening_enabled: bool = False
    content_morning_target_hour: int = Field(default=7, ge=0, le=23)
    content_morning_target_minute: int = Field(default=30, ge=0, le=59)
    content_noon_target_hour: int = Field(default=12, ge=0, le=23)
    content_noon_target_minute: int = Field(default=30, ge=0, le=59)
    content_evening_target_hour: int = Field(default=18, ge=0, le=23)
    content_evening_target_minute: int = Field(default=30, ge=0, le=59)
    content_slot_prepare_lead_minutes: int = Field(default=90, ge=30, le=180)
    content_slot_delivery_late_minutes: int = Field(default=60, ge=0, le=120)
    content_slot_max_items: int = Field(default=3, ge=1, le=3)
    content_slot_ranking_version: Literal["slot-ranking-v1"] = DEFAULT_SLOT_RANKING_VERSION

    wecom_enabled: bool = False
    wecom_api_base_url: str = "https://qyapi.weixin.qq.com"
    wecom_delivery_provider: Literal["self_built_app", "group_webhook"] = "self_built_app"
    wecom_corp_id: str = ""
    wecom_agent_id: int | None = Field(default=None, ge=1)
    wecom_corp_secret: SecretStr | None = None
    wecom_group_webhook_key: SecretStr | None = None
    wecom_default_recipient_id: str = ""
    wecom_default_recipient_name: str = "销售"
    wecom_auto_delivery_enabled: bool = False
    wecom_require_review_before_send: bool = True
    wecom_poll_seconds: float = Field(default=2.0, gt=0, le=300)
    wecom_worker_concurrency: int = Field(default=1, ge=1, le=8)
    wecom_lease_seconds: int = Field(default=120, ge=30, le=3600)
    wecom_heartbeat_seconds: int = Field(default=30, ge=5, le=600)
    wecom_max_attempts: int = Field(default=3, ge=1, le=10)
    wecom_request_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    wecom_max_image_bytes: int = Field(default=10 * 1024 * 1024, ge=6, le=10 * 1024 * 1024)
    wecom_max_text_bytes: int = Field(default=2048, ge=1, le=2048)
    wecom_group_max_image_bytes: int = Field(default=2 * 1024 * 1024, ge=6, le=2 * 1024 * 1024)
    wecom_group_max_text_bytes: int = Field(default=4096, ge=1, le=4096)
    wecom_slot_package_gap_seconds: int = Field(default=60, ge=1, le=600)

    brand_upload_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=64 * 1024,
        le=25 * 1024 * 1024,
    )
    brand_parse_max_pages: int = Field(default=120, ge=1, le=500)
    brand_parse_max_characters: int = Field(default=300_000, ge=1_000, le=1_000_000)
    brand_parse_max_chunks: int = Field(default=600, ge=1, le=2_000)
    brand_chunk_characters: int = Field(default=900, ge=300, le=3_000)
    brand_chunk_overlap_characters: int = Field(default=120, ge=0, le=500)
    brand_parser_version: str = STRUCTURED_BRAND_DERIVATION_VERSIONS[0]
    brand_chunk_version: str = STRUCTURED_BRAND_DERIVATION_VERSIONS[1]
    brand_embedding_input_version: str = STRUCTURED_BRAND_DERIVATION_VERSIONS[2]
    brand_retrieval_version: str = STRUCTURED_BRAND_RETRIEVAL_VERSION
    brand_ocr_model: str = Field(default="glm-ocr", min_length=1, max_length=120)
    brand_ocr_sparse_text_threshold: int = Field(default=40, ge=1, le=10_000)
    brand_ocr_max_request_bytes: int = Field(
        default=40 * 1024 * 1024, ge=64 * 1024, le=64 * 1024 * 1024
    )
    brand_ocr_max_response_bytes: int = Field(
        default=10 * 1024 * 1024, ge=64 * 1024, le=50 * 1024 * 1024
    )
    brand_ocr_timeout_seconds: float = Field(default=180.0, gt=0, le=360)
    brand_ocr_max_pages: int = Field(default=100, ge=1, le=100)
    copy_pipeline_version: str = ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION
    copy_generator_prompt_version: str = "moments-generator-v19-exact-claim-span"
    copy_draft_schema_version: str = "moments-draft-schema-v1"
    copy_auditor_prompt_version: str = "moments-auditor-v18-xiaosai-insight"
    copy_audit_schema_version: str = "moments-audit-schema-v1"
    copy_rule_version: str = "moments-rules-v11-compact-warning-recovery"
    copy_preview_policy_version: str = "preview-v11-compact-content-warning-recovery"
    copy_brand_context_limit: int = Field(default=6, ge=1, le=20)
    copy_max_output_tokens: int = Field(default=2_048, ge=512, le=8_192)
    copy_audit_max_output_tokens: int = Field(default=1_024, ge=256, le=4_096)

    official_account_local_enabled: bool = False
    official_account_editor_handoff_enabled: bool = False
    official_account_local_worker_enabled: bool = False
    official_account_local_poll_seconds: float = Field(default=2.0, ge=0.1, le=300)
    official_account_local_worker_concurrency: int = Field(default=1, ge=1, le=4)
    official_account_local_lease_seconds: int = Field(default=300, ge=60, le=3_600)
    official_account_local_heartbeat_seconds: int = Field(default=60, ge=5, le=600)
    official_account_local_max_attempts: int = Field(default=3, ge=1, le=6)
    official_account_local_retry_base_seconds: int = Field(default=10, ge=1, le=600)
    official_account_local_generator_prompt_version: str = (
        OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION
    )
    official_account_local_article_schema_version: str = OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION
    official_account_local_media_plan_version: str = OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION
    official_account_local_auditor_prompt_version: str = OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION
    official_account_local_audit_schema_version: str = OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION
    official_account_local_rule_version: str = OFFICIAL_ACCOUNT_RULE_VERSION
    official_account_local_renderer_version: str = OFFICIAL_ACCOUNT_RENDERER_V8_VERSION
    official_account_local_style_version: str = OFFICIAL_ACCOUNT_STYLE_V8_VERSION
    official_account_local_template_version: str = OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION
    official_account_local_adapter_version: str = OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION
    official_account_local_visual_query_version: str = OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION
    official_account_local_visual_selector_version: str = OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION
    official_account_local_context_media_plan_version: str = (
        OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION
    )
    official_account_local_visual_semantic_enabled: bool = False
    official_account_local_generated_visuals_enabled: bool = False
    official_account_local_generated_visual_plan_version: str = (
        OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION
    )
    official_account_local_generated_visual_prompt_version: str = (
        OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION
    )
    official_account_local_default_author: str = Field(
        default="赛先生", min_length=1, max_length=80
    )
    official_account_local_min_characters: int = Field(default=1_200, ge=1_000, le=4_000)
    official_account_local_target_min_characters: int = Field(
        default=1_800,
        ge=1_000,
        le=4_000,
    )
    official_account_local_target_max_characters: int = Field(
        default=2_600,
        ge=1_000,
        le=4_000,
    )
    official_account_local_max_characters: int = Field(default=4_000, ge=1_200, le=4_000)
    official_account_local_max_output_tokens: int = Field(default=16_384, ge=2_048, le=16_384)
    official_account_local_audit_max_output_tokens: int = Field(
        default=2_048,
        ge=512,
        le=4_096,
    )

    ip_asset_hub_enabled: bool = False
    ip_asset_worker_enabled: bool = False
    ip_asset_generation_enabled: bool = False
    ip_asset_recognition_enabled: bool = False
    ip_asset_recognition_model: str = Field(
        default="glm-4.1v-thinking-flash",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$",
    )
    ip_asset_recognition_timeout_seconds: float = Field(default=90.0, gt=0, le=180)
    ip_asset_recognition_concurrency: int = Field(default=1, ge=1, le=4)
    ip_asset_recognition_max_request_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=1024 * 1024,
        le=32 * 1024 * 1024,
    )
    ip_asset_recognition_max_response_bytes: int = Field(
        default=1024 * 1024,
        ge=16 * 1024,
        le=4 * 1024 * 1024,
    )
    ip_asset_poll_seconds: float = Field(default=2.0, ge=0.1, le=300)
    ip_asset_worker_concurrency: int = Field(default=1, ge=1, le=4)
    ip_asset_lease_seconds: int = Field(default=300, ge=60, le=3_600)
    ip_asset_heartbeat_seconds: int = Field(default=60, ge=5, le=600)
    ip_asset_max_attempts: int = Field(default=3, ge=1, le=6)
    ip_asset_upload_concurrency: int = Field(default=2, ge=1, le=8)

    image_enabled: bool = False
    image_provider_mode: Literal["disabled", "fake", "toapis", "comfly"] = "disabled"
    toapis_base_url: str = "https://toapis.com"
    toapis_api_key: SecretStr | None = None
    comfly_base_url: str = "https://ai.comfly.org"
    comfly_api_key: SecretStr | None = None
    image_model: str = "gpt-image-2"
    image_prompt_version: str = "image-prompt-v1"
    image_pipeline_version: str = "image-pipeline-v1"
    image_max_attempts: int = Field(default=3, ge=1, le=6)
    image_poll_initial_seconds: float = Field(default=5.0, ge=0.1, le=30)
    image_poll_interval_seconds: float = Field(default=7.0, ge=0.1, le=30)
    image_provider_timeout_seconds: float = Field(default=300.0, gt=0, le=300)
    image_provider_window_seconds: float = Field(default=300.0, gt=1, le=300)
    image_max_download_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    image_max_request_bytes: int = Field(
        default=16 * 1024 * 1024, ge=64 * 1024, le=50 * 1024 * 1024
    )
    image_max_provider_response_bytes: int = Field(
        default=32 * 1024 * 1024, ge=16 * 1024, le=50 * 1024 * 1024
    )
    image_max_reference_images: int = Field(default=3, ge=1, le=4)
    image_reference_budget_bytes: int = Field(
        default=IMAGE_REFERENCE_BUDGET_BYTES, ge=256 * 1024, le=20 * 1024 * 1024
    )
    image_asset_manifest: str = "private/brand-materials/visual-assets.manifest.json"
    image_selector_version: str = "brand-visual-selector-v1"
    image_selector_enabled: bool = True
    image_reference_asset: str = "private/brand-materials/05-visual-assets/赛先生-显微镜.png"
    image_ocr_enabled: bool = False
    image_ocr_model: str = Field(default="glm-ocr", min_length=1, max_length=120)
    image_ocr_max_input_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=10 * 1024 * 1024)
    image_ocr_max_response_bytes: int = Field(default=1024 * 1024, ge=1, le=1024 * 1024)
    image_ocr_timeout_seconds: float = Field(default=120.0, gt=0, le=360)
    image_quality_audit_enabled: bool = False
    image_diversity_enabled: bool = False
    image_diversity_policy_version: str = VISUAL_DIVERSITY_POLICY_VERSION
    image_visual_brief_version: str = VISUAL_BRIEF_V2_VERSION
    image_diversity_selector_version: str = VISUAL_SELECTOR_V2_VERSION
    image_diversity_prompt_version: str = VISUAL_PROMPT_V3_VERSION
    image_diversity_pipeline_version: str = VISUAL_PIPELINE_V3_VERSION
    image_perceptual_hash_version: str = IMAGE_PERCEPTUAL_HASH_VERSION
    image_similarity_policy_version: str = IMAGE_SIMILARITY_POLICY_VERSION
    image_diversity_history_days: int = Field(default=7, ge=1, le=30)
    image_diversity_history_limit: int = Field(default=400, ge=1, le=1_000)
    image_similarity_threshold: int = Field(default=DEFAULT_IMAGE_SIMILARITY_THRESHOLD, ge=0, le=64)
    image_diversity_max_regenerations: Literal[1] = 1

    visual_semantic_enabled: bool = False
    visual_embedding_provider_mode: Literal["disabled", "fake", "alibaba"] = "disabled"
    visual_embedding_endpoint: SecretStr | None = None
    visual_embedding_api_key: SecretStr | None = None
    visual_embedding_model: Literal["qwen3-vl-embedding"] = "qwen3-vl-embedding"
    visual_embedding_dimensions: Literal[2048] = 2048
    visual_embedding_input_policy_version: Literal["brand-visual-embedding-input-v2"] = (
        "brand-visual-embedding-input-v2"
    )
    visual_embedding_timeout_seconds: float = Field(default=60.0, gt=0, le=180)
    visual_embedding_concurrency: int = Field(default=1, ge=1, le=4)
    visual_index_lease_seconds: int = Field(default=300, ge=30, le=3_600)

    # Brand text RAG intentionally has an identity separate from the governance/article
    # embedding provider. ``auto`` preserves deterministic fake tests while selecting the
    # configured Alibaba multimodal vector space in development/runtime deployments.
    brand_embedding_provider_mode: Literal["auto", "disabled", "fake", "alibaba"] = "auto"

    ai_provider_mode: Literal["disabled", "fake", "zhipu"] = "disabled"
    ai_platform_base_url: str | None = None
    ai_platform_api_key: SecretStr | None = None
    ai_chat_model: str = "glm-5.2"
    ai_embedding_model: str = "embedding-3"
    ai_embedding_dimensions: int = 2048
    ai_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    ai_read_timeout_seconds: float = Field(default=120.0, gt=0, le=300)
    ai_total_timeout_seconds: float = Field(default=150.0, gt=0, le=360)
    ai_provider_concurrency: int = Field(default=2, ge=1, le=16)
    ai_max_attempts: int = Field(default=3, ge=1, le=6)
    ai_max_validation_corrections: int = Field(default=1, ge=0, le=1)
    ai_max_input_characters: int = Field(default=40_000, ge=1_000, le=200_000)
    ai_max_output_tokens: int = Field(default=4_096, ge=256, le=32_768)
    ai_max_tokens_per_run: int = Field(default=200_000, ge=4_096, le=10_000_000)
    ai_max_tokens_per_day: int = Field(default=1_000_000, ge=4_096, le=100_000_000)
    ai_max_cost_units_per_run: int = Field(default=100_000, ge=0, le=100_000_000)
    ai_max_cost_units_per_day: int = Field(default=500_000, ge=0, le=1_000_000_000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    @field_validator("image_diversity_max_regenerations", mode="before")
    @classmethod
    def parse_fixed_diversity_regeneration_count(cls, value: object) -> object:
        return 1 if value == "1" else value

    @field_validator("visual_embedding_dimensions", mode="before")
    @classmethod
    def parse_fixed_visual_embedding_dimensions(cls, value: object) -> object:
        return 2048 if value == "2048" else value

    @field_validator("app_browser_origins")
    @classmethod
    def validate_app_browser_origins(cls, value: str) -> str:
        origins: list[str] = []
        for raw in value.split(","):
            candidate = raw.strip().rstrip("/")
            parsed = urlsplit(candidate)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or candidate == "*"
            ):
                raise ValueError("APP_BROWSER_ORIGINS must contain exact HTTP(S) origins")
            if candidate not in origins:
                origins.append(candidate)
        if not origins:
            raise ValueError("APP_BROWSER_ORIGINS must not be empty")
        return ",".join(origins)

    @property
    def browser_origins(self) -> tuple[str, ...]:
        return tuple(self.app_browser_origins.split(","))

    @property
    def visual_embedding_identity(self) -> VisualEmbeddingIdentity:
        return VisualEmbeddingIdentity(
            model=self.visual_embedding_model,
            dimensions=self.visual_embedding_dimensions,
            input_policy_version=self.visual_embedding_input_policy_version,
        )

    @property
    def resolved_brand_embedding_provider_mode(self) -> Literal["disabled", "fake", "alibaba"]:
        if self.brand_embedding_provider_mode != "auto":
            return self.brand_embedding_provider_mode
        if self.ai_provider_mode == "fake":
            return "fake"
        if self.visual_embedding_provider_mode == "alibaba":
            return "alibaba"
        return "disabled"

    @property
    def brand_embedding_provider(self) -> str:
        mode = self.resolved_brand_embedding_provider_mode
        if mode == "alibaba":
            return self.visual_embedding_identity.provider
        return mode

    @property
    def brand_embedding_model(self) -> str:
        if self.resolved_brand_embedding_provider_mode == "alibaba":
            return self.visual_embedding_identity.model
        return self.ai_embedding_model

    @property
    def brand_embedding_dimensions(self) -> int:
        if self.resolved_brand_embedding_provider_mode == "alibaba":
            return self.visual_embedding_identity.dimensions
        return self.ai_embedding_dimensions

    @field_validator("content_llm_rerank_policy_version")
    @classmethod
    def validate_content_llm_rerank_policy_version(cls, value: str) -> str:
        if value not in SUPPORTED_TOPIC_RERANK_POLICY_VERSIONS:
            raise ValueError("unsupported content LLM rerank policy version")
        return value

    def content_slot_schedules(self) -> tuple[ContentSlotSchedule, ...]:
        def schedule(
            slot: ContentSlot,
            *,
            enabled: bool,
            target_hour: int,
            target_minute: int,
        ) -> ContentSlotSchedule:
            return ContentSlotSchedule(
                slot=slot,
                enabled=enabled,
                target_hour=target_hour,
                target_minute=target_minute,
                prepare_lead_minutes=self.content_slot_prepare_lead_minutes,
                delivery_late_minutes=self.content_slot_delivery_late_minutes,
                max_items=self.content_slot_max_items,
            )

        return (
            schedule(
                ContentSlot.MORNING,
                enabled=self.content_morning_enabled,
                target_hour=self.content_morning_target_hour,
                target_minute=self.content_morning_target_minute,
            ),
            schedule(
                ContentSlot.NOON,
                enabled=self.content_noon_enabled,
                target_hour=self.content_noon_target_hour,
                target_minute=self.content_noon_target_minute,
            ),
            schedule(
                ContentSlot.EVENING,
                enabled=self.content_evening_enabled,
                target_hour=self.content_evening_target_hour,
                target_minute=self.content_evening_target_minute,
            ),
        )

    @model_validator(mode="after")
    def validate_runtime_invariants(self) -> "Settings":
        if self.acquisition_heartbeat_seconds >= self.acquisition_lease_seconds:
            raise ValueError("acquisition heartbeat must be shorter than the lease")
        if self.governance_heartbeat_seconds >= self.governance_lease_seconds:
            raise ValueError("governance heartbeat must be shorter than the lease")
        if self.content_heartbeat_seconds >= self.content_lease_seconds:
            raise ValueError("content heartbeat must be shorter than the lease")
        if self.wecom_heartbeat_seconds >= self.wecom_lease_seconds:
            raise ValueError("WeCom heartbeat must be shorter than the lease")
        if (
            self.official_account_local_heartbeat_seconds
            >= self.official_account_local_lease_seconds
        ):
            raise ValueError("official-account heartbeat must be shorter than the lease")
        if self.brand_chunk_overlap_characters >= self.brand_chunk_characters:
            raise ValueError("brand chunk overlap must be shorter than the chunk")
        if (
            self.governance_scheduler_enabled or self.governance_worker_enabled
        ) and not self.governance_enabled:
            raise ValueError("governance processes require governance to be enabled")
        if (
            self.content_scheduler_enabled or self.content_worker_enabled
        ) and not self.content_enabled:
            raise ValueError("content processes require content to be enabled")
        if self.content_slot_mode_enabled and not self.content_enabled:
            raise ValueError("content slot mode requires content to be enabled")
        if self.official_account_local_worker_enabled and not self.official_account_local_enabled:
            raise ValueError("official-account worker requires the local feature to be enabled")
        if self.ip_asset_worker_enabled and not self.ip_asset_hub_enabled:
            raise ValueError("IP asset worker requires the hub to be enabled")
        if self.ip_asset_heartbeat_seconds >= self.ip_asset_lease_seconds:
            raise ValueError("IP asset heartbeat must be shorter than the lease")
        if self.ip_asset_generation_enabled and (
            not self.ip_asset_hub_enabled
            or not self.image_enabled
            or self.image_provider_mode == "disabled"
        ):
            raise ValueError("IP asset generation requires an enabled hub and image provider")
        if self.ip_asset_recognition_enabled:
            recognition_key = (
                self.ai_platform_api_key.get_secret_value().strip()
                if self.ai_platform_api_key is not None
                else ""
            )
            if (
                not self.ip_asset_hub_enabled
                or self.ai_provider_mode != "zhipu"
                or not recognition_key
            ):
                raise ValueError(
                    "IP asset recognition requires an enabled hub and configured Zhipu provider"
                )
        if not (
            self.official_account_local_min_characters
            <= self.official_account_local_target_min_characters
            <= self.official_account_local_target_max_characters
            <= self.official_account_local_max_characters
        ):
            raise ValueError("official-account article length policy is inconsistent")
        official_account_versions = (
            self.official_account_local_generator_prompt_version,
            self.official_account_local_article_schema_version,
            self.official_account_local_media_plan_version,
            self.official_account_local_auditor_prompt_version,
            self.official_account_local_audit_schema_version,
            self.official_account_local_rule_version,
            self.official_account_local_renderer_version,
            self.official_account_local_style_version,
            self.official_account_local_template_version,
            self.official_account_local_adapter_version,
            self.official_account_local_visual_query_version,
            self.official_account_local_visual_selector_version,
            self.official_account_local_context_media_plan_version,
        )
        if self.official_account_local_enabled and official_account_versions != (
            OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
            OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
            OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
            OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
            OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
            OFFICIAL_ACCOUNT_RULE_VERSION,
            OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
            OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
            OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
            OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
            OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
        ):
            raise ValueError("official-account current version bundle is unsupported")
        if (
            self.official_account_local_visual_semantic_enabled
            and self.visual_embedding_provider_mode == "disabled"
        ):
            raise ValueError("official-account visual semantic matching requires a visual provider")
        if self.official_account_local_generated_visuals_enabled:
            if (
                not self.official_account_local_enabled
                or not self.official_account_local_worker_enabled
                or not self.image_enabled
                or self.image_provider_mode == "disabled"
            ):
                raise ValueError(
                    "generated official-account visuals require enabled local worker and image "
                    "provider"
                )
            if self.image_max_attempts != 1:
                raise ValueError(
                    "generated official-account visuals require exactly one provider attempt"
                )
            if (
                self.official_account_local_generated_visual_plan_version
                != OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION
                or self.official_account_local_generated_visual_prompt_version
                != OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION
            ):
                raise ValueError("official-account generated visual version bundle is unsupported")
        if (
            self.content_enabled
            and self.content_llm_rerank_enabled
            and self.ai_provider_mode not in {"fake", "zhipu"}
        ):
            raise ValueError("content LLM rerank requires fake or zhipu AI provider mode")
        if self.acquisition_total_timeout_seconds < self.acquisition_read_timeout_seconds:
            raise ValueError("acquisition total timeout must cover the read timeout")
        if (
            "EduAILeadAgent/" not in self.acquisition_user_agent
            or "+" not in self.acquisition_user_agent
        ):
            raise ValueError("acquisition user agent must identify the service and contact URL")
        if self.acquisition_first_run_scan_limit < self.acquisition_first_run_item_limit:
            raise ValueError("first-run scan limit must cover the accepted item limit")
        if self.acquisition_daily_scan_limit < self.acquisition_daily_item_limit:
            raise ValueError("daily scan limit must cover the accepted item limit")
        if self.content_freshness_window_days < 1:
            raise ValueError("content freshness window must be positive")
        parsed_wecom_base_url = urlsplit(self.wecom_api_base_url.strip())
        if (
            parsed_wecom_base_url.scheme != "https"
            or parsed_wecom_base_url.hostname != "qyapi.weixin.qq.com"
            or parsed_wecom_base_url.port not in {None, 443}
            or parsed_wecom_base_url.path not in {"", "/"}
            or parsed_wecom_base_url.username is not None
            or parsed_wecom_base_url.password is not None
            or parsed_wecom_base_url.query
            or parsed_wecom_base_url.fragment
        ):
            raise ValueError("WeCom API base URL must be exactly https://qyapi.weixin.qq.com")
        if self.wecom_enabled:
            if self.wecom_delivery_provider == "self_built_app":
                if any(
                    not value.strip() or any(character.isspace() for character in value)
                    for value in (self.wecom_corp_id, self.wecom_default_recipient_id)
                ):
                    raise ValueError(
                        "self-built WeCom delivery requires CorpID and default recipient"
                    )
                if (
                    self.wecom_agent_id is None
                    or self.wecom_corp_secret is None
                    or not self.wecom_corp_secret.get_secret_value().strip()
                ):
                    raise ValueError(
                        "enabled self-built WeCom delivery requires AgentID and CorpSecret"
                    )
            else:
                group_key = (
                    self.wecom_group_webhook_key.get_secret_value()
                    if self.wecom_group_webhook_key is not None
                    else ""
                )
                if not group_key.strip() or any(
                    character.isspace() or ord(character) < 32 for character in group_key
                ):
                    raise ValueError("enabled group-webhook delivery requires a valid webhook key")
        if self.wecom_auto_delivery_enabled and not self.wecom_enabled:
            raise ValueError("automatic WeCom delivery requires WeCom to be enabled")
        if not self.wecom_default_recipient_name.strip():
            raise ValueError("WeCom default recipient name must be non-blank")
        if self.ai_total_timeout_seconds < self.ai_read_timeout_seconds:
            raise ValueError("AI total timeout must cover the read timeout")
        if self.ai_max_tokens_per_run < self.ai_max_output_tokens:
            raise ValueError("AI run token budget must cover one maximum output")
        if self.ai_max_tokens_per_day < self.ai_max_tokens_per_run:
            raise ValueError("AI daily token budget must cover one run budget")
        if self.ai_max_cost_units_per_day < self.ai_max_cost_units_per_run:
            raise ValueError("AI daily cost budget must cover one run budget")
        if self.ai_embedding_dimensions != 2048:
            raise ValueError("embedding-3 persistence contract requires exactly 2048 dimensions")
        checkpoint_url = self.governance_checkpoint_database_url.get_secret_value()
        parsed_checkpoint_url = urlsplit(checkpoint_url)
        if (
            parsed_checkpoint_url.scheme not in {"postgresql", "postgres"}
            or not parsed_checkpoint_url.hostname
            or not parsed_checkpoint_url.path.strip("/")
            or parsed_checkpoint_url.fragment
        ):
            raise ValueError(
                "governance checkpoint URL must be a psycopg postgresql:// connection URL"
            )
        if self.ai_provider_mode == "zhipu":
            base_url = (self.ai_platform_base_url or "").strip()
            api_key = (
                self.ai_platform_api_key.get_secret_value().strip()
                if self.ai_platform_api_key is not None
                else ""
            )
            if not base_url:
                raise ValueError("Zhipu mode requires a non-blank AI platform base URL")
            if (self.governance_worker_enabled or self.content_worker_enabled) and not api_key:
                raise ValueError("Zhipu model workers require a non-blank API key")
            parsed_base_url = urlsplit(base_url)
            if (
                parsed_base_url.scheme != "https"
                or not parsed_base_url.hostname
                or parsed_base_url.username is not None
                or parsed_base_url.password is not None
                or parsed_base_url.query
                or parsed_base_url.fragment
            ):
                raise ValueError("Zhipu base URL must be an HTTPS origin/path without credentials")
        if self.image_enabled and self.image_provider_mode == "disabled":
            raise ValueError("image provider must be enabled when image generation is enabled")
        if self.visual_semantic_enabled and self.visual_embedding_provider_mode == "disabled":
            raise ValueError("visual semantic retrieval requires an embedding provider")
        if self.visual_semantic_enabled and not self.image_selector_enabled:
            raise ValueError("visual semantic retrieval requires approved asset selection")
        if self.visual_index_lease_seconds <= self.visual_embedding_timeout_seconds:
            raise ValueError("visual index lease must outlast the embedding timeout")
        if (
            self.visual_embedding_provider_mode == "alibaba"
            or self.resolved_brand_embedding_provider_mode == "alibaba"
        ):
            endpoint = (
                self.visual_embedding_endpoint.get_secret_value().strip()
                if self.visual_embedding_endpoint is not None
                else ""
            )
            api_key = (
                self.visual_embedding_api_key.get_secret_value().strip()
                if self.visual_embedding_api_key is not None
                else ""
            )
            if not endpoint or not api_key:
                raise ValueError("Alibaba visual embedding requires endpoint and API key secrets")
            parsed_endpoint = urlsplit(endpoint)
            if (
                parsed_endpoint.scheme != "https"
                or not parsed_endpoint.hostname
                or not parsed_endpoint.hostname.endswith(".cn-beijing.maas.aliyuncs.com")
                or parsed_endpoint.path
                != "/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
                or parsed_endpoint.port not in {None, 443}
                or parsed_endpoint.username is not None
                or parsed_endpoint.password is not None
                or parsed_endpoint.query
                or parsed_endpoint.fragment
            ):
                raise ValueError("Alibaba visual embedding endpoint must be the Beijing REST URL")
        if self.brand_embedding_provider_mode == "fake" and self.ai_provider_mode != "fake":
            raise ValueError("fake brand embedding requires fake AI provider mode")
        if self.image_diversity_enabled:
            if not self.image_enabled:
                raise ValueError("image diversity requires image generation to be enabled")
            if self.image_ocr_enabled and self.image_ocr_model != "glm-ocr":
                raise ValueError("image diversity requires the reviewed glm-ocr image OCR model")
            if not self.image_selector_enabled:
                raise ValueError("image diversity requires approved visual asset selection")
            reviewed_versions = {
                "image_diversity_policy_version": (
                    self.image_diversity_policy_version,
                    VISUAL_DIVERSITY_POLICY_VERSION,
                ),
                "image_visual_brief_version": (
                    self.image_visual_brief_version,
                    VISUAL_BRIEF_V2_VERSION,
                ),
                "image_diversity_selector_version": (
                    self.image_diversity_selector_version,
                    VISUAL_SELECTOR_V2_VERSION,
                ),
                "image_diversity_prompt_version": (
                    self.image_diversity_prompt_version,
                    VISUAL_PROMPT_V3_VERSION,
                ),
                "image_diversity_pipeline_version": (
                    self.image_diversity_pipeline_version,
                    VISUAL_PIPELINE_V3_VERSION,
                ),
                "image_perceptual_hash_version": (
                    self.image_perceptual_hash_version,
                    IMAGE_PERCEPTUAL_HASH_VERSION,
                ),
                "image_similarity_policy_version": (
                    self.image_similarity_policy_version,
                    IMAGE_SIMILARITY_POLICY_VERSION,
                ),
            }
            mismatched = [
                name for name, (actual, expected) in reviewed_versions.items() if actual != expected
            ]
            if mismatched:
                raise ValueError(
                    "image diversity versions must match the reviewed bundle: "
                    + ", ".join(mismatched)
                )
        if self.image_provider_mode == "toapis":
            key = self.toapis_api_key.get_secret_value().strip() if self.toapis_api_key else ""
            if not key:
                raise ValueError("ToAPIs image mode requires TOAPIS_API_KEY")
            parsed_toapis = urlsplit(self.toapis_base_url)
            if (
                parsed_toapis.scheme != "https"
                or parsed_toapis.hostname != "toapis.com"
                or parsed_toapis.port not in {None, 443}
                or parsed_toapis.path not in {"", "/"}
                or parsed_toapis.username is not None
                or parsed_toapis.password is not None
                or parsed_toapis.query
                or parsed_toapis.fragment
            ):
                raise ValueError("ToAPIs base URL must be exactly https://toapis.com")
        if self.image_provider_mode == "comfly":
            key = self.comfly_api_key.get_secret_value().strip() if self.comfly_api_key else ""
            if not key:
                raise ValueError("Comfly image mode requires COMFLY_API_KEY")
            base_url = self.comfly_base_url.strip()
            parsed_comfly = urlsplit(base_url)
            try:
                port = parsed_comfly.port
            except ValueError as exc:
                raise ValueError("Comfly base URL must be a valid HTTPS origin") from exc
            if (
                parsed_comfly.scheme != "https"
                or not parsed_comfly.hostname
                or port not in {None, 443}
                or parsed_comfly.path not in {"", "/"}
                or parsed_comfly.username is not None
                or parsed_comfly.password is not None
                or parsed_comfly.query
                or parsed_comfly.fragment
                or any(character.isspace() for character in base_url)
            ):
                raise ValueError("Comfly base URL must be an HTTPS origin without credentials")
        if not self.image_model.strip() or any(ch.isspace() for ch in self.image_model):
            raise ValueError("image model identifier must be non-blank and contain no whitespace")
        if not self.brand_ocr_model.strip() or any(
            character.isspace() for character in self.brand_ocr_model
        ):
            raise ValueError(
                "brand OCR model identifier must be non-blank and contain no whitespace"
            )
        if not self.image_ocr_model.strip() or any(
            character.isspace() for character in self.image_ocr_model
        ):
            raise ValueError(
                "image OCR model identifier must be non-blank and contain no whitespace"
            )
        if not self.ai_chat_model.strip() or not self.ai_embedding_model.strip():
            raise ValueError("AI model identifiers must be non-blank")
        brand_derivation_versions = (
            self.brand_parser_version,
            self.brand_chunk_version,
            self.brand_embedding_input_version,
        )
        if brand_derivation_versions not in SUPPORTED_BRAND_DERIVATION_VERSIONS:
            raise ValueError("brand parser/chunk/input versions must use a supported frozen bundle")
        if self.brand_retrieval_version not in SUPPORTED_BRAND_RETRIEVAL_VERSIONS:
            raise ValueError("brand retrieval version is unsupported")
        version_values = {
            self.governance_pipeline_version,
            self.governance_normalization_version,
            self.governance_passage_schema_version,
            self.governance_taxonomy_version,
            self.governance_prompt_version,
            self.governance_analysis_schema_version,
            self.governance_embedding_input_version,
            self.governance_similarity_rule_version,
            self.governance_event_assignment_version,
            self.content_scoring_version,
            self.content_scoring_profile,
            self.content_selection_priority_rule_version,
            self.content_slot_ranking_version,
            self.acquisition_version,
            self.brand_parser_version,
            self.brand_chunk_version,
            self.brand_embedding_input_version,
            self.brand_retrieval_version,
            self.copy_pipeline_version,
            self.copy_generator_prompt_version,
            self.copy_draft_schema_version,
            self.copy_auditor_prompt_version,
            self.copy_audit_schema_version,
            self.copy_rule_version,
            self.copy_preview_policy_version,
            self.official_account_local_generator_prompt_version,
            self.official_account_local_article_schema_version,
            self.official_account_local_media_plan_version,
            self.official_account_local_auditor_prompt_version,
            self.official_account_local_audit_schema_version,
            self.official_account_local_rule_version,
            self.official_account_local_renderer_version,
            self.official_account_local_style_version,
            self.official_account_local_template_version,
            self.official_account_local_adapter_version,
            self.official_account_local_visual_query_version,
            self.official_account_local_visual_selector_version,
            self.official_account_local_context_media_plan_version,
            self.official_account_local_generated_visual_plan_version,
            self.official_account_local_generated_visual_prompt_version,
            self.image_prompt_version,
            self.image_pipeline_version,
            self.image_diversity_policy_version,
            self.image_visual_brief_version,
            self.image_diversity_selector_version,
            self.image_diversity_prompt_version,
            self.image_diversity_pipeline_version,
            self.image_perceptual_hash_version,
            self.image_similarity_policy_version,
            self.visual_embedding_input_policy_version,
        }
        version_values.discard(None)
        bounded_version_values = {value for value in version_values if value is not None}
        if any(not value.strip() or len(value) > 80 for value in bounded_version_values):
            raise ValueError(
                "governance version identifiers must be non-empty and at most 80 chars"
            )
        if self.app_env == "production":
            placeholders = {
                "edu_ai_minio",
                "edu_ai_minio_local_change_me",
                "edu_ai_local_change_me",
            }
            database_url = self.database_url.get_secret_value()
            checkpoint_url = self.governance_checkpoint_database_url.get_secret_value()
            if (
                self.minio_access_key.get_secret_value() in placeholders
                or self.minio_secret_key.get_secret_value() in placeholders
                or any(value in database_url for value in placeholders)
                or (
                    self.governance_enabled
                    and any(value in checkpoint_url for value in placeholders)
                )
            ):
                raise ValueError("production credentials must not use development placeholders")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
