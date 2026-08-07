import type { components } from "@/lib/api/generated/schema";
import { apiClient, resolveApiResourceUrl } from "@/lib/api/client";

export type MaterialPackageResponse =
  components["schemas"]["MaterialPackageResponse"];
export type MaterialPackageDownloadResponse =
  components["schemas"]["MaterialPackageDownloadResponse"];
export type MaterialPackageStatus = MaterialPackageResponse["status"];
export type MaterialPackageReviewStatus =
  MaterialPackageResponse["review_status"];
export type ImageArtifactStatus = MaterialPackageResponse["image"]["status"];
export type ImageReferenceMode =
  MaterialPackageResponse["image"]["reference_mode"];
export type MaterialPackageListResponse =
  components["schemas"]["MaterialPackageListResponse"];
export type MaterialPackageSummaryResponse =
  components["schemas"]["MaterialPackageSummaryResponse"];

type UnknownRecord = Readonly<Record<string, unknown>>;

export type TopicDecisionKind = "selected" | "no_topic" | "unknown";
export type ClaimKind =
  "external_fact" | "brand_statement" | "opinion" | "unknown";
export type IssueSeverity = "warning" | "error" | "info";
export type IssueStage = "deterministic" | "audit" | "unknown";

export type ScoreMetricViewModel = Readonly<{
  label: string;
  value: string;
}>;

export type TopicViewModel = Readonly<{
  title: string;
  summary: string | null;
  category: string | null;
  sourceTrust: string | null;
  decisionKind: TopicDecisionKind;
  decisionLabel: string;
  explanation: string;
  businessDate: string;
  timezone: string | null;
  selectedEventId: string | null;
  selectedEventVersionId: string | null;
  score: number | null;
  scoreBreakdown: readonly ScoreMetricViewModel[];
}>;

export type ClaimViewModel = Readonly<{
  id: string;
  text: string;
  kind: ClaimKind;
  evidenceIds: readonly string[];
  brandChunkIds: readonly string[];
}>;

export type CopyViewModel = Readonly<{
  copywriting: string;
  parentTakeaway: string;
  interaction: string;
  sourceNote: string;
  draftVersionId: string | null;
  version: number | null;
  claims: readonly ClaimViewModel[];
}>;

export type EvidenceViewModel = Readonly<{
  id: string;
  claimId: string | null;
  label: string;
  sourceUrl: string | null;
  sourceTier: string | null;
  publishedAt: string | null;
  exactQuote: string | null;
  claimText: string | null;
}>;

export type BrandBindingViewModel = Readonly<{
  id: string;
  claimId: string | null;
  brandChunkId: string;
  documentTitle: string | null;
  audience: string | null;
  text: string | null;
  toneTags: readonly string[];
  safetyTags: readonly string[];
}>;

export type MaterialIssueViewModel = Readonly<{
  id: string;
  stage: IssueStage;
  code: string;
  message: string;
  severity: IssueSeverity;
  field: string | null;
  claimId: string | null;
}>;

export type ValidationViewModel = Readonly<{
  passed: boolean | null;
  ruleVersion: string | null;
  issues: readonly MaterialIssueViewModel[];
}>;

export type AuditViewModel = Readonly<{
  accepted: boolean | null;
  status: "accepted" | "rejected" | "pending" | "unknown";
  ruleVersion: string | null;
  promptVersion: string | null;
  schemaVersion: string | null;
  auditId: string | null;
  diagnostic: string | null;
  issues: readonly MaterialIssueViewModel[];
}>;

export type ImageValidationViewModel = Readonly<{
  version: string;
  configured: boolean;
  passed: boolean | null;
  issueCodes: readonly string[];
  provider: string | null;
  model: string | null;
  mediaType: string | null;
  width: number | null;
  height: number | null;
  byteSize: number | null;
}>;

export type ImageAuditViewModel = Readonly<{
  version: string;
  configured: boolean;
  status:
    "accepted" | "rejected" | "not_applicable" | "not_configured" | "unknown";
  passed: boolean | null;
  issueCodes: readonly string[];
  provider: string | null;
  model: string | null;
}>;

export type ImageFallbackViewModel = Readonly<{
  state: "not_used" | "neutralized_retry" | "brand_catalog";
  providerRejectionRetryCount: number;
  asset: Readonly<{
    filename: string;
    selectionReason: string;
    role: VisualReferenceViewModel["role"];
    roleLabel: string;
  }> | null;
}>;

export type ImageViewModel = Readonly<{
  id: string;
  status: ImageArtifactStatus;
  statusLabel: string;
  provider: string;
  model: string;
  width: number | null;
  height: number | null;
  mediaType: string | null;
  byteSize: number | null;
  sha256: string | null;
  errorCode: string | null;
  downloadUrl: string | null;
  referenceMode: ImageReferenceMode;
  repairCount: number;
  fallback: ImageFallbackViewModel;
  validation: ImageValidationViewModel;
  audit: ImageAuditViewModel;
  visualBrief: VisualBriefViewModel | null;
  references: readonly VisualReferenceViewModel[];
}>;

export type VisualBriefViewModel = Readonly<{
  version: string;
  category: string;
  learningGoal: string;
  scene: string;
  mainAction: string;
  characters: readonly string[];
  assetTags: readonly string[];
  referenceRoles: readonly string[];
  renderTextMode: string;
  textLayer: Readonly<{
    title: string;
    learningLine: string;
    keywords: readonly string[];
    brandValues: readonly string[];
  }>;
}>;

export type VisualReferenceViewModel = Readonly<{
  role:
    "identity_reference" | "action_reference" | "style_reference" | "legacy";
  roleLabel: string;
  assetId: string;
  filename: string;
  sha256: string;
  selectionReason: string;
  fallback: boolean;
}>;

export type ReviewViewModel = Readonly<{
  status: MaterialPackageReviewStatus;
  statusLabel: string;
  note: string | null;
  reviewedAt: string | null;
  reviewUrl: string;
}>;

export type MaterialPackageViewModel = Readonly<{
  id: string;
  copyGenerationRunId: string;
  status: MaterialPackageStatus;
  statusLabel: string;
  reviewStatus: MaterialPackageReviewStatus;
  reviewStatusLabel: string;
  businessDate: string;
  createdAt: string;
  createdAtLabel: string;
  detailUrl: string;
  packageVersion: number;
  topic: TopicViewModel;
  copy: CopyViewModel;
  evidence: readonly EvidenceViewModel[];
  brandBindings: readonly BrandBindingViewModel[];
  validation: ValidationViewModel;
  audit: AuditViewModel;
  image: ImageViewModel;
  review: ReviewViewModel;
}>;

export type MaterialPackageSummaryViewModel = Readonly<{
  id: string;
  copyGenerationRunId: string;
  status: MaterialPackageStatus;
  statusLabel: string;
  reviewStatus: MaterialPackageReviewStatus;
  reviewStatusLabel: string;
  businessDate: string;
  createdAt: string;
  createdAtLabel: string;
  detailUrl: string;
}>;

export type MaterialPackageListViewModel = Readonly<{
  items: readonly MaterialPackageSummaryViewModel[];
  count: number;
}>;

const packageStatusLabels: Readonly<Record<MaterialPackageStatus, string>> = {
  queued: "排队中",
  ready: "已就绪",
  awaiting_manual_use: "待人工使用",
  completed: "内部已确认",
  rejected: "已驳回",
  failed: "生成失败",
};

const reviewStatusLabels: Readonly<
  Record<MaterialPackageReviewStatus, string>
> = {
  pending: "待人工审核",
  approved: "审核通过",
  rejected: "审核驳回",
};

const imageStatusLabels: Readonly<Record<ImageArtifactStatus, string>> = {
  queued: "图片排队中",
  running: "图片生成中",
  succeeded: "图片已生成",
  failed: "图片失败",
  review_required: "图片待复核",
};

export async function listMaterialPackages(
  signal?: AbortSignal,
): Promise<MaterialPackageListViewModel> {
  const { data, error } = await apiClient.GET("/api/v1/material-packages", {
    ...(signal === undefined ? {} : { signal }),
  });
  if (data === undefined)
    throw new Error(
      error === undefined ? "material_list_failed" : "material_api_error",
    );
  return {
    count: data.count,
    items: data.items.map(mapMaterialPackageSummary),
  };
}

export async function getMaterialPackage(
  packageId: string,
  signal?: AbortSignal,
): Promise<MaterialPackageViewModel> {
  const { data, error } = await apiClient.GET(
    "/api/v1/material-packages/{package_id}",
    {
      params: { path: { package_id: packageId } },
      ...(signal === undefined ? {} : { signal }),
    },
  );
  if (data === undefined)
    throw new Error(
      error === undefined ? "material_detail_failed" : "material_api_error",
    );
  return mapMaterialPackage(data);
}

export async function downloadMaterialPackage(
  packageId: string,
  signal?: AbortSignal,
): Promise<MaterialPackageDownloadResponse> {
  const { data, error } = await apiClient.GET(
    "/api/v1/material-packages/{package_id}/download",
    {
      params: { path: { package_id: packageId } },
      ...(signal === undefined ? {} : { signal }),
    },
  );
  if (data === undefined)
    throw new Error(
      error === undefined ? "material_download_failed" : "material_api_error",
    );
  return data;
}

export async function generateMaterialPackage(
  copyGenerationRunId: string,
): Promise<MaterialPackageViewModel> {
  const { data, error } = await apiClient.POST("/api/v1/material-packages", {
    body: { copy_generation_run_id: copyGenerationRunId, reviewer: "internal" },
  });
  if (data === undefined)
    throw new Error(
      error === undefined ? "material_generate_failed" : "material_api_error",
    );
  return mapMaterialPackage(data);
}

export async function reviewMaterialPackage(
  packageId: string,
  decision: "approved" | "rejected",
  note: string,
): Promise<MaterialPackageViewModel> {
  const { data, error } = await apiClient.POST(
    "/api/v1/material-packages/{package_id}/review",
    {
      params: { path: { package_id: packageId } },
      body: { decision, reviewer: "internal", note: note || null },
    },
  );
  if (data === undefined)
    throw new Error(
      error === undefined ? "material_review_failed" : "material_api_error",
    );
  return mapMaterialPackage(data);
}

export function mapMaterialPackage(
  response: MaterialPackageResponse,
): MaterialPackageViewModel {
  const topicRecord = toRecord(response.topic);
  const copyRecord = toRecord(response.copy);
  const auditRecord = toRecord(response.audit);
  const validationRecord = toRecord(response.validation);
  const claims = parseClaims(copyRecord);

  return {
    id: response.id,
    copyGenerationRunId: response.copy_generation_run_id,
    status: response.status,
    statusLabel: packageStatusLabels[response.status],
    reviewStatus: response.review_status,
    reviewStatusLabel: reviewStatusLabels[response.review_status],
    businessDate: response.business_date,
    createdAt: response.created_at,
    createdAtLabel: formatDateTime(response.created_at),
    detailUrl: response.detail_url,
    packageVersion: response.package_version,
    topic: parseTopic(topicRecord, response.business_date),
    copy: parseCopy(copyRecord, claims),
    evidence: parseEvidence(response.sources, claims),
    brandBindings: parseBrandBindings(
      response.brand_bindings,
      copyRecord,
      auditRecord,
      claims,
    ),
    validation: parseValidation(validationRecord, copyRecord, auditRecord),
    audit: parseAudit(auditRecord),
    image: parseImage(response.image),
    review: {
      status: response.review_status,
      statusLabel: reviewStatusLabels[response.review_status],
      note: response.review_note,
      reviewedAt: response.reviewed_at,
      reviewUrl: response.review_url,
    },
  };
}

function mapMaterialPackageSummary(
  response: MaterialPackageSummaryResponse,
): MaterialPackageSummaryViewModel {
  return {
    id: response.id,
    copyGenerationRunId: response.copy_generation_run_id,
    status: response.status,
    statusLabel: packageStatusLabels[response.status],
    reviewStatus: response.review_status,
    reviewStatusLabel: reviewStatusLabels[response.review_status],
    businessDate: response.business_date,
    createdAt: response.created_at,
    createdAtLabel: formatDateTime(response.created_at),
    detailUrl: response.detail_url,
  };
}

function parseTopic(
  record: UnknownRecord,
  businessDate: string,
): TopicViewModel {
  const decisionKind = readTopicDecisionKind(record, "decision_kind");
  const title =
    readString(record, "title") ??
    readString(record, "topic_title") ??
    "已锁定选题";
  const summary = readString(record, "summary");
  const category =
    readString(record, "category") ?? readString(record, "category_label");
  const sourceTrust =
    readString(record, "source_trust") ??
    readString(record, "source_trust_label");
  const explanation =
    readString(record, "selection_explanation") ??
    readString(record, "selection_reason") ??
    readString(record, "explanation") ??
    buildTopicExplanation(decisionKind, category, sourceTrust);

  return {
    title,
    summary,
    category,
    sourceTrust,
    decisionKind,
    decisionLabel:
      decisionKind === "selected"
        ? "已选中"
        : decisionKind === "no_topic"
          ? "未达到选题门槛"
          : "状态未说明",
    explanation,
    businessDate: readString(record, "business_date") ?? businessDate,
    timezone: readString(record, "timezone"),
    selectedEventId: readString(record, "selected_event_id"),
    selectedEventVersionId: readString(record, "selected_event_version_id"),
    score:
      readNumber(record, "score") ??
      readNumber(record, "selection_score") ??
      readNumber(record, "total_score"),
    scoreBreakdown: parseScoreBreakdown(
      readUnknown(record, "score_breakdown") ??
        readUnknown(record, "score_components") ??
        readUnknown(record, "scores"),
    ),
  };
}

function parseCopy(
  record: UnknownRecord,
  claims: readonly ClaimViewModel[],
): CopyViewModel {
  return {
    copywriting: readString(record, "copywriting") ?? "",
    parentTakeaway:
      readString(record, "parent_takeaway") ??
      readString(record, "takeaway") ??
      "",
    interaction: readString(record, "interaction") ?? "",
    sourceNote: readString(record, "source_note") ?? "",
    draftVersionId: readString(record, "draft_version_id"),
    version: readNumber(record, "version"),
    claims,
  };
}

function parseClaims(record: UnknownRecord): readonly ClaimViewModel[] {
  const rawClaims = readUnknown(record, "claims");
  if (!Array.isArray(rawClaims)) return [];
  return rawClaims.flatMap((value, index) => {
    const claim = toRecord(value);
    const id =
      readString(claim, "claim_id") ??
      readString(claim, "id") ??
      `claim-${index + 1}`;
    const text = readString(claim, "text") ?? readString(claim, "claim_text");
    if (text === null) return [];
    return [
      {
        id,
        text,
        kind: readClaimKind(claim, "kind"),
        evidenceIds: readStringArray(claim, "evidence_ids"),
        brandChunkIds: readFirstStringArray(claim, [
          "brand_chunk_ids",
          "brandChunkIds",
        ]),
      },
    ];
  });
}

function parseEvidence(
  values: readonly UnknownRecord[],
  claims: readonly ClaimViewModel[],
): readonly EvidenceViewModel[] {
  return values.flatMap((value, index) => {
    const claimId =
      readString(value, "claim_id") ?? readString(value, "claim_key");
    const claimText =
      claims.find((claim) => claim.id === claimId)?.text ?? null;
    const rawUrl = readString(value, "source_url");
    const sourceUrl = rawUrl === null ? null : toSafeHttpUrl(rawUrl);
    const exactQuote =
      readString(value, "exact_quote") ?? readString(value, "quote");
    const label =
      readString(value, "source_name") ??
      readString(value, "title") ??
      claimText ??
      exactQuote ??
      `证据 ${index + 1}`;
    return [
      {
        id: `${claimId ?? "evidence"}-${index + 1}`,
        claimId,
        label,
        sourceUrl,
        sourceTier: readString(value, "source_tier"),
        publishedAt: readString(value, "published_at"),
        exactQuote,
        claimText,
      },
    ];
  });
}

function parseBrandBindings(
  responseBindings: readonly UnknownRecord[],
  copy: UnknownRecord,
  audit: UnknownRecord,
  claims: readonly ClaimViewModel[],
): readonly BrandBindingViewModel[] {
  const bindings: BrandBindingViewModel[] = [];
  const seen = new Set<string>();
  const add = (binding: BrandBindingViewModel) => {
    if (seen.has(binding.id)) return;
    seen.add(binding.id);
    bindings.push(binding);
  };

  for (const value of [
    responseBindings,
    readUnknown(copy, "brand_bindings"),
    readUnknown(copy, "brand_context"),
    readUnknown(audit, "brand_bindings"),
    readUnknown(audit, "brand_context"),
  ]) {
    if (!Array.isArray(value)) continue;
    value.forEach((item, index) => {
      const record = toRecord(item);
      const brandChunkId =
        readString(record, "brand_chunk_id") ??
        readString(record, "chunk_id") ??
        readString(record, "id");
      if (brandChunkId === null) return;
      add({
        id: `${brandChunkId}-${index}`,
        claimId:
          readString(record, "claim_id") ?? readString(record, "claim_key"),
        brandChunkId,
        documentTitle:
          readString(record, "document_title") ?? readString(record, "title"),
        audience: readString(record, "audience"),
        text: readString(record, "text") ?? readString(record, "excerpt"),
        toneTags: readFirstStringArray(record, ["tone_tags", "toneTags"]),
        safetyTags: readFirstStringArray(record, ["safety_tags", "safetyTags"]),
      });
    });
  }

  claims.forEach((claim) => {
    claim.brandChunkIds.forEach((brandChunkId) => {
      add({
        id: `${claim.id}-${brandChunkId}`,
        claimId: claim.id,
        brandChunkId,
        documentTitle: null,
        audience: null,
        text: null,
        toneTags: [],
        safetyTags: [],
      });
    });
  });

  for (const brandChunkId of [
    ...readFirstStringArray(copy, ["brand_chunk_ids", "brandChunkIds"]),
    ...readFirstStringArray(audit, ["brand_chunk_ids", "brandChunkIds"]),
  ]) {
    add({
      id: `package-${brandChunkId}`,
      claimId: null,
      brandChunkId,
      documentTitle: null,
      audience: null,
      text: null,
      toneTags: [],
      safetyTags: [],
    });
  }
  return bindings;
}

function parseValidation(
  validation: UnknownRecord,
  copy: UnknownRecord,
  audit: UnknownRecord,
): ValidationViewModel {
  const passed =
    readBoolean(validation, "passed") ??
    readBoolean(copy, "validation_passed") ??
    readBoolean(audit, "validation_passed") ??
    readBoolean(audit, "deterministic_validation_passed");
  const issues = [
    ...parseIssues(readUnknown(validation, "issues"), "deterministic"),
    ...parseIssues(readUnknown(copy, "validation_issues"), "deterministic"),
    ...parseIssues(readUnknown(copy, "deterministic_issues"), "deterministic"),
    ...parseIssues(readUnknown(audit, "validation_issues"), "deterministic"),
    ...parseIssues(readUnknown(audit, "deterministic_issues"), "deterministic"),
  ];
  return {
    passed,
    ruleVersion:
      readString(validation, "rule_version") ??
      readString(copy, "validation_rule_version") ??
      readString(audit, "validation_rule_version") ??
      readString(audit, "rule_version"),
    issues: deduplicateIssues(issues),
  };
}

function parseAudit(record: UnknownRecord): AuditViewModel {
  const accepted = readBoolean(record, "accepted");
  const statusValue = readString(record, "status");
  const status =
    accepted === true
      ? "accepted"
      : accepted === false
        ? "rejected"
        : statusValue === "pending" ||
            statusValue === "accepted" ||
            statusValue === "rejected"
          ? statusValue
          : "unknown";
  return {
    accepted,
    status,
    ruleVersion: readString(record, "rule_version"),
    promptVersion: readString(record, "prompt_version"),
    schemaVersion: readString(record, "schema_version"),
    auditId: readString(record, "audit_id"),
    diagnostic:
      readString(record, "diagnostic") ??
      readString(record, "error_message") ??
      readString(record, "error_code"),
    issues: deduplicateIssues(
      parseIssues(readUnknown(record, "issues"), "audit"),
    ),
  };
}

function parseImage(image: MaterialPackageResponse["image"]): ImageViewModel {
  const fallbackAsset = image.fallback.asset ?? null;
  return {
    id: image.id,
    status: image.status,
    statusLabel: imageStatusLabels[image.status],
    provider: image.provider,
    model: image.model,
    width: image.width,
    height: image.height,
    mediaType: image.media_type,
    byteSize: image.byte_size,
    sha256: image.sha256,
    errorCode: image.error_code,
    downloadUrl:
      image.download_url === null
        ? null
        : resolveApiResourceUrl(image.download_url),
    referenceMode: image.reference_mode,
    repairCount: image.repair_count,
    fallback: {
      state: image.fallback.state,
      providerRejectionRetryCount:
        image.fallback.provider_rejection_retry_count,
      asset:
        fallbackAsset === null
          ? null
          : {
              filename: fallbackAsset.filename,
              selectionReason: fallbackAsset.selection_reason,
              role: fallbackAsset.role,
              roleLabel: visualReferenceRoleLabels[fallbackAsset.role],
            },
    },
    validation: {
      version: image.validation.version,
      configured: image.validation.configured,
      passed: image.validation.passed,
      issueCodes: image.validation.issue_codes,
      provider: image.validation.provider,
      model: image.validation.model,
      mediaType: image.validation.media_type ?? null,
      width: image.validation.width ?? null,
      height: image.validation.height ?? null,
      byteSize: image.validation.byte_size ?? null,
    },
    audit: {
      version: image.audit.version,
      configured: image.audit.configured,
      status: image.audit.status,
      passed: image.audit.passed,
      issueCodes: image.audit.issue_codes,
      provider: image.audit.provider,
      model: image.audit.model,
    },
    visualBrief: parseVisualBrief(image.visual_brief),
    references: (image.references ?? []).map((reference) => ({
      role: reference.role,
      roleLabel: visualReferenceRoleLabels[reference.role],
      assetId: reference.asset_id,
      filename: reference.filename,
      sha256: reference.sha256,
      selectionReason: reference.selection_reason,
      fallback: reference.fallback,
    })),
  };
}

const visualReferenceRoleLabels: Readonly<
  Record<VisualReferenceViewModel["role"], string>
> = {
  identity_reference: "身份素材",
  action_reference: "动作素材",
  style_reference: "风格素材",
  legacy: "兼容素材",
};

function parseVisualBrief(
  brief: MaterialPackageResponse["image"]["visual_brief"],
): VisualBriefViewModel | null {
  if (brief === null || brief === undefined) return null;
  return {
    version: brief.version,
    category: brief.category,
    learningGoal: brief.learning_goal,
    scene: brief.scene,
    mainAction: brief.main_action,
    characters: brief.characters,
    assetTags: brief.asset_tags,
    referenceRoles: brief.reference_roles,
    renderTextMode: brief.render_text_mode,
    textLayer: {
      title: brief.text_layer.title,
      learningLine: brief.text_layer.learning_line,
      keywords: brief.text_layer.keywords,
      brandValues: brief.text_layer.brand_values,
    },
  };
}

function parseScoreBreakdown(value: unknown): readonly ScoreMetricViewModel[] {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => {
      const record = toRecord(item);
      const label =
        readString(record, "label") ??
        readString(record, "name") ??
        readString(record, "key") ??
        `指标 ${index + 1}`;
      const metricValue =
        readPrimitive(record, "value") ??
        readPrimitive(record, "score") ??
        readPrimitive(record, "weight");
      return metricValue === null ? [] : [{ label, value: metricValue }];
    });
  }
  const record = toRecord(value);
  return Object.entries(record).flatMap(([label, metricValue]) => {
    const valueLabel = primitiveToString(metricValue);
    return valueLabel === null ? [] : [{ label, value: valueLabel }];
  });
}

function parseIssues(
  value: unknown,
  defaultStage: IssueStage,
): readonly MaterialIssueViewModel[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index) => {
    const record = toRecord(item);
    const message =
      readString(record, "message") ??
      readString(record, "safe_message") ??
      readString(record, "detail");
    if (message === null) return [];
    const stageValue = readString(record, "stage");
    const stage: IssueStage =
      stageValue === "deterministic" || stageValue === "audit"
        ? stageValue
        : defaultStage;
    return [
      {
        id: `${stage}-${readString(record, "code") ?? "issue"}-${index}`,
        stage,
        code: readString(record, "code") ?? "unknown_issue",
        message,
        severity: readIssueSeverity(record, "severity"),
        field: readString(record, "field") ?? readString(record, "field_name"),
        claimId:
          readString(record, "claim_id") ?? readString(record, "claim_key"),
      },
    ];
  });
}

function deduplicateIssues(
  issues: readonly MaterialIssueViewModel[],
): readonly MaterialIssueViewModel[] {
  const seen = new Set<string>();
  return issues.filter((issue) => {
    const key = `${issue.stage}:${issue.code}:${issue.message}:${issue.claimId ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function buildTopicExplanation(
  decisionKind: TopicDecisionKind,
  category: string | null,
  sourceTrust: string | null,
): string {
  if (decisionKind === "no_topic") {
    return "本次选题没有达到生成门槛，系统不会把它包装成可用素材。";
  }
  const context = [category, sourceTrust].filter(
    (value): value is string => value !== null,
  );
  if (context.length > 0) {
    return `选题已锁定，分类为${context.join("、")}；下方事件标识用于回溯本次选择。`;
  }
  return "选题已锁定；下方事件标识用于回溯本次选择。";
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function toRecord(value: unknown): UnknownRecord {
  return isRecord(value) ? value : {};
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readUnknown(record: UnknownRecord, key: string): unknown {
  return record[key];
}

function readString(record: UnknownRecord, key: string): string | null {
  const value = record[key];
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function readNumber(record: UnknownRecord, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readBoolean(record: UnknownRecord, key: string): boolean | null {
  const value = record[key];
  return typeof value === "boolean" ? value : null;
}

function readPrimitive(record: UnknownRecord, key: string): string | null {
  return primitiveToString(record[key]);
}

function primitiveToString(value: unknown): string | null {
  if (typeof value === "string" && value.trim().length > 0) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  return null;
}

function readStringArray(
  record: UnknownRecord,
  key: string,
): readonly string[] {
  const value = record[key];
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is string =>
      typeof item === "string" && item.trim().length > 0,
  );
}

function readFirstStringArray(
  record: UnknownRecord,
  keys: readonly string[],
): readonly string[] {
  for (const key of keys) {
    const values = readStringArray(record, key);
    if (values.length > 0) return values;
  }
  return [];
}

function readTopicDecisionKind(
  record: UnknownRecord,
  key: string,
): TopicDecisionKind {
  const value = record[key];
  return value === "selected" || value === "no_topic" ? value : "unknown";
}

function readClaimKind(record: UnknownRecord, key: string): ClaimKind {
  const value = record[key];
  return value === "external_fact" ||
    value === "brand_statement" ||
    value === "opinion"
    ? value
    : "unknown";
}

function readIssueSeverity(record: UnknownRecord, key: string): IssueSeverity {
  const value = record[key];
  return value === "warning" || value === "error" || value === "info"
    ? value
    : "info";
}

function toSafeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}
