from app.core.config import Settings
from app.domain.governance_entities import GovernanceVersionBundle


def build_governance_version_bundle(settings: Settings) -> GovernanceVersionBundle:
    provider = settings.ai_provider_mode
    return GovernanceVersionBundle(
        pipeline_version=settings.governance_pipeline_version,
        normalization_version=settings.governance_normalization_version,
        passage_schema_version=settings.governance_passage_schema_version,
        taxonomy_version=settings.governance_taxonomy_version,
        prompt_version=settings.governance_prompt_version,
        analysis_schema_version=settings.governance_analysis_schema_version,
        chat_provider=provider,
        chat_model=settings.ai_chat_model,
        embedding_provider=provider,
        embedding_model=settings.ai_embedding_model,
        embedding_dimensions=settings.ai_embedding_dimensions,
        embedding_input_version=settings.governance_embedding_input_version,
        similarity_rule_version=settings.governance_similarity_rule_version,
        event_assignment_version=settings.governance_event_assignment_version,
    )
