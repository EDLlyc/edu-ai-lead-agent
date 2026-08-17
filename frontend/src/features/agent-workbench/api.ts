import createClient from "openapi-fetch";

import type {
  components,
  paths,
} from "@/lib/api/generated/agent-workbench-schema";

import { getAgentWorkbenchApiBaseUrl } from "./config";
import type {
  AgentWorkbenchCitationViewModel,
  AgentWorkbenchRunViewModel,
  AgentWorkbenchTraceDetailViewModel,
} from "./view-model";

export type AgentWorkbenchRunRequest =
  components["schemas"]["AgentWorkbenchRunRequest"];
export type AgentWorkbenchRunResponse =
  components["schemas"]["AgentWorkbenchRunResponse"];
type AgentTraceStepResponse = components["schemas"]["AgentTraceStepResponse"];
type AgentTraceValue = AgentTraceStepResponse["argument_summary"][string];

export type AgentWorkbenchExecutor = (
  query: string,
  signal?: AbortSignal,
) => Promise<AgentWorkbenchRunViewModel>;

export type AgentWorkbenchClientErrorCode =
  | "agent_workbench_disabled"
  | "agent_workbench_loopback_required"
  | "agent_workbench_invalid_request"
  | "agent_workbench_unavailable"
  | "agent_workbench_network_error"
  | "agent_workbench_invalid_base_url";

export class AgentWorkbenchClientError extends Error {
  readonly code: AgentWorkbenchClientErrorCode;
  readonly httpStatus: number | null;
  readonly requestId: string | null;

  constructor(
    code: AgentWorkbenchClientErrorCode,
    httpStatus: number | null = null,
    requestId: string | null = null,
  ) {
    super(code);
    this.name = "AgentWorkbenchClientError";
    this.code = code;
    this.httpStatus = httpStatus;
    this.requestId = requestId;
  }
}

export const runAgentWorkbench: AgentWorkbenchExecutor = async (
  query,
  signal,
) => {
  let baseUrl: string;
  try {
    baseUrl = getAgentWorkbenchApiBaseUrl();
  } catch {
    throw new AgentWorkbenchClientError("agent_workbench_invalid_base_url");
  }

  const client = createClient<paths>({ baseUrl });
  try {
    const response = await client.POST("/api/v1/agent-workbench/runs", {
      body: { query },
      ...(signal === undefined ? {} : { signal }),
    });
    if (response.data === undefined) {
      throw new AgentWorkbenchClientError(
        errorCodeForStatus(response.response.status),
        response.response.status,
        readSafeRequestId(response.response),
      );
    }
    return mapAgentWorkbenchRun(response.data);
  } catch (error) {
    if (error instanceof AgentWorkbenchClientError) throw error;
    if (isAbortError(error)) throw error;
    throw new AgentWorkbenchClientError("agent_workbench_network_error");
  }
};

export function mapAgentWorkbenchRun(
  response: AgentWorkbenchRunResponse,
): AgentWorkbenchRunViewModel {
  const usedCitationIds = new Set(
    response.claims.flatMap((claim) => claim.citation_ids),
  );
  const seenCitationIds = new Set<string>();
  const citations: AgentWorkbenchCitationViewModel[] = [];
  for (const citation of response.citations) {
    if (!usedCitationIds.has(citation.id) || seenCitationIds.has(citation.id)) {
      continue;
    }
    seenCitationIds.add(citation.id);
    citations.push({
      id: citation.id,
      kind: citation.kind,
      kindLabel: citationKindLabel(citation.kind),
      sourceName: citation.source_name,
      title: citation.title,
      url:
        citation.kind === "evidence" && citation.evidence_eligible
          ? resolveHttpsCitationUrl(citation.url)
          : null,
      evidenceEligible:
        citation.kind === "evidence" && citation.evidence_eligible,
    });
  }

  const catalogIds = new Set(citations.map((citation) => citation.id));
  const hasTokenUsage =
    response.metrics.prompt_tokens +
      response.metrics.completion_tokens +
      response.metrics.reasoning_tokens >
    0;

  return {
    runId: response.run_id,
    status: runStatus(response.status),
    statusLabel: runStatusLabel(response.status),
    summary: response.summary,
    claims: response.claims.map((claim, index) => ({
      id: `claim-${index + 1}`,
      text: claim.text,
      kind: claim.kind,
      kindLabel: claimKindLabel(claim.kind),
      citationIds: claim.citation_ids.filter((citationId) =>
        catalogIds.has(citationId),
      ),
    })),
    citations,
    steps: response.steps.map((step, index) => {
      const code = step.code ?? null;
      const toolName = step.tool_name ?? null;
      return {
        id: `step-${step.ordinal}-${index + 1}`,
        ordinal: step.ordinal,
        kind: step.kind,
        kindLabel: traceKindLabel(step.kind),
        status: step.status,
        statusLabel: traceStatusLabel(step.status, code),
        code: safeErrorCode(code),
        toolName,
        toolLabel: toolLabel(toolName),
        displayLabel: traceDisplayLabel(step),
        durationMs: step.duration_ms,
        details: traceDetails(step),
        citationIds: step.citation_ids.flatMap((citationId) =>
          isSafeIdentifier(citationId) ? [citationId] : [],
        ),
      };
    }),
    metrics: {
      modelSteps: response.metrics.model_turns,
      toolCalls: response.metrics.tool_calls,
      successfulToolCalls: response.metrics.successful_tool_calls,
      durationMs: response.metrics.duration_ms,
      modelLatencyMs: response.metrics.model_latency_ms,
      toolLatencyMs: response.metrics.tool_latency_ms,
      inputTokens: hasTokenUsage ? response.metrics.prompt_tokens : null,
      outputTokens: hasTokenUsage ? response.metrics.completion_tokens : null,
      reasoningTokens: hasTokenUsage ? response.metrics.reasoning_tokens : null,
    },
    errorCode: safeErrorCode(response.error_code ?? null),
  };
}

export function resolveHttpsCitationUrl(value: string | null): string | null {
  if (value === null) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      url.username.length === 0 &&
      url.password.length === 0 &&
      url.hash.length === 0 &&
      isPublicCitationHostname(url.hostname)
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

function isPublicCitationHostname(value: string): boolean {
  const hostname = value.toLowerCase().replace(/\.$/u, "");
  const unwrapped =
    hostname.startsWith("[") && hostname.endsWith("]")
      ? hostname.slice(1, -1)
      : hostname;

  if (unwrapped.includes(":")) {
    const segments = unwrapped.split(":");
    const firstSegment = segments[0];
    const secondSegment = segments[1] ?? "";
    if (firstSegment === undefined || firstSegment.length === 0) return false;
    const firstValue = Number.parseInt(firstSegment, 16);
    const secondValue =
      secondSegment.length === 0 ? 0 : Number.parseInt(secondSegment, 16);
    const isIetfProtocolAssignment =
      firstValue === 0x2001 && secondValue <= 0x01ff;
    const isDocumentation =
      (firstValue === 0x2001 && secondValue === 0x0db8) ||
      (firstValue === 0x3fff && secondValue <= 0x0fff);
    const isDeprecatedTransition = firstValue === 0x2002;
    return (
      Number.isInteger(firstValue) &&
      Number.isInteger(secondValue) &&
      firstValue >= 0x2000 &&
      firstValue <= 0x3fff &&
      !isIetfProtocolAssignment &&
      !isDocumentation &&
      !isDeprecatedTransition
    );
  }

  if (/^\d+(?:\.\d+){3}$/u.test(unwrapped)) {
    const octets = unwrapped.split(".").map(Number);
    const first = octets[0];
    const second = octets[1];
    const third = octets[2];
    if (first === undefined || second === undefined || third === undefined)
      return false;
    return !(
      first === 0 ||
      first === 10 ||
      first === 127 ||
      (first === 100 && second >= 64 && second <= 127) ||
      (first === 169 && second === 254) ||
      (first === 172 && second >= 16 && second <= 31) ||
      (first === 192 && second === 0 && (third === 0 || third === 2)) ||
      (first === 192 && second === 88 && third === 99) ||
      (first === 192 && second === 168) ||
      (first === 198 && (second === 18 || second === 19)) ||
      (first === 198 && second === 51 && third === 100) ||
      (first === 203 && second === 0 && third === 113) ||
      first >= 224
    );
  }

  const blockedSuffixes = [
    "localhost",
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".test",
    ".example",
    ".invalid",
    ".home.arpa",
  ];
  return (
    unwrapped.includes(".") &&
    !blockedSuffixes.some((suffix) => unwrapped.endsWith(suffix))
  );
}

function runStatus(value: string): AgentWorkbenchRunViewModel["status"] {
  switch (value) {
    case "completed":
    case "refused":
    case "failed":
    case "cancelled":
      return value;
    case "budget_exhausted":
      return "budget-exhausted";
    default:
      return "failed";
  }
}

function runStatusLabel(value: string): string {
  const labels: Readonly<Record<string, string>> = {
    completed: "分析已完成",
    refused: "请求已安全拒绝",
    budget_exhausted: "步骤预算已用尽",
    failed: "分析安全停止",
    cancelled: "本次请求已取消",
  };
  return labels[value] ?? "状态未识别，已安全停止";
}

function claimKindLabel(value: string): string {
  const labels: Readonly<Record<string, string>> = {
    external_fact: "外部事实",
    brand_statement: "品牌表达",
    opinion: "解释与建议",
  };
  return labels[value] ?? "未分类声明";
}

function citationKindLabel(value: string): string {
  const labels: Readonly<Record<string, string>> = {
    evidence: "事实证据",
    brand_context: "品牌上下文",
  };
  return labels[value] ?? "未分类引用";
}

function traceKindLabel(value: string): string {
  const labels: Readonly<Record<string, string>> = {
    model_decision: "模型决策",
    tool_call: "工具调用",
    tool_result: "工具观察",
    final: "最终输出",
    error: "安全停止",
  };
  return labels[value] ?? "未知步骤";
}

function traceStatusLabel(status: string, code: string | null): string {
  if (status === "succeeded") return "已完成";
  if (status === "failed")
    return code === null ? "未完成" : "未完成 · 查看安全错误码";
  return "状态未识别";
}

function traceDisplayLabel(step: AgentTraceStepResponse): string {
  if (step.kind === "tool_call")
    return step.tool_name === null || step.tool_name === undefined
      ? "准备受控工具调用"
      : `调用：${toolLabel(step.tool_name) ?? "未注册工具"}`;
  if (step.kind === "tool_result")
    return step.tool_name === null || step.tool_name === undefined
      ? "接收受控工具结果"
      : `观察：${toolLabel(step.tool_name) ?? "未注册工具"}`;
  const labels: Readonly<Record<string, string>> = {
    model_decision: "选择下一步安全动作",
    final: "形成引用结论",
    error: "执行已安全停止",
  };
  return labels[step.kind] ?? "未识别步骤";
}

function toolLabel(value: string | null): string | null {
  if (value === null) return null;
  const labels: Readonly<Record<string, string>> = {
    search_evidence: "检索事实证据",
    get_event: "读取事件详情",
    retrieve_brand_context: "召回品牌上下文",
    validate_copy: "验证文案边界",
  };
  return labels[value] ?? "未注册工具";
}

function traceDetails(
  step: AgentTraceStepResponse,
): readonly AgentWorkbenchTraceDetailViewModel[] {
  const argumentLabels: Readonly<Record<string, string>> = {
    argument_bytes: "参数大小",
    query_length: "查询长度",
    query_hash: "查询指纹",
    limit: "请求上限",
    candidate_id: "候选 ID",
    event_id: "事件 ID",
    valid_on: "有效日期",
    audience: "受众",
    document_kinds: "文档类别",
    copy_run_id: "文案运行 ID",
    draft_bytes: "文案大小",
    claim_count: "声明数量",
    brand_chunk_ids: "品牌片段 ID",
  };
  const details: AgentWorkbenchTraceDetailViewModel[] = [];
  for (const [key, value] of Object.entries(step.argument_summary).sort(
    ([left], [right]) => left.localeCompare(right, "en"),
  )) {
    const label = argumentLabels[key];
    if (label === undefined) continue;
    details.push({ label, value: formatTraceValue(value) });
  }
  if (step.item_count !== null && step.item_count !== undefined) {
    details.push({ label: "结果数量", value: `${step.item_count} 条` });
  }
  if (step.issue_count !== null && step.issue_count !== undefined) {
    details.push({ label: "问题数量", value: `${step.issue_count} 条` });
  }
  if (step.provider !== null && step.provider !== undefined) {
    details.push({ label: "适配器", value: boundedLabel(step.provider) });
  }
  if (step.model !== null && step.model !== undefined) {
    details.push({ label: "模型", value: boundedLabel(step.model) });
  }
  const tokenCount =
    step.prompt_tokens + step.completion_tokens + step.reasoning_tokens;
  if (tokenCount > 0) {
    details.push({ label: "Token", value: tokenCount.toLocaleString("zh-CN") });
  }
  return details;
}

function formatTraceValue(value: AgentTraceValue): string {
  if (value === null) return "未提供";
  if (Array.isArray(value)) {
    return value.map((item) => boundedLabel(item)).join("、");
  }
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return value.toLocaleString("zh-CN");
  return boundedLabel(value);
}

function boundedLabel(value: string): string {
  const normalized = value.trim();
  return normalized.length <= 120 ? normalized : `${normalized.slice(0, 117)}…`;
}

function safeErrorCode(value: string | null): string | null {
  if (value === null) return null;
  return /^[a-z][a-z0-9_]{0,79}$/.test(value) ? value : "agent_trace_unknown";
}

function isSafeIdentifier(value: string): boolean {
  return (
    value.length > 0 &&
    value.length <= 80 &&
    Array.from(value).every((character) => {
      const codePoint = character.codePointAt(0);
      return codePoint !== undefined && codePoint >= 32 && codePoint !== 127;
    })
  );
}

function errorCodeForStatus(status: number): AgentWorkbenchClientErrorCode {
  if (status === 404) return "agent_workbench_disabled";
  if (status === 403) return "agent_workbench_loopback_required";
  if (status === 422) return "agent_workbench_invalid_request";
  if (status === 503) return "agent_workbench_unavailable";
  return "agent_workbench_unavailable";
}

function readSafeRequestId(response: Response): string | null {
  const requestId = response.headers.get("x-request-id");
  return requestId !== null &&
    /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(requestId)
    ? requestId
    : null;
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof Error || error instanceof DOMException) &&
    error.name === "AbortError"
  );
}
