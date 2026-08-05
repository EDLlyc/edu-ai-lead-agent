export const DEFAULT_PREVIEW_MANIFEST_URL = "/preview/latest.json";

type ManifestRecord = Readonly<Record<string, unknown>>;

type PreviewImportMetaEnv = ImportMetaEnv & {
  readonly VITE_PREVIEW_MANIFEST_URL?: string;
};

export type PreviewStatus =
  | "ready"
  | "loading"
  | "empty"
  | "no_topic"
  | "failed"
  | "review_required"
  | "cancelled"
  | "unknown";

export type PreviewStageStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "review_required"
  | "no_topic"
  | "cancelled"
  | "skipped"
  | "unknown";

export type PreviewIssueSeverity = "info" | "warning" | "error";

export type PreviewStageViewModel = Readonly<{
  id: string;
  label: string;
  status: PreviewStageStatus;
  statusLabel: string;
  runId: string | null;
  version: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  startedAtLabel: string;
  finishedAtLabel: string;
  errorCode: string | null;
  errorMessage: string | null;
}>;

export type PreviewSourceViewModel = Readonly<{
  id: string;
  title: string;
  sourceName: string | null;
  url: string | null;
  sourceTier: string | null;
  publishedAt: string | null;
  publishedAtLabel: string;
  summary: string | null;
  status: string | null;
  statusLabel: string;
  isSelected: boolean;
}>;

export type PreviewTopicViewModel = Readonly<{
  title: string;
  summary: string | null;
  category: string | null;
  sourceTrust: string | null;
  decision: "selected" | "no_topic" | "unknown";
  decisionLabel: string;
  explanation: string;
  score: number | null;
  scoreLabel: string;
  selectedSourceId: string | null;
}>;

export type PreviewCopyViewModel = Readonly<{
  copywriting: string;
  hashtags: readonly string[];
  parentTakeaway: string;
  interaction: string;
  sourceNote: string;
  version: string | null;
}>;

export type PreviewQualityViewModel = Readonly<{
  status: "passed" | "failed" | "pending" | "not_configured" | "unknown";
  statusLabel: string;
  version: string | null;
  issueCodes: readonly string[];
}>;

export type PreviewImageViewModel = Readonly<{
  status:
    "ready" | "review_required" | "failed" | "pending" | "missing" | "unknown";
  statusLabel: string;
  url: string | null;
  alt: string;
  filename: string;
  mediaType: string | null;
  width: number | null;
  height: number | null;
  byteSize: number | null;
  validation: PreviewQualityViewModel;
  audit: PreviewQualityViewModel;
}>;

export type PreviewBrandBindingViewModel = Readonly<{
  id: string;
  title: string;
  role: string | null;
  reason: string | null;
  tags: readonly string[];
}>;

export type PreviewFindingViewModel = Readonly<{
  id: string;
  stage: string;
  severity: PreviewIssueSeverity;
  code: string;
  message: string;
  field: string | null;
}>;

export type PreviewManifestViewModel = Readonly<{
  schemaVersion: string;
  runId: string;
  status: PreviewStatus;
  statusLabel: string;
  generatedAt: string | null;
  generatedAtLabel: string;
  businessDate: string | null;
  stages: readonly PreviewStageViewModel[];
  sources: readonly PreviewSourceViewModel[];
  topic: PreviewTopicViewModel;
  copy: PreviewCopyViewModel;
  validation: PreviewQualityViewModel;
  audit: PreviewQualityViewModel;
  image: PreviewImageViewModel;
  brandBindings: readonly PreviewBrandBindingViewModel[];
  findings: readonly PreviewFindingViewModel[];
  errorCode: string | null;
  errorMessage: string | null;
  downloadPayload: Readonly<Record<string, unknown>>;
}>;

export type PreviewManifestErrorCode =
  "not_found" | "request_failed" | "invalid_manifest" | "network_error";

export class PreviewManifestError extends Error {
  readonly code: PreviewManifestErrorCode;
  readonly httpStatus: number | null;

  constructor(
    code: PreviewManifestErrorCode,
    message: string,
    httpStatus: number | null = null,
  ) {
    super(message);
    this.name = "PreviewManifestError";
    this.code = code;
    this.httpStatus = httpStatus;
  }
}

const stageLabels: Readonly<Record<string, string>> = {
  acquisition: "权威来源采集",
  source_acquisition: "权威来源采集",
  governance: "事实治理",
  factual_governance: "事实治理",
  topic_selection: "Top 1 选题",
  "topic-selection": "Top 1 选题",
  content_selection: "Top 1 选题",
  copy_generation: "朋友圈文案生成",
  "copy-generation": "朋友圈文案生成",
  content_generation: "朋友圈文案生成",
  material_package: "品牌视觉与素材包",
  "material-package": "品牌视觉与素材包",
  image_generation: "品牌视觉与素材包",
};

const previewStatusLabels: Readonly<Record<PreviewStatus, string>> = {
  ready: "可人工预览",
  loading: "链路处理中",
  empty: "暂无预览",
  no_topic: "今日没有合格 Top 1",
  failed: "链路失败",
  review_required: "待人工复核",
  cancelled: "已取消",
  unknown: "状态未说明",
};

const stageStatusLabels: Readonly<Record<PreviewStageStatus, string>> = {
  queued: "排队中",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
  review_required: "待复核",
  no_topic: "无合格选题",
  cancelled: "已取消",
  skipped: "未执行",
  unknown: "未记录",
};

const imageStatusLabels: Readonly<
  Record<PreviewImageViewModel["status"], string>
> = {
  ready: "图片已生成",
  review_required: "图片待复核",
  failed: "图片失败",
  pending: "图片生成中",
  missing: "没有可展示的图片",
  unknown: "图片状态未说明",
};

const qualityStatusLabels: Readonly<
  Record<PreviewQualityViewModel["status"], string>
> = {
  passed: "验证通过",
  failed: "验证未通过",
  pending: "尚未完成",
  not_configured: "未配置",
  unknown: "状态未说明",
};

export function getPreviewManifestUrl(): string {
  const configured = (import.meta.env as PreviewImportMetaEnv)
    .VITE_PREVIEW_MANIFEST_URL;
  const trimmed = configured?.trim();
  return trimmed === undefined || trimmed.length === 0
    ? DEFAULT_PREVIEW_MANIFEST_URL
    : trimmed;
}

export async function fetchPreviewManifest(
  manifestUrl = getPreviewManifestUrl(),
  signal?: AbortSignal,
): Promise<PreviewManifestViewModel> {
  if (resolveHttpUrl(manifestUrl, getDocumentBaseUrl()) === null) {
    throw new PreviewManifestError(
      "invalid_manifest",
      "preview manifest URL is not an HTTP resource",
    );
  }

  let response: Response;
  try {
    response = await fetch(manifestUrl, {
      headers: { Accept: "application/json" },
      ...(signal === undefined ? {} : { signal }),
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new PreviewManifestError(
      "network_error",
      "preview manifest could not be fetched",
    );
  }

  if (response.status === 404) {
    throw new PreviewManifestError(
      "not_found",
      "preview manifest has not been generated",
      response.status,
    );
  }
  if (!response.ok) {
    throw new PreviewManifestError(
      "request_failed",
      "preview manifest request failed",
      response.status,
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new PreviewManifestError(
      "invalid_manifest",
      "preview manifest is not valid JSON",
      response.status,
    );
  }

  try {
    return mapPreviewManifest(payload, manifestUrl);
  } catch (error) {
    if (error instanceof PreviewManifestError) throw error;
    throw new PreviewManifestError(
      "invalid_manifest",
      "preview manifest does not match the supported shape",
      response.status,
    );
  }
}

export function mapPreviewManifest(
  payload: unknown,
  manifestUrl = getPreviewManifestUrl(),
): PreviewManifestViewModel {
  const root = toRecord(payload);
  if (root === null) {
    throw new PreviewManifestError(
      "invalid_manifest",
      "preview manifest must be an object",
    );
  }

  const packageRecord =
    readRecord(root, "material_package") ??
    readRecord(root, "materialPackage") ??
    readRecord(root, "package") ??
    readRecord(root, "result");
  const baseUrl =
    resolveHttpUrl(manifestUrl, getDocumentBaseUrl()) ?? manifestUrl;
  const schemaVersion =
    readString(root, "schema_version") ??
    readString(root, "schemaVersion") ??
    "preview-manifest-v1";
  const topicRecord =
    readRecord(root, "topic") ??
    readRecord(root, "top1") ??
    readRecord(root, "selection") ??
    readRecord(packageRecord, "topic") ??
    emptyRecord;
  const copyRecord =
    readRecord(root, "copy") ??
    readRecord(root, "copywriting") ??
    readRecord(packageRecord, "copy") ??
    emptyRecord;
  const imageRecord =
    readRecord(root, "image") ??
    readRecord(packageRecord, "image") ??
    emptyRecord;
  const validationRecord =
    readRecord(root, "validation") ??
    readRecord(copyRecord, "validation") ??
    readRecord(packageRecord, "validation") ??
    emptyRecord;
  const auditRecord =
    readRecord(root, "audit") ??
    readRecord(copyRecord, "audit") ??
    readRecord(packageRecord, "audit") ??
    emptyRecord;
  const runId =
    readString(root, "run_id") ??
    readString(root, "pipeline_run_id") ??
    readString(packageRecord, "run_id") ??
    readString(packageRecord, "copy_generation_run_id") ??
    "preview-unknown";
  const businessDate =
    readString(root, "business_date") ??
    readString(packageRecord, "business_date");
  const generatedAt =
    readString(root, "generated_at") ??
    readString(root, "created_at") ??
    readString(packageRecord, "created_at");
  const topic = parseTopic(topicRecord);
  const sources = parseSources(
    root,
    packageRecord,
    topic.selectedSourceId,
    baseUrl,
  );
  const copy = parseCopy(copyRecord, root);
  const validation = parseQuality(validationRecord, "validation");
  const audit = parseQuality(auditRecord, "audit");
  const image = parseImage(imageRecord, root, topic.title, runId, baseUrl);
  const stages = parseStages(root, packageRecord);
  const brandBindings = parseBrandBindings(root, packageRecord, copyRecord);
  const findings = parseFindings(
    root,
    packageRecord,
    validationRecord,
    auditRecord,
    image,
  );
  const explicitStatus = normalizeStatus(
    readString(root, "status") ??
      readString(root, "run_status") ??
      readString(packageRecord, "status"),
  );
  const errorRecord = firstRecord(
    readUnknown(root, "error") ?? readUnknown(packageRecord, "error"),
  );
  const errorCode =
    readString(root, "error_code") ??
    readString(errorRecord, "code") ??
    readString(packageRecord, "error_code");
  const errorMessage =
    readString(root, "error_message") ??
    readString(errorRecord, "message") ??
    readString(packageRecord, "error_message");
  const status = resolvePreviewStatus({
    explicitStatus,
    topic,
    image,
    stages,
    validation: validation.status,
    audit: audit.status,
    hasContent:
      copy.copywriting.length > 0 ||
      sources.length > 0 ||
      image.url !== null ||
      stages.some((stage) => stage.status !== "unknown"),
  });

  return {
    schemaVersion,
    runId,
    status,
    statusLabel: previewStatusLabels[status],
    generatedAt,
    generatedAtLabel: formatDateTime(generatedAt),
    businessDate,
    stages,
    sources,
    topic,
    copy,
    validation,
    audit,
    image,
    brandBindings,
    findings,
    errorCode,
    errorMessage,
    downloadPayload: buildDownloadPayload({
      schemaVersion,
      runId,
      status,
      generatedAt,
      businessDate,
      stages,
      sources,
      topic,
      copy,
      validation,
      audit,
      image,
      brandBindings,
      findings,
      errorCode,
      errorMessage,
    }),
  };
}

type StatusResolutionInput = Readonly<{
  explicitStatus: string | null;
  topic: PreviewTopicViewModel;
  image: PreviewImageViewModel;
  stages: readonly PreviewStageViewModel[];
  validation: PreviewQualityViewModel["status"];
  audit: PreviewQualityViewModel["status"];
  hasContent: boolean;
}>;

function resolvePreviewStatus(input: StatusResolutionInput): PreviewStatus {
  const { explicitStatus } = input;
  if (explicitStatus === "no_topic" || input.topic.decision === "no_topic") {
    return "no_topic";
  }
  if (
    explicitStatus === "cancelled" ||
    input.stages.some((stage) => stage.status === "cancelled")
  ) {
    return "cancelled";
  }
  if (
    explicitStatus === "failed" ||
    input.image.status === "failed" ||
    input.stages.some((stage) => stage.status === "failed")
  ) {
    return "failed";
  }
  if (
    explicitStatus === "review_required" ||
    input.image.status === "review_required" ||
    input.validation === "failed" ||
    input.audit === "failed" ||
    input.audit === "pending"
  ) {
    return "review_required";
  }
  if (
    explicitStatus === "queued" ||
    explicitStatus === "running" ||
    explicitStatus === "pending"
  ) {
    return "loading";
  }
  if (
    explicitStatus === "ready" ||
    explicitStatus === "accepted" ||
    explicitStatus === "completed" ||
    explicitStatus === "awaiting_manual_use" ||
    explicitStatus === "succeeded"
  ) {
    return "ready";
  }
  if (!input.hasContent) return "empty";
  if (input.image.status === "pending") return "loading";
  if (input.topic.decision === "selected" || input.image.url !== null)
    return "ready";
  return "unknown";
}

function parseTopic(record: ManifestRecord): PreviewTopicViewModel {
  const decision = normalizeDecision(
    readString(record, "decision_kind") ??
      readString(record, "decision") ??
      readString(record, "outcome") ??
      readString(record, "status"),
  );
  const score =
    readNumber(record, "score") ??
    readNumber(record, "selection_score") ??
    readNumber(record, "total_score");
  return {
    title:
      readString(record, "title") ??
      readString(record, "topic_title") ??
      readString(record, "name") ??
      "未提供选题",
    summary:
      readString(record, "summary") ?? readString(record, "topic_summary"),
    category:
      readString(record, "category") ?? readString(record, "category_label"),
    sourceTrust:
      readString(record, "source_trust") ??
      readString(record, "source_trust_label"),
    decision,
    decisionLabel:
      decision === "selected"
        ? "Top 1 已选中"
        : decision === "no_topic"
          ? "未达到选题门槛"
          : "选题状态未说明",
    explanation:
      readString(record, "selection_explanation") ??
      readString(record, "selection_reason") ??
      readString(record, "explanation") ??
      "未提供 Top 1 选择解释。",
    score,
    scoreLabel: score === null ? "未提供" : String(score),
    selectedSourceId:
      readString(record, "selected_source_id") ??
      readString(record, "selected_candidate_id") ??
      readString(record, "candidate_id"),
  };
}

function parseSources(
  root: ManifestRecord,
  packageRecord: ManifestRecord | null,
  selectedSourceId: string | null,
  baseUrl: string,
): readonly PreviewSourceViewModel[] {
  const acquisition =
    readRecord(root, "acquisition") ?? readRecord(packageRecord, "acquisition");
  const rawSources =
    firstArray(root, [
      "sources",
      "candidates",
      "education_news",
      "news_candidates",
    ]) ??
    firstArray(acquisition, ["sources", "candidates", "education_news"]) ??
    firstArray(packageRecord, ["sources", "candidates"]);
  if (rawSources === null) return [];
  return rawSources.flatMap((value, index) => {
    const record = toRecord(value);
    if (record === null) return [];
    const id =
      readString(record, "id") ??
      readString(record, "candidate_id") ??
      readString(record, "source_id") ??
      `source-${index + 1}`;
    const rawUrl =
      readString(record, "url") ??
      readString(record, "source_url") ??
      readString(record, "canonical_url");
    const status = normalizeSourceStatus(
      readString(record, "status") ?? readString(record, "eligibility"),
    );
    const title =
      readString(record, "title") ??
      readString(record, "headline") ??
      readString(record, "name") ??
      `教育新闻候选 ${index + 1}`;
    return [
      {
        id,
        title,
        sourceName:
          readString(record, "source_name") ?? readString(record, "publisher"),
        url: rawUrl === null ? null : resolveHttpUrl(rawUrl, baseUrl),
        sourceTier:
          readString(record, "source_tier") ?? readString(record, "tier"),
        publishedAt:
          readString(record, "published_at") ??
          readString(record, "publication_date"),
        publishedAtLabel: formatDateTime(
          readString(record, "published_at") ??
            readString(record, "publication_date"),
        ),
        summary:
          readString(record, "summary") ?? readString(record, "description"),
        status,
        statusLabel: sourceStatusLabel(status),
        isSelected:
          readBoolean(record, "is_selected") === true ||
          readBoolean(record, "selected") === true ||
          id === selectedSourceId,
      },
    ];
  });
}

function parseCopy(
  record: ManifestRecord,
  root: ManifestRecord,
): PreviewCopyViewModel {
  const copywriting =
    readString(record, "copywriting") ??
    readString(record, "text") ??
    readString(record, "content") ??
    readString(root, "copywriting") ??
    "";
  const rawHashtags =
    firstStringArray(record, ["hashtags", "tags", "labels"]) ??
    firstStringArray(root, ["hashtags", "tags"]);
  const hashtags = uniqueStrings(
    (rawHashtags ?? [])
      .map(normalizeHashtag)
      .concat(extractHashtags(copywriting)),
  );
  return {
    copywriting,
    hashtags,
    parentTakeaway:
      readString(record, "parent_takeaway") ??
      readString(record, "takeaway") ??
      readString(record, "parent_summary") ??
      "",
    interaction:
      readString(record, "interaction") ??
      readString(record, "interaction_prompt") ??
      "",
    sourceNote:
      readString(record, "source_note") ??
      readString(record, "evidence_note") ??
      "",
    version:
      readString(record, "version") ??
      readString(record, "draft_version_id") ??
      readString(root, "copy_version"),
  };
}

function parseImage(
  record: ManifestRecord,
  root: ManifestRecord,
  topicTitle: string,
  runId: string,
  baseUrl: string,
): PreviewImageViewModel {
  const inputFilename =
    readString(record, "filename") ?? readString(record, "file_name");
  const rootImage = readString(root, "image");
  const rawUrl =
    readString(record, "url") ??
    readString(record, "image_url") ??
    readString(record, "preview_url") ??
    readString(record, "download_url") ??
    readString(root, "image_url") ??
    safeRelativeResource(rootImage) ??
    safeRelativeResource(inputFilename);
  const url = rawUrl === null ? null : resolveImageResourceUrl(rawUrl, baseUrl);
  const rawStatus = normalizeStatus(
    readString(record, "status") ?? readString(root, "image_status"),
  );
  const validationRecord = readRecord(record, "validation") ?? emptyRecord;
  const auditRecord = readRecord(record, "audit") ?? emptyRecord;
  const validation = parseQuality(validationRecord, "validation");
  const audit = parseQuality(auditRecord, "audit");
  const status = resolveImageStatus(rawStatus, url, audit, validation);
  return {
    status,
    statusLabel: imageStatusLabels[status],
    url,
    alt:
      readString(record, "alt") ??
      readString(record, "alt_text") ??
      `${topicTitle}的品牌 IP 预览图片`,
    filename: safePreviewFilename(
      inputFilename ?? `preview-${safeFilenamePart(runId)}.png`,
    ),
    mediaType:
      readString(record, "media_type") ?? readString(record, "content_type"),
    width: readPositiveNumber(record, "width"),
    height: readPositiveNumber(record, "height"),
    byteSize:
      readPositiveNumber(record, "byte_size") ??
      readPositiveNumber(record, "size"),
    validation,
    audit,
  };
}

function resolveImageStatus(
  rawStatus: string | null,
  url: string | null,
  audit: PreviewQualityViewModel,
  validation: PreviewQualityViewModel,
): PreviewImageViewModel["status"] {
  if (rawStatus === "review_required" || audit.status === "failed")
    return "review_required";
  if (rawStatus === "failed" || validation.status === "failed") return "failed";
  if (
    rawStatus === "queued" ||
    rawStatus === "running" ||
    rawStatus === "pending"
  ) {
    return "pending";
  }
  if (rawStatus === "missing") return "missing";
  if (url === null) return rawStatus === null ? "missing" : "unknown";
  if (
    rawStatus === "succeeded" ||
    rawStatus === "accepted" ||
    rawStatus === "ready"
  ) {
    return "ready";
  }
  return "ready";
}

function parseQuality(
  record: ManifestRecord,
  kind: "validation" | "audit",
): PreviewQualityViewModel {
  const passed = readBoolean(record, "passed");
  const accepted = readBoolean(record, "accepted");
  const rawStatus = normalizeStatus(readString(record, "status"));
  const status =
    passed === true ||
    (kind === "audit" && accepted === true) ||
    rawStatus === "accepted"
      ? "passed"
      : passed === false || accepted === false || rawStatus === "rejected"
        ? "failed"
        : kind === "audit" && rawStatus === "not_configured"
          ? "not_configured"
          : passed === null && accepted === null && rawStatus === null
            ? "unknown"
            : "pending";
  return {
    status,
    statusLabel: qualityStatusLabels[status],
    version:
      readString(record, "version") ??
      readString(record, "rule_version") ??
      readString(record, "prompt_version"),
    issueCodes: uniqueStrings(
      (firstStringArray(record, ["issue_codes", "codes"]) ?? []).concat(
        parseIssueCodes(readUnknown(record, "issues")),
      ),
    ),
  };
}

function parseStages(
  root: ManifestRecord,
  packageRecord: ManifestRecord | null,
): readonly PreviewStageViewModel[] {
  const rawStages =
    readUnknown(root, "stages") ??
    readUnknown(root, "pipeline_stages") ??
    readUnknown(packageRecord, "stages");
  const values: readonly [string, unknown][] = Array.isArray(rawStages)
    ? rawStages.map((value, index) => [`stage-${index + 1}`, value] as const)
    : toRecord(rawStages) === null
      ? []
      : Object.entries(toRecord(rawStages) ?? {});
  if (values.length === 0) {
    return defaultStages(root, packageRecord);
  }
  return values.map(([fallbackId, value], index) => {
    const record = toRecord(value) ?? emptyRecord;
    const rawId =
      readString(record, "id") ??
      readString(record, "key") ??
      readString(record, "stage") ??
      fallbackId;
    const id = normalizeStageId(rawId);
    const status = normalizeStageStatus(
      readString(record, "status") ??
        readString(record, "state") ??
        (typeof value === "string" ? value : null),
    );
    return {
      id: `${id || "stage"}-${index + 1}`,
      label:
        readString(record, "label") ??
        readString(record, "name") ??
        stageLabels[id] ??
        humanizeStageId(id),
      status,
      statusLabel: stageStatusLabels[status],
      runId: readString(record, "run_id") ?? readString(record, "job_id"),
      version:
        readString(record, "version") ??
        readString(record, "stage_version") ??
        readString(record, "rule_version"),
      startedAt:
        readString(record, "started_at") ?? readString(record, "startedAt"),
      finishedAt:
        readString(record, "finished_at") ??
        readString(record, "completed_at") ??
        readString(record, "finishedAt"),
      startedAtLabel: formatDateTime(
        readString(record, "started_at") ?? readString(record, "startedAt"),
      ),
      finishedAtLabel: formatDateTime(
        readString(record, "finished_at") ??
          readString(record, "completed_at") ??
          readString(record, "finishedAt"),
      ),
      errorCode: readString(record, "error_code"),
      errorMessage:
        readString(record, "error_message") ?? readString(record, "message"),
    };
  });
}

function defaultStages(
  root: ManifestRecord,
  packageRecord: ManifestRecord | null,
): readonly PreviewStageViewModel[] {
  const statusRecord =
    readRecord(root, "stage_statuses") ??
    readRecord(packageRecord, "stage_statuses");
  const stageDefinitions = [
    ["acquisition", "权威来源采集"],
    ["governance", "事实治理"],
    ["topic_selection", "Top 1 选题"],
    ["copy_generation", "朋友圈文案生成"],
    ["material_package", "品牌视觉与素材包"],
  ] as const satisfies readonly (readonly [string, string])[];
  return stageDefinitions.map(([id, label], index) => {
    const status = normalizeStageStatus(readString(statusRecord, id));
    return {
      id: `${id}-${index + 1}`,
      label,
      status,
      statusLabel: stageStatusLabels[status],
      runId: null,
      version: null,
      startedAt: null,
      finishedAt: null,
      startedAtLabel: "未记录",
      finishedAtLabel: "未记录",
      errorCode: null,
      errorMessage: null,
    };
  });
}

function parseBrandBindings(
  root: ManifestRecord,
  packageRecord: ManifestRecord | null,
  copyRecord: ManifestRecord,
): readonly PreviewBrandBindingViewModel[] {
  const values = [
    readUnknown(root, "brand_bindings"),
    readUnknown(packageRecord, "brand_bindings"),
    readUnknown(copyRecord, "brand_bindings"),
    readUnknown(root, "brand_context"),
  ];
  const seen = new Set<string>();
  const bindings: PreviewBrandBindingViewModel[] = [];
  values.forEach((value) => {
    if (!Array.isArray(value)) return;
    value.forEach((item, index) => {
      const record = toRecord(item);
      if (record === null) return;
      const id =
        readString(record, "id") ??
        readString(record, "brand_chunk_id") ??
        `brand-binding-${index + 1}`;
      if (seen.has(id)) return;
      seen.add(id);
      bindings.push({
        id,
        title:
          readString(record, "document_title") ??
          readString(record, "title") ??
          "赛先生品牌视觉资料",
        role: readString(record, "role") ?? readString(record, "audience"),
        reason:
          readString(record, "selection_reason") ??
          readString(record, "reason") ??
          readString(record, "text"),
        tags: uniqueStrings(
          (
            firstStringArray(record, ["tone_tags", "safety_tags", "tags"]) ?? []
          ).map((tag) => tag),
        ),
      });
    });
  });
  return bindings;
}

function parseFindings(
  root: ManifestRecord,
  packageRecord: ManifestRecord | null,
  validationRecord: ManifestRecord,
  auditRecord: ManifestRecord,
  image: PreviewImageViewModel,
): readonly PreviewFindingViewModel[] {
  const findings: PreviewFindingViewModel[] = [];
  const add = (
    value: unknown,
    stage: string,
    fallbackSeverity: PreviewIssueSeverity,
  ) => {
    if (!Array.isArray(value)) return;
    value.forEach((item, index) => {
      const record = toRecord(item);
      if (record === null && typeof item !== "string") return;
      const message =
        typeof item === "string"
          ? item
          : (readString(record, "message") ??
            readString(record, "detail") ??
            readString(record, "code") ??
            "未提供问题说明");
      const code =
        typeof item === "string"
          ? item
          : (readString(record, "code") ??
            readString(record, "issue_code") ??
            "unclassified");
      const severity =
        normalizeSeverity(readString(record, "severity")) ?? fallbackSeverity;
      const id = `${stage}-${code}-${index + 1}`;
      if (findings.some((finding) => finding.id === id)) return;
      findings.push({
        id,
        stage,
        severity,
        code,
        message,
        field: readString(record, "field"),
      });
    });
  };

  add(readUnknown(root, "findings"), "pipeline", "warning");
  add(readUnknown(root, "issues"), "pipeline", "warning");
  add(readUnknown(validationRecord, "issues"), "验证", "error");
  add(readUnknown(auditRecord, "issues"), "审计", "warning");
  add(readUnknown(packageRecord, "issues"), "素材包", "warning");
  add(
    image.validation.issueCodes.map((code) => ({
      code,
      message: code,
      severity: "error",
    })),
    "图片验证",
    "error",
  );
  add(
    image.audit.issueCodes.map((code) => ({
      code,
      message: code,
      severity: "warning",
    })),
    "图片审计",
    "warning",
  );
  return findings;
}

function buildDownloadPayload(
  input: Readonly<{
    schemaVersion: string;
    runId: string;
    status: PreviewStatus;
    generatedAt: string | null;
    businessDate: string | null;
    stages: readonly PreviewStageViewModel[];
    sources: readonly PreviewSourceViewModel[];
    topic: PreviewTopicViewModel;
    copy: PreviewCopyViewModel;
    validation: PreviewQualityViewModel;
    audit: PreviewQualityViewModel;
    image: PreviewImageViewModel;
    brandBindings: readonly PreviewBrandBindingViewModel[];
    findings: readonly PreviewFindingViewModel[];
    errorCode: string | null;
    errorMessage: string | null;
  }>,
): Readonly<Record<string, unknown>> {
  return {
    schema_version: input.schemaVersion,
    run_id: input.runId,
    status: input.status,
    generated_at: input.generatedAt,
    business_date: input.businessDate,
    stages: input.stages.map((stage) => ({
      id: stage.id,
      label: stage.label,
      status: stage.status,
      status_label: stage.statusLabel,
      run_id: stage.runId,
      version: stage.version,
      started_at: stage.startedAt,
      finished_at: stage.finishedAt,
      error_code: stage.errorCode,
      error_message: stage.errorMessage,
    })),
    topic: {
      title: input.topic.title,
      summary: input.topic.summary,
      category: input.topic.category,
      source_trust: input.topic.sourceTrust,
      decision: input.topic.decision,
      explanation: input.topic.explanation,
      score: input.topic.score,
      selected_source_id: input.topic.selectedSourceId,
    },
    copy: {
      copywriting: input.copy.copywriting,
      hashtags: input.copy.hashtags,
      parent_takeaway: input.copy.parentTakeaway,
      interaction: input.copy.interaction,
      source_note: input.copy.sourceNote,
      version: input.copy.version,
    },
    validation: {
      status: input.validation.status,
      version: input.validation.version,
      issue_codes: input.validation.issueCodes,
    },
    audit: {
      status: input.audit.status,
      version: input.audit.version,
      issue_codes: input.audit.issueCodes,
    },
    sources: input.sources.map((source) => ({
      id: source.id,
      title: source.title,
      source_name: source.sourceName,
      url: source.url,
      source_tier: source.sourceTier,
      published_at: source.publishedAt,
      status: source.status,
      is_selected: source.isSelected,
    })),
    brand_bindings: input.brandBindings.map((binding) => ({
      id: binding.id,
      title: binding.title,
      role: binding.role,
      reason: binding.reason,
      tags: binding.tags,
    })),
    image: {
      filename: input.image.filename,
      status: input.image.status,
      media_type: input.image.mediaType,
      width: input.image.width,
      height: input.image.height,
      byte_size: input.image.byteSize,
      validation: {
        status: input.image.validation.status,
        version: input.image.validation.version,
        issue_codes: input.image.validation.issueCodes,
      },
      audit: {
        status: input.image.audit.status,
        version: input.image.audit.version,
        issue_codes: input.image.audit.issueCodes,
      },
    },
    findings: input.findings.map((finding) => ({
      stage: finding.stage,
      severity: finding.severity,
      code: finding.code,
      message: finding.message,
      field: finding.field,
    })),
    error: {
      code: input.errorCode,
      message: input.errorMessage,
    },
  };
}

function readUnknown(record: ManifestRecord | null, key: string): unknown {
  return record?.[key];
}

function readRecord(
  record: ManifestRecord | null,
  key: string,
): ManifestRecord | null {
  return toRecord(readUnknown(record, key));
}

function firstRecord(value: unknown): ManifestRecord | null {
  return toRecord(value);
}

function toRecord(value: unknown): ManifestRecord | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as ManifestRecord;
}

function isUnknownArray(value: unknown): value is readonly unknown[] {
  return Array.isArray(value);
}

function readString(record: ManifestRecord | null, key: string): string | null {
  const value = readUnknown(record, key);
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : null;
}

function readBoolean(
  record: ManifestRecord | null,
  key: string,
): boolean | null {
  const value = readUnknown(record, key);
  return typeof value === "boolean" ? value : null;
}

function readNumber(record: ManifestRecord | null, key: string): number | null {
  const value = readUnknown(record, key);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readPositiveNumber(
  record: ManifestRecord | null,
  key: string,
): number | null {
  const value = readNumber(record, key);
  return value !== null && value >= 0 ? value : null;
}

function readStringArray(
  record: ManifestRecord | null,
  key: string,
): readonly string[] {
  const value = readUnknown(record, key);
  return Array.isArray(value)
    ? value.filter(
        (item): item is string =>
          typeof item === "string" && item.trim().length > 0,
      )
    : [];
}

function firstStringArray(
  record: ManifestRecord | null,
  keys: readonly string[],
): readonly string[] | null {
  for (const key of keys) {
    const values = readStringArray(record, key);
    if (values.length > 0) return values;
  }
  return null;
}

function firstArray(
  record: ManifestRecord | null,
  keys: readonly string[],
): readonly unknown[] | null {
  for (const key of keys) {
    const value = readUnknown(record, key);
    if (isUnknownArray(value)) return value;
  }
  return null;
}

function normalizeStatus(value: string | null): string | null {
  return value === null
    ? null
    : value.trim().toLowerCase().replace(/[ -]/g, "_");
}

function normalizeDecision(
  value: string | null,
): PreviewTopicViewModel["decision"] {
  if (
    value === "selected" ||
    value === "accepted" ||
    value === "top_1" ||
    value === "top1"
  ) {
    return "selected";
  }
  if (
    value === "no_topic" ||
    value === "no_candidate" ||
    value === "no_selection"
  ) {
    return "no_topic";
  }
  return "unknown";
}

function normalizeStageId(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_");
}

function normalizeStageStatus(value: string | null): PreviewStageStatus {
  const status = normalizeStatus(value);
  if (status === "queued" || status === "pending" || status === "not_started")
    return "queued";
  if (status === "running" || status === "in_progress") return "running";
  if (
    status === "completed" ||
    status === "succeeded" ||
    status === "accepted" ||
    status === "done"
  ) {
    return "completed";
  }
  if (status === "failed" || status === "error") return "failed";
  if (status === "review_required" || status === "review")
    return "review_required";
  if (status === "no_topic") return "no_topic";
  if (status === "cancelled" || status === "canceled") return "cancelled";
  if (status === "skipped") return "skipped";
  return "unknown";
}

function normalizeSourceStatus(value: string | null): string | null {
  return value === null ? null : value.replace(/_/g, " ");
}

function sourceStatusLabel(value: string | null): string {
  if (value === null) return "已采集";
  if (value === "selected") return "已进入 Top 1";
  if (value === "relevant") return "相关候选";
  if (value === "rejected") return "未入选";
  return value;
}

function normalizeSeverity(value: string | null): PreviewIssueSeverity | null {
  if (value === "info" || value === "warning" || value === "error")
    return value;
  return null;
}

function parseIssueCodes(value: unknown): readonly string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string") return [item];
    const record = toRecord(item);
    const code = readString(record, "code") ?? readString(record, "issue_code");
    return code === null ? [] : [code];
  });
}

function normalizeHashtag(value: string): string {
  const trimmed = value.trim();
  return trimmed.startsWith("#") ? trimmed : `#${trimmed}`;
}

function extractHashtags(value: string): readonly string[] {
  return value.match(/#[^\s#，。！？,.!?]+/g) ?? [];
}

function uniqueStrings(values: readonly string[]): readonly string[] {
  return [...new Set(values.filter((value) => value.trim().length > 0))];
}

function resolveHttpUrl(value: string, baseUrl: string): string | null {
  try {
    const url = new URL(value, baseUrl);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

function resolveImageResourceUrl(
  value: string,
  baseUrl: string,
): string | null {
  const resolved = resolveHttpUrl(value, baseUrl);
  if (resolved === null) return null;
  try {
    const url = new URL(resolved);
    return url.search.length === 0 && url.hash.length === 0
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

function getDocumentBaseUrl(): string {
  return typeof window === "undefined"
    ? "http://localhost/"
    : window.location.href;
}

function formatDateTime(value: string | null): string {
  if (value === null) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function humanizeStageId(value: string): string {
  return (
    value
      .split("_")
      .filter((part) => part.length > 0)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ") || "处理阶段"
  );
}

function safeFilenamePart(value: string): string {
  const safe = value.replace(/[^a-zA-Z0-9._-]+/g, "-");
  return safe.length > 0 ? safe : "latest";
}

function safePreviewFilename(value: string): string {
  const basename = value.split(/[\\/]/).at(-1) ?? value;
  return safeFilenamePart(basename);
}

function safeRelativeResource(value: string | null): string | null {
  if (
    value === null ||
    value.startsWith("/") ||
    value.includes("\\") ||
    value.includes("?") ||
    value.includes("#") ||
    value.split("/").some((part) => part === "..") ||
    /^[a-z][a-z\d+.-]*:/i.test(value)
  ) {
    return null;
  }
  return value;
}

const emptyRecord: ManifestRecord = {};
