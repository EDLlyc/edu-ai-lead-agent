import type { components } from "@/lib/api/generated/schema";
import { apiClient, resolveApiResourceUrl } from "@/lib/api/client";

type CapabilitiesResponse =
  components["schemas"]["OfficialAccountCapabilitiesResponse"];
type RunSummaryResponse =
  components["schemas"]["OfficialAccountRunSummaryResponse"];
type RunDetailResponse =
  components["schemas"]["OfficialAccountRunDetailResponse"];
type RunCreateRequest =
  components["schemas"]["OfficialAccountRunCreateRequest"];
type ManualReviewRequest =
  components["schemas"]["OfficialAccountManualReviewRequest"];
type ManualReviewResponse =
  components["schemas"]["OfficialAccountManualReviewResponse"];
type MediaResponse = components["schemas"]["OfficialAccountMediaResponse"];
type EditorHandoffResponse =
  components["schemas"]["OfficialAccountEditorHandoffResponse"];

export type OfficialAccountStatus = RunSummaryResponse["status"];
export type OfficialAccountStage = RunSummaryResponse["current_stage"];
export type OfficialAccountManualReviewDecision =
  ManualReviewRequest["decision"];

export type OfficialAccountManualReviewViewModel = Readonly<{
  status: ManualReviewResponse["status"];
  statusLabel: string;
  reviewId: string | null;
  reviewerLabel: string | null;
  note: string | null;
  reviewedAtLabel: string | null;
  requestFingerprint: string | null;
  idempotentReplay: boolean;
  editoriallyApproved: boolean;
}>;

export type OfficialAccountCapabilitiesViewModel = Readonly<{
  enabled: boolean;
  fixtureAvailable: boolean;
  liveAvailable: boolean;
  liveUnavailableReason: string | null;
  eligibleMaterials: readonly Readonly<{
    id: string;
    title: string;
    status: string;
    reviewStatus: string;
  }>[];
  boundaryLabel: string;
  visualSemanticEnabled: boolean;
  visualSemanticProviderMode: CapabilitiesResponse["visual_semantic_provider_mode"];
  generatedVisualsEnabled: boolean;
  editorHandoffEnabled: boolean;
}>;

export type OfficialAccountEditorHandoffViewModel = Readonly<{
  state: EditorHandoffResponse["state"];
  copyReady: boolean;
  boundaryLabel: string;
  fingerprint: string | null;
  identity: Readonly<{
    rendererVersion: string;
    styleVersion: string;
    themeId: string;
    themeSha256: string;
  }> | null;
  checks: readonly Readonly<{
    code: string;
    label: string;
    severity: "info" | "warning" | "error";
    passed: boolean;
    detail: string;
  }>[];
  blockingCodes: readonly string[];
  warningCodes: readonly string[];
  media: readonly Readonly<{
    name: string;
    role: "body" | "context" | "cover";
    roleLabel: string;
    ordinal: number;
    downloadUrl: string | null;
    mediaType: string;
    byteSize: number;
    sha256: string;
    dimensionsLabel: string;
    altText: string;
    sourcePageUrl: string | null;
    credit: string | null;
    rightsStatus: "publish_permission_unverified" | null;
  }>[];
  mobileStatus: "not_run" | "passed";
  bodyUrl: string | null;
  previewUrl: string | null;
  bundleUrl: string | null;
  bundleFilename: string | null;
  bundleSha256: string | null;
}>;

export type OfficialAccountRunSummaryViewModel = Readonly<{
  id: string;
  sourceLabel: string;
  materialPackageId: string | null;
  modeLabel: string;
  providerModel: string;
  status: OfficialAccountStatus;
  statusLabel: string;
  stage: OfficialAccountStage;
  stageLabel: string;
  attemptCount: number;
  errorCode: string | null;
  errorRetryable: boolean;
  createdAtLabel: string;
  simulation: true;
}>;

export type OfficialAccountMediaViewModel = Readonly<{
  id: string;
  role: "body" | "cover" | "context";
  roleLabel: string;
  ordinal: number;
  url: string | null;
  mediaType: string;
  byteSize: number;
  sha256: string;
  semanticLabel: string | null;
  assignedSectionIndex: number | null;
  scoreBand: "heading" | "body" | "fallback" | null;
  selectionReasonCode: string | null;
  selectionMethod: "deterministic_tag" | "multimodal_embedding" | null;
  selectionMethodLabel: string | null;
  similarityBand: "very_high" | "high" | "medium" | "low" | null;
  similarityBandLabel: string | null;
  altText: string | null;
  provenanceKind: MediaResponse["provenance_kind"];
  sourcePageUrl: string | null;
  caption: string | null;
  credit: string | null;
  rightsStatus: MediaResponse["rights_status"];
  contextOnlyNotEvidence: boolean;
}>;

export type OfficialAccountRunDetailViewModel = Readonly<{
  summary: OfficialAccountRunSummaryViewModel;
  article: RunDetailResponse["article"];
  validation: RunDetailResponse["validation"];
  audit: RunDetailResponse["audit"];
  usage: RunDetailResponse["usage"];
  media: readonly OfficialAccountMediaViewModel[];
  bodyImages: readonly Readonly<{
    id: string;
    ordinal: number;
    url: string | null;
    mediaType: string;
    byteSize: number;
    sha256: string;
  }>[];
  contextImages: readonly OfficialAccountMediaViewModel[];
  contextMediaStatus: "not_present" | "partial" | "ready";
  primaryBodyImageId: string | null;
  coverImageId: string | null;
  mediaSelection: Readonly<{
    policyVersion: string;
    bodyImageCount: number;
    targetLabel: string;
    safelyDegraded: boolean;
    explanation: readonly string[];
    mode: "multimodal_embedding" | "deterministic_fallback" | "historical";
    modeLabel: string;
    semanticStatus:
      | "semantic_ready"
      | "semantic_unavailable"
      | "single_candidate"
      | "not_applicable";
    closedReason: string | null;
    closedReasonLabel: string | null;
    visualQueryVersion: string | null;
    visualSelectorVersion: string | null;
    embeddingIdentity: Readonly<{
      provider: string;
      model: string;
      dimensions: number;
      inputPolicyVersion: string;
    }> | null;
  }>;
  generatedVisuals: readonly Readonly<{
    ordinal: number;
    sectionIndex: number;
    blockIndex: number | null;
    blockKind: "paragraph" | "bullet_list" | "quote" | "callout" | null;
    referenceAssetRef: string;
    selectionMethodLabel: string;
    similarityBandLabel: string | null;
    status: "generating" | "ready" | "failed" | "result_unknown";
    statusLabel: string;
    planVersion: string;
    outputProfileVersion: string | null;
    providerModel: string;
    outputSha256: string | null;
    dimensionsLabel: string | null;
    errorCode: string | null;
  }>[];
  generatedVisualProgress: Readonly<{
    ready: number;
    total: number;
  }>;
  draft: Readonly<{
    id: string;
    state: "ready" | "failed" | "result_unknown";
    previewUrl: string | null;
    fingerprint: string;
    createdAtLabel: string;
  }> | null;
  manualReview: OfficialAccountManualReviewViewModel;
}>;

const statusLabels: Record<OfficialAccountStatus, string> = {
  queued: "排队中",
  running: "处理中",
  review_required: "需要人工复核",
  ready: "本地草稿就绪",
  failed: "运行失败",
  result_unknown: "草稿结果未知",
};

const stageLabels: Record<OfficialAccountStage, string> = {
  queued: "等待 worker",
  generating: "生成结构化长文",
  validating: "确定性校验",
  auditing: "模型审校",
  rendering: "生成微信兼容 HTML",
  generating_body_visuals: "按正文块生成原创插画",
  staging_body_media: "登记正文图片",
  staging_cover: "登记封面",
  creating_local_draft: "创建本地模拟草稿",
  ready: "完成",
  review_required: "等待人工复核",
  failed: "失败",
  result_unknown: "结果未知，禁止自动重试",
};

export async function getOfficialAccountCapabilities(
  signal?: AbortSignal,
): Promise<OfficialAccountCapabilitiesViewModel> {
  const { data, error } = await apiClient.GET(
    "/api/v1/official-account-local/capabilities",
    signal === undefined ? {} : { signal },
  );
  if (data === undefined) throwApiError(error, "capabilities_failed");
  return mapCapabilities(data);
}

export async function listOfficialAccountRuns(
  signal?: AbortSignal,
): Promise<readonly OfficialAccountRunSummaryViewModel[]> {
  const { data, error } = await apiClient.GET(
    "/api/v1/official-account-local/article-runs",
    {
      params: { query: { limit: 50 } },
      ...(signal === undefined ? {} : { signal }),
    },
  );
  if (data === undefined) throwApiError(error, "run_list_failed");
  return data.items.map(mapRunSummary);
}

export async function getOfficialAccountRun(
  runId: string,
  signal?: AbortSignal,
): Promise<OfficialAccountRunDetailViewModel> {
  const { data, error } = await apiClient.GET(
    "/api/v1/official-account-local/article-runs/{run_id}",
    {
      params: { path: { run_id: runId } },
      ...(signal === undefined ? {} : { signal }),
    },
  );
  if (data === undefined) throwApiError(error, "run_detail_failed");
  return mapRunDetail(data);
}

export async function getOfficialAccountEditorHandoff(
  runId: string,
  signal?: AbortSignal,
): Promise<OfficialAccountEditorHandoffViewModel> {
  const { data, error } = await apiClient.GET(
    "/api/v1/official-account-local/article-runs/{run_id}/editor-handoff",
    {
      params: { path: { run_id: runId } },
      ...(signal === undefined ? {} : { signal }),
    },
  );
  if (data === undefined) throwApiError(error, "editor_handoff_failed");
  return mapEditorHandoff(data);
}

export async function getOfficialAccountEditorHandoffBody(
  runId: string,
): Promise<string> {
  const { data, error } = await apiClient.GET(
    "/api/v1/official-account-local/article-runs/{run_id}/editor-handoff/body",
    { params: { path: { run_id: runId } }, parseAs: "text" },
  );
  if (data === undefined) throwApiError(error, "editor_handoff_body_failed");
  return data;
}

export async function createFixtureArticleRun(): Promise<OfficialAccountRunSummaryViewModel> {
  return createRun({
    source: {
      kind: "fixture",
      fixture_id: "official-account-article-v1",
    },
    generation_mode: "fixture",
  });
}

export async function createLiveArticleRun(
  materialPackageId: string,
): Promise<OfficialAccountRunSummaryViewModel> {
  return createRun({
    source: {
      kind: "material_package",
      material_package_id: materialPackageId,
    },
    generation_mode: "live",
  });
}

export async function retryOfficialAccountRun(
  runId: string,
): Promise<OfficialAccountRunSummaryViewModel> {
  const { data, error } = await apiClient.POST(
    "/api/v1/official-account-local/article-runs/{run_id}/retry",
    { params: { path: { run_id: runId } } },
  );
  if (data === undefined) throwApiError(error, "run_retry_failed");
  return mapRunSummary(data);
}

export async function submitOfficialAccountManualReview(input: {
  runId: string;
  decision: OfficialAccountManualReviewDecision;
  reviewerLabel: string;
  note: string | null;
}): Promise<OfficialAccountManualReviewViewModel> {
  const body: ManualReviewRequest = {
    decision: input.decision,
    reviewer_label: input.reviewerLabel,
    note: input.note,
  };
  const { data, error } = await apiClient.POST(
    "/api/v1/official-account-local/article-runs/{run_id}/manual-review",
    { params: { path: { run_id: input.runId } }, body },
  );
  if (data === undefined) throwApiError(error, "manual_review_failed");
  return mapManualReview(data);
}

async function createRun(
  body: RunCreateRequest,
): Promise<OfficialAccountRunSummaryViewModel> {
  const { data, error } = await apiClient.POST(
    "/api/v1/official-account-local/article-runs",
    { body },
  );
  if (data === undefined) throwApiError(error, "run_create_failed");
  return mapRunSummary(data);
}

export function mapCapabilities(
  response: CapabilitiesResponse,
): OfficialAccountCapabilitiesViewModel {
  return {
    enabled: response.enabled,
    fixtureAvailable: response.fixture_available,
    liveAvailable: response.live_available,
    liveUnavailableReason: response.live_unavailable_reason ?? null,
    eligibleMaterials: (response.eligible_material_packages ?? []).map(
      (item) => ({
        id: item.id,
        title: item.title,
        status: item.status,
        reviewStatus: item.review_status,
      }),
    ),
    boundaryLabel: response.boundary_label,
    visualSemanticEnabled: response.visual_semantic_enabled,
    visualSemanticProviderMode: response.visual_semantic_provider_mode,
    generatedVisualsEnabled: response.generated_visuals_enabled,
    editorHandoffEnabled: response.editor_handoff_enabled,
  };
}

export function mapEditorHandoff(
  response: EditorHandoffResponse,
): OfficialAccountEditorHandoffViewModel {
  return {
    state: response.state,
    copyReady: response.copy_ready,
    boundaryLabel: response.boundary_label,
    fingerprint: response.fingerprint ?? null,
    identity:
      response.identity == null
        ? null
        : {
            rendererVersion: response.identity.renderer_version,
            styleVersion: response.identity.style_version,
            themeId: response.identity.theme_id,
            themeSha256: response.identity.theme_sha256,
          },
    checks: response.checks.map((item) => ({
      code: item.code,
      label: editorHandoffCheckLabel(item.code),
      severity: item.severity,
      passed: item.passed,
      detail: item.detail,
    })),
    blockingCodes: response.blocking_codes,
    warningCodes: response.warning_codes,
    media: response.media.map((item) => ({
      name: item.name,
      role: item.role,
      roleLabel:
        item.role === "body"
          ? `正文图 ${String(item.ordinal + 1).padStart(2, "0")}`
          : item.role === "context"
            ? `新闻原图 ${String(item.ordinal + 1).padStart(2, "0")}`
            : "2.35:1 封面",
      ordinal: item.ordinal,
      downloadUrl: resolveApiResourceUrl(item.download_url),
      mediaType: item.media_type,
      byteSize: item.byte_size,
      sha256: item.sha256,
      dimensionsLabel: `${item.width} × ${item.height}`,
      altText: item.alt_text,
      sourcePageUrl: item.source_page_url ?? null,
      credit: item.credit ?? null,
      rightsStatus: item.rights_status ?? null,
    })),
    mobileStatus: response.mobile_validation.status,
    bodyUrl:
      response.body_url == null
        ? null
        : resolveApiResourceUrl(response.body_url),
    previewUrl:
      response.preview_url == null
        ? null
        : resolveApiResourceUrl(response.preview_url),
    bundleUrl:
      response.bundle_url == null
        ? null
        : resolveApiResourceUrl(response.bundle_url),
    bundleFilename: response.bundle_filename ?? null,
    bundleSha256: response.bundle_sha256 ?? null,
  };
}

function editorHandoffCheckLabel(code: string): string {
  const labels: Readonly<Record<string, string>> = {
    run_ready: "运行状态",
    article_present: "结构化文章",
    article_version_supported: "文章版本",
    article_fingerprint_valid: "内容指纹",
    deterministic_validation_passed: "规则校验",
    model_audit_accepted: "模型审校",
    render_present: "固定渲染",
    simulated_draft_ready: "本地草稿",
    draft_fingerprint_valid: "草稿谱系",
    immutable_review_approved: "最终人工审稿",
    immutable_review_pending: "最终人工审稿",
    immutable_review_rejected: "最终人工审稿",
    review_fingerprint_valid: "审稿指纹",
    pure_section_fragment: "微信正文片段",
    forbidden_markup_absent: "危险标记",
    placeholder_absent: "占位符",
    private_reference_absent: "私有路径",
    wechat_markup_allowlist: "微信标签与样式",
    span_leaf_complete: "粘贴样式保护",
    controlled_relative_images: "图片引用",
    body_image_count_valid: "正文图片数量",
    body_images_unique: "正文图片去重",
    media_images_unique: "全部图片去重",
    cover_ratio_valid: "封面比例",
    asset_paths_unique: "资源路径",
    preview_body_exact_match: "预览与正文一致性",
    context_image_rights_unverified_direct_use: "新闻图片权利",
    mobile_browser_validation_not_run: "移动端浏览器验收",
    handoff_integrity_failed: "交接包完整性",
  };
  return labels[code] ?? code;
}

export function mapRunSummary(
  response: RunSummaryResponse,
): OfficialAccountRunSummaryViewModel {
  return {
    id: response.id,
    sourceLabel:
      response.source_kind === "fixture"
        ? "脱敏离线样例"
        : `素材包 ${response.material_package_id ?? "未知"}`,
    materialPackageId: response.material_package_id,
    modeLabel:
      response.generation_mode === "fixture"
        ? "FIXTURE / 离线"
        : "LIVE / 真实模型",
    providerModel: `${response.provider} / ${response.model}`,
    status: response.status,
    statusLabel: statusLabels[response.status],
    stage: response.current_stage,
    stageLabel: stageLabels[response.current_stage],
    attemptCount: response.attempt_count,
    errorCode: response.error_code,
    errorRetryable: response.error_retryable,
    createdAtLabel: formatDateTime(response.created_at),
    simulation: true,
  };
}

export function mapRunDetail(
  response: RunDetailResponse,
): OfficialAccountRunDetailViewModel {
  return {
    summary: mapRunSummary(response),
    article: response.article,
    validation: response.validation,
    audit: response.audit,
    usage: response.usage,
    media: response.media.map(mapMedia),
    bodyImages: response.body_images.map((item) => ({
      id: item.local_media_id,
      ordinal: item.ordinal,
      url: resolveApiResourceUrl(item.media_url),
      mediaType: item.media_type,
      byteSize: item.byte_size,
      sha256: item.sha256,
    })),
    contextImages: (response.context_images ?? []).map(mapMedia),
    contextMediaStatus: response.context_media_status ?? "not_present",
    primaryBodyImageId: response.body_image?.local_media_id ?? null,
    coverImageId: response.cover_image?.local_media_id ?? null,
    mediaSelection: {
      policyVersion: response.media_selection.policy_version,
      bodyImageCount: response.media_selection.body_image_count,
      targetLabel: response.media_selection.target_body_image_count,
      safelyDegraded: response.media_selection.safely_degraded,
      explanation: response.media_selection.explanation,
      mode: response.media_selection.selection_mode,
      modeLabel: selectionModeLabel(response.media_selection.selection_mode),
      semanticStatus: response.media_selection.semantic_status,
      closedReason:
        response.media_selection.semantic_unavailable_reason ?? null,
      closedReasonLabel: closedReasonLabel(
        response.media_selection.semantic_unavailable_reason ?? null,
      ),
      visualQueryVersion: response.media_selection.visual_query_version ?? null,
      visualSelectorVersion:
        response.media_selection.visual_selector_version ?? null,
      embeddingIdentity:
        response.media_selection.embedding_identity == null
          ? null
          : {
              provider: response.media_selection.embedding_identity.provider,
              model: response.media_selection.embedding_identity.model,
              dimensions:
                response.media_selection.embedding_identity.dimensions,
              inputPolicyVersion:
                response.media_selection.embedding_identity
                  .input_policy_version,
            },
    },
    generatedVisuals: (response.generated_visuals ?? []).map((item) => ({
      ordinal: item.ordinal,
      sectionIndex: item.section_index,
      blockIndex: item.block_index ?? null,
      blockKind: item.block_kind ?? null,
      referenceAssetRef: item.reference_asset_ref,
      selectionMethodLabel:
        item.selection_method === "multimodal_embedding"
          ? "多模态语义匹配"
          : "确定性标签回退",
      similarityBandLabel: similarityBandLabel(item.similarity_band ?? null),
      status: item.status,
      statusLabel: generatedVisualStatusLabel(item.status),
      planVersion: item.plan_version,
      outputProfileVersion: item.output_profile_version ?? null,
      providerModel: `${item.provider} / ${item.model}`,
      outputSha256: item.sha256 ?? null,
      dimensionsLabel:
        item.width == null || item.height == null
          ? null
          : `${item.width} × ${item.height}`,
      errorCode: item.error_code ?? null,
    })),
    generatedVisualProgress: {
      ready: (response.generated_visuals ?? []).filter(
        (item) => item.status === "ready",
      ).length,
      total: response.media_selection.body_image_count,
    },
    draft:
      response.draft === null
        ? null
        : {
            id: response.draft.local_draft_id,
            state: response.draft.state,
            previewUrl: resolveApiResourceUrl(response.draft.preview_url),
            fingerprint: response.draft.resolved_fingerprint,
            createdAtLabel: formatDateTime(response.draft.created_at),
          },
    manualReview: mapManualReview(response.manual_review),
  };
}

function mapMedia(item: MediaResponse): OfficialAccountMediaViewModel {
  return {
    id: item.local_media_id,
    role: item.role,
    roleLabel:
      item.role === "context"
        ? `新闻原图 ${String(item.ordinal + 1).padStart(2, "0")}`
        : item.role === "body"
          ? `公司 IP 图 ${String(item.ordinal + 1).padStart(2, "0")}`
          : "封面",
    ordinal: item.ordinal,
    url: resolveApiResourceUrl(item.media_url),
    mediaType: item.media_type,
    byteSize: item.byte_size,
    sha256: item.sha256,
    semanticLabel: item.semantic_label ?? null,
    assignedSectionIndex: item.assigned_section_index ?? null,
    scoreBand: item.score_band ?? null,
    selectionReasonCode: item.selection_reason_code ?? null,
    selectionMethod: item.selection_method ?? null,
    selectionMethodLabel:
      item.selection_method === "multimodal_embedding"
        ? "多模态语义匹配"
        : item.selection_method === "deterministic_tag"
          ? "确定性标签回退"
          : null,
    similarityBand: item.similarity_band ?? null,
    similarityBandLabel: similarityBandLabel(item.similarity_band ?? null),
    altText: item.alt_text ?? null,
    provenanceKind: item.provenance_kind ?? null,
    sourcePageUrl: item.source_page_url ?? null,
    caption: item.caption ?? null,
    credit: item.credit ?? null,
    rightsStatus: item.rights_status ?? null,
    contextOnlyNotEvidence: item.context_only_not_evidence,
  };
}

function selectionModeLabel(
  value: OfficialAccountRunDetailViewModel["mediaSelection"]["mode"],
): string {
  if (value === "multimodal_embedding") return "多模态语义匹配";
  if (value === "deterministic_fallback") return "确定性标签回退";
  return "历史版本规则";
}

function similarityBandLabel(
  value: "very_high" | "high" | "medium" | "low" | null,
): string | null {
  if (value === "very_high") return "相似度：很高";
  if (value === "high") return "相似度：高";
  if (value === "medium") return "相似度：中";
  if (value === "low") return "相似度：低";
  return null;
}

function generatedVisualStatusLabel(
  value: "generating" | "ready" | "failed" | "result_unknown",
): string {
  if (value === "generating") return "正在生成";
  if (value === "ready") return "生成完成";
  if (value === "failed") return "生成失败";
  return "结果未知，禁止自动重试";
}

function closedReasonLabel(value: string | null): string | null {
  const labels: Readonly<Record<string, string>> = {
    disabled: "语义匹配未启用",
    single_candidate: "只有一个合格候选，无需调用模型",
    index_incomplete: "当前批准图库索引不完整",
    provider_unavailable: "语义服务不可用",
    invalid_provider_output: "语义服务结果未通过校验",
    identity_mismatch: "语义模型身份不匹配",
    catalog_changed: "选图期间批准图库发生变化",
    input_normalization_failed: "章节查询未通过安全规范化",
    selection_pending: "选图结果尚未生成",
  };
  return value === null ? null : (labels[value] ?? "语义匹配已安全关闭");
}

export function mapManualReview(
  response: ManualReviewResponse,
): OfficialAccountManualReviewViewModel {
  const statusLabels: Record<ManualReviewResponse["status"], string> = {
    pending: "等待最终人工审稿",
    approved: "人工审稿已批准",
    rejected: "人工审稿已退回",
  };
  return {
    status: response.status,
    statusLabel: statusLabels[response.status],
    reviewId: response.review_id ?? null,
    reviewerLabel: response.reviewer_label ?? null,
    note: response.note ?? null,
    reviewedAtLabel:
      response.reviewed_at == null
        ? null
        : formatDateTime(response.reviewed_at),
    requestFingerprint: response.request_fingerprint ?? null,
    idempotentReplay: response.idempotent_replay,
    editoriallyApproved: response.editorially_approved,
  };
}

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? value
    : parsed.toLocaleString("zh-CN");
}

function throwApiError(error: unknown, fallback: string): never {
  if (typeof error === "object" && error !== null && "error" in error) {
    const envelope = error as Readonly<{
      error?: Readonly<{ code?: string; message?: string }>;
    }>;
    throw new Error(
      envelope.error?.code ?? envelope.error?.message ?? fallback,
    );
  }
  throw new Error(fallback);
}
