import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentWorkbenchRunResponse } from "./api";
import {
  AgentWorkbenchClientError,
  mapAgentWorkbenchRun,
  resolveHttpsCitationUrl,
  runAgentWorkbench,
} from "./api";

function withFixtureUserinfo(value: string): string {
  const url = new URL(value);
  url.username = "fixture-user";
  return url.href;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const response = {
  run_id: "00000000-0000-4000-8000-000000000901",
  status: "completed",
  summary: "公开证据支持事件事实，品牌资料只用于表达。",
  claims: [
    {
      text: "教育主管部门发布了公开说明。",
      kind: "external_fact",
      citation_ids: ["evidence-1"],
    },
    {
      text: "家长沟通应准确、克制。",
      kind: "brand_statement",
      citation_ids: ["brand-1"],
    },
  ],
  citations: [
    {
      id: "evidence-1",
      kind: "evidence",
      source_name: "教育主管部门",
      title: "人工智能教育应用公开说明",
      url: "https://example.edu.cn/policy/ai-education",
      evidence_eligible: true,
    },
    {
      id: "brand-1",
      kind: "brand_context",
      source_name: "脱敏品牌规范",
      title: "家长沟通语气",
      url: null,
      evidence_eligible: false,
    },
    {
      id: "unused-evidence",
      kind: "evidence",
      source_name: "未使用来源",
      title: "不应进入引用目录",
      url: "https://example.edu.cn/unused",
      evidence_eligible: true,
    },
  ],
  steps: [
    {
      ordinal: 1,
      kind: "model_decision",
      status: "succeeded",
      code: null,
      tool_name: null,
      call_id: null,
      argument_summary: {},
      duration_ms: 42,
      item_count: null,
      issue_count: null,
      citation_ids: [],
      provider: "deterministic",
      model: "offline-policy-v1",
      prompt_tokens: 100,
      completion_tokens: 0,
      reasoning_tokens: 0,
    },
    {
      ordinal: 2,
      kind: "tool_call",
      status: "succeeded",
      code: null,
      tool_name: "search_evidence",
      call_id: "call-1",
      argument_summary: {
        query_length: 18,
        query_hash: "fixture-query-hash",
        limit: 2,
        ignored_unknown_field: "must-not-render",
      },
      duration_ms: 18,
      item_count: 2,
      issue_count: null,
      citation_ids: ["evidence-1"],
      provider: null,
      model: null,
      prompt_tokens: 0,
      completion_tokens: 0,
      reasoning_tokens: 0,
    },
    {
      ordinal: 3,
      kind: "error",
      status: "failed",
      code: "../../private-path",
      tool_name: "unregistered_side_effect_tool",
      call_id: "call-2",
      argument_summary: { argument_bytes: 42 },
      duration_ms: 1,
      item_count: null,
      issue_count: 1,
      citation_ids: [],
      provider: null,
      model: null,
      prompt_tokens: 0,
      completion_tokens: 0,
      reasoning_tokens: 0,
    },
  ],
  metrics: {
    model_turns: 3,
    tool_calls: 2,
    successful_tool_calls: 1,
    prompt_tokens: 228,
    completion_tokens: 96,
    reasoning_tokens: 0,
    model_latency_ms: 279,
    tool_latency_ms: 19,
    duration_ms: 315,
  },
  error_code: null,
} satisfies AgentWorkbenchRunResponse;

describe("mapAgentWorkbenchRun", () => {
  it("maps the generated wire contract into a bounded claim-used view", () => {
    const run = mapAgentWorkbenchRun(response);

    expect(run.status).toBe("completed");
    expect(run.claims[0]).toMatchObject({
      kindLabel: "外部事实",
      citationIds: ["evidence-1"],
    });
    expect(run.citations.map((citation) => citation.id)).toEqual([
      "evidence-1",
      "brand-1",
    ]);
    expect(run.citations[0]?.url).toBe(
      "https://example.edu.cn/policy/ai-education",
    );
    expect(run.citations[1]).toMatchObject({
      url: null,
      evidenceEligible: false,
      kindLabel: "品牌上下文",
    });
    expect(run.steps[1]?.details).toEqual(
      expect.arrayContaining([
        { label: "查询长度", value: "18" },
        { label: "查询指纹", value: "fixture-query-hash" },
        { label: "结果数量", value: "2 条" },
      ]),
    );
    expect(run.steps[1]?.details).not.toEqual(
      expect.arrayContaining([
        { label: "ignored_unknown_field", value: "must-not-render" },
      ]),
    );
    expect(run.steps[2]).toMatchObject({
      toolLabel: "未注册工具",
      code: "agent_trace_unknown",
    });
    expect(run.metrics).toMatchObject({
      modelSteps: 3,
      successfulToolCalls: 1,
      inputTokens: 228,
      outputTokens: 96,
      reasoningTokens: 0,
    });
  });

  it("does not invent token use when the adapter supplied no usage", () => {
    const run = mapAgentWorkbenchRun({
      ...response,
      metrics: {
        ...response.metrics,
        prompt_tokens: 0,
        completion_tokens: 0,
        reasoning_tokens: 0,
      },
    });

    expect(run.metrics).toMatchObject({
      inputTokens: null,
      outputTokens: null,
      reasoningTokens: null,
    });
  });

  it("removes unresolved claim references and unsafe evidence links", () => {
    const evidenceCitation = response.citations[0];
    if (evidenceCitation === undefined) {
      throw new Error("evidence citation fixture is missing");
    }
    const run = mapAgentWorkbenchRun({
      ...response,
      claims: [
        {
          text: "引用不存在的声明不会获得可点击脚注。",
          kind: "external_fact",
          citation_ids: ["missing-citation", "evidence-1"],
        },
      ],
      citations: [
        {
          ...evidenceCitation,
          url: "https://127.0.0.1/private-object",
        },
      ],
    });

    expect(run.claims[0]?.citationIds).toEqual(["evidence-1"]);
    expect(run.citations[0]?.url).toBeNull();
  });
});

describe("resolveHttpsCitationUrl", () => {
  it.each([
    "http://example.edu.cn/source",
    "https://localhost/source",
    "https://news.local/source",
    "https://intranet/source",
    "https://resolver.home.arpa/source",
    "https://0.0.0.0/source",
    "https://127.0.0.1/source",
    "https://2130706433/source",
    "https://0x7f000001/source",
    "https://10.0.0.8/source",
    "https://100.64.0.1/source",
    "https://169.254.1.1/source",
    "https://172.16.0.1/source",
    "https://192.0.2.1/source",
    "https://192.168.1.8/source",
    "https://198.18.0.1/source",
    "https://198.51.100.1/source",
    "https://203.0.113.1/source",
    "https://224.0.0.1/source",
    "https://255.255.255.255/source",
    "https://[::]/source",
    "https://[::1]/source",
    "https://[fc00::1]/source",
    "https://[fe80::1]/source",
    "https://[ff02::1]/source",
    "https://[2001:2::1]/source",
    "https://[2001:20::1]/source",
    "https://[2001:db8::1]/source",
    "https://[2002::1]/source",
    "https://[3fff::1]/source",
    withFixtureUserinfo("https://example.edu.cn/source"),
    "https://example.edu.cn/source#private-fragment",
    "javascript:alert(1)",
  ])("rejects non-public citation URL %s", (url) => {
    expect(resolveHttpsCitationUrl(url)).toBeNull();
  });

  it.each([
    "https://example.edu.cn/source",
    "https://8.8.8.8/source",
    "https://[2606:4700:4700::1111]/source",
  ])("accepts canonical public HTTPS URL %s", (url) => {
    expect(resolveHttpsCitationUrl(url)).toBe(url);
  });
});

describe("runAgentWorkbench", () => {
  it("posts only the bounded query to the fixed local endpoint", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const request =
        input instanceof Request ? input : new Request(input, init);
      expect(request.url).toBe(
        "http://127.0.0.1:8010/api/v1/agent-workbench/runs",
      );
      expect(request.method).toBe("POST");
      expect(await request.clone().json()).toEqual({ query: "核验公开证据" });
      return new Response(JSON.stringify(response), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const run = await runAgentWorkbench("核验公开证据");

    expect(run.runId).toBe(response.run_id);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("projects HTTP failures without exposing a provider body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              raw_provider_body: "must-not-be-projected",
              detail: "private detail",
            }),
            {
              status: 403,
              headers: {
                "content-type": "application/json",
                "x-request-id": "safe-request-1",
              },
            },
          ),
        ),
      ),
    );

    const failure = await runAgentWorkbench("非回环请求").catch(
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(AgentWorkbenchClientError);
    expect(failure).toMatchObject({
      code: "agent_workbench_loopback_required",
      httpStatus: 403,
      requestId: "safe-request-1",
      message: "agent_workbench_loopback_required",
    });
    expect(JSON.stringify(failure)).not.toContain("private detail");
  });

  it("preserves caller cancellation and safely types network failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.reject(new DOMException("cancelled", "AbortError")),
      ),
    );
    await expect(runAgentWorkbench("取消请求")).rejects.toMatchObject({
      name: "AbortError",
    });

    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.reject(new Error("socket detail"))),
    );
    await expect(runAgentWorkbench("网络失败")).rejects.toMatchObject({
      code: "agent_workbench_network_error",
      message: "agent_workbench_network_error",
    });
  });
});

export { response as agentWorkbenchResponseFixture };
