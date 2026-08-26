import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";

import type {
  OfficialAccountMediaViewModel,
  OfficialAccountRunDetailViewModel,
  OfficialAccountRunSummaryViewModel,
} from "./api";

const hookMocks = vi.hoisted(() => ({
  fixtureMutate: vi.fn(),
  liveMutate: vi.fn(),
  retryMutate: vi.fn(),
  reviewMutate: vi.fn(),
}));

const run: OfficialAccountRunSummaryViewModel = {
  id: "00000000-0000-4000-8000-000000000001",
  sourceLabel: "脱敏离线样例",
  materialPackageId: null,
  modeLabel: "FIXTURE / 离线",
  providerModel: "fake / official-account-fixture-v1",
  status: "ready",
  statusLabel: "本地草稿就绪",
  stage: "ready",
  stageLabel: "完成",
  attemptCount: 1,
  errorCode: null,
  errorRetryable: false,
  createdAtLabel: "2026/8/21 08:00:00",
  simulation: true,
};

const contextMedia: OfficialAccountMediaViewModel = {
  id: "local-media-context-safe",
  role: "context",
  roleLabel: "新闻原图 01",
  ordinal: 0,
  url: "http://127.0.0.1:8000/context.jpg",
  mediaType: "image/jpeg",
  byteSize: 120,
  sha256: "9".repeat(64),
  semanticLabel: "新闻原图",
  assignedSectionIndex: 0,
  scoreBand: null,
  selectionReasonCode: "evidence_snapshot_lineage_v1",
  selectionMethod: null,
  selectionMethodLabel: null,
  similarityBand: null,
  similarityBandLabel: null,
  altText: "新闻现场中的科学教育活动",
  provenanceKind: "source_news",
  sourcePageUrl: "https://source.example/news/article",
  caption: "新闻现场",
  credit: "来源机构",
  rightsStatus: "publish_permission_unverified",
  contextOnlyNotEvidence: true,
};

const detail: OfficialAccountRunDetailViewModel = {
  summary: run,
  article: {
    title: "<script>只作为标题文本</script>",
    digest: "脱敏摘要",
    author: "赛先生",
    lead: "脱敏导语",
    conclusion: "脱敏结语",
    topic_title: "脱敏选题",
    sections: [
      {
        heading: "第一节",
        blocks: [
          {
            kind: "paragraph",
            text: "模型文本只进入 React 文本节点。",
            claim_refs: ["opinion-1"],
          },
          {
            kind: "image",
            slot_key: "body-0",
            alt_text: "脱敏正文图",
            claim_refs: [],
          },
        ],
      },
    ],
    claims: [
      {
        id: "opinion-1",
        text: "脱敏观点",
        kind: "opinion",
        evidence_ids: [],
        brand_chunk_ids: [],
      },
    ],
    sources: [
      {
        evidence_id: "00000000-0000-4000-8000-000000000010",
        source_url: "https://example.invalid/source",
        source_name: "脱敏来源",
        source_tier: "fixture",
      },
    ],
    media_slots: [
      { role: "body", ordinal: 0, slot_key: "body-0" },
      { role: "cover", ordinal: 0, slot_key: "cover-0" },
    ],
    quality: {
      inherited_copy_validation_passed: true,
      inherited_copy_audit_accepted: true,
      inherited_image_validation_passed: true,
      inherited_image_audit_status: "accepted",
      manual_review_status: "pending",
    },
    versions: {
      generator_prompt_version: "generator-v1",
      article_schema_version: "schema-v1",
      auditor_prompt_version: "auditor-v1",
      audit_schema_version: "audit-schema-v1",
      rule_version: "rules-v1",
      renderer_version: "renderer-v1",
      style_version: "style-v1",
      template_version: "template-v1",
      local_adapter_version: "adapter-v1",
    },
    content_fingerprint: "a".repeat(64),
  },
  validation: { passed: true, issues: [] },
  audit: { accepted: true, issue_codes: [], claim_ids: [] },
  usage: {
    prompt_tokens: 0,
    completion_tokens: 0,
    reasoning_tokens: 0,
    latency_ms: 0,
    safe_provider_request_id: null,
  },
  media: [
    {
      id: "local-media-body-safe",
      role: "body",
      roleLabel: "正文图片 01",
      ordinal: 0,
      url: "http://127.0.0.1:8000/body.png",
      mediaType: "image/png",
      byteSize: 100,
      sha256: "1".repeat(64),
      altText: "第一节观察现象正文块插画",
      semanticLabel: "观察现象",
      assignedSectionIndex: 0,
      scoreBand: "heading",
      selectionReasonCode: "semantic_heading_match",
      selectionMethod: "multimodal_embedding",
      selectionMethodLabel: "多模态语义匹配",
      similarityBand: "high",
      similarityBandLabel: "相似度：高",
      provenanceKind: "generated_visual",
      sourcePageUrl: null,
      caption: null,
      credit: null,
      rightsStatus: null,
      contextOnlyNotEvidence: false,
    },
    {
      id: "local-media-body-safe-1",
      role: "body",
      roleLabel: "正文图片 02",
      ordinal: 1,
      url: "http://127.0.0.1:8000/body-1.png",
      mediaType: "image/png",
      byteSize: 101,
      sha256: "2".repeat(64),
      altText: "第三节动手验证正文块插画",
      semanticLabel: "动手验证",
      assignedSectionIndex: 2,
      scoreBand: "heading",
      selectionReasonCode: "semantic_heading_match",
      selectionMethod: "multimodal_embedding",
      selectionMethodLabel: "多模态语义匹配",
      similarityBand: "medium",
      similarityBandLabel: "相似度：中",
      provenanceKind: "generated_visual",
      sourcePageUrl: null,
      caption: null,
      credit: null,
      rightsStatus: null,
      contextOnlyNotEvidence: false,
    },
    {
      id: "local-media-body-safe-2",
      role: "body",
      roleLabel: "正文图片 03",
      ordinal: 2,
      url: "http://127.0.0.1:8000/body-2.png",
      mediaType: "image/png",
      byteSize: 102,
      sha256: "3".repeat(64),
      altText: "第四节记录复盘正文块插画",
      semanticLabel: "记录复盘",
      assignedSectionIndex: 3,
      scoreBand: "heading",
      selectionReasonCode: "semantic_heading_match",
      selectionMethod: "multimodal_embedding",
      selectionMethodLabel: "多模态语义匹配",
      similarityBand: "high",
      similarityBandLabel: "相似度：高",
      provenanceKind: "generated_visual",
      sourcePageUrl: null,
      caption: null,
      credit: null,
      rightsStatus: null,
      contextOnlyNotEvidence: false,
    },
    {
      id: "local-media-cover-safe",
      role: "cover",
      roleLabel: "封面",
      ordinal: 0,
      url: "http://127.0.0.1:8000/cover.png",
      mediaType: "image/png",
      byteSize: 100,
      sha256: "4".repeat(64),
      altText: null,
      semanticLabel: null,
      assignedSectionIndex: null,
      scoreBand: null,
      selectionReasonCode: null,
      selectionMethod: null,
      selectionMethodLabel: null,
      similarityBand: null,
      similarityBandLabel: null,
      provenanceKind: "image_artifact",
      sourcePageUrl: null,
      caption: null,
      credit: null,
      rightsStatus: null,
      contextOnlyNotEvidence: false,
    },
    contextMedia,
  ],
  bodyImages: [
    {
      id: "local-media-body-safe",
      ordinal: 0,
      url: "http://127.0.0.1:8000/body.png",
      mediaType: "image/png",
      byteSize: 100,
      sha256: "1".repeat(64),
    },
    {
      id: "local-media-body-safe-1",
      ordinal: 1,
      url: "http://127.0.0.1:8000/body-1.png",
      mediaType: "image/png",
      byteSize: 101,
      sha256: "2".repeat(64),
    },
    {
      id: "local-media-body-safe-2",
      ordinal: 2,
      url: "http://127.0.0.1:8000/body-2.png",
      mediaType: "image/png",
      byteSize: 102,
      sha256: "3".repeat(64),
    },
  ],
  contextImages: [contextMedia],
  contextMediaStatus: "partial",
  primaryBodyImageId: "local-media-body-safe",
  coverImageId: "local-media-cover-safe",
  mediaSelection: {
    policyVersion: "official-account-media-plan-v1-deterministic",
    bodyImageCount: 3,
    targetLabel: "3–5 张（候选充足时）",
    safelyDegraded: false,
    explanation: [
      "观察现象：固定测试素材按受治理顺序进入正文",
      "动手验证：固定测试素材按受治理顺序进入正文",
      "记录复盘：固定测试素材按受治理顺序进入正文",
    ],
    mode: "multimodal_embedding",
    modeLabel: "多模态语义匹配",
    semanticStatus: "semantic_ready",
    closedReason: null,
    closedReasonLabel: null,
    visualQueryVersion: "official-account-visual-query-v1",
    visualSelectorVersion:
      "official-account-visual-selector-v3-multimodal-hybrid",
    embeddingIdentity: {
      provider: "alibaba-model-studio",
      model: "qwen3-vl-embedding",
      dimensions: 2048,
      inputPolicyVersion: "brand-visual-embedding-input-v2",
    },
  },
  generatedVisuals: [],
  generatedVisualProgress: { ready: 0, total: 3 },
  draft: {
    id: "local-draft-safe",
    state: "ready",
    previewUrl:
      "http://127.0.0.1:8000/api/v1/official-account-local/drafts/local-draft-safe/preview",
    fingerprint: "b".repeat(64),
    createdAtLabel: "2026/8/21 08:00:02",
  },
  manualReview: {
    status: "pending",
    statusLabel: "等待最终人工审稿",
    reviewId: null,
    reviewerLabel: null,
    note: null,
    reviewedAtLabel: null,
    requestFingerprint: null,
    idempotentReplay: false,
    editoriallyApproved: false,
  },
};

vi.mock("./hooks", () => ({
  useOfficialAccountCapabilities: () => ({
    data: {
      enabled: true,
      fixtureAvailable: true,
      liveAvailable: true,
      liveUnavailableReason: null,
      eligibleMaterials: [
        {
          id: "00000000-0000-4000-8000-000000000099",
          title: "合格素材包",
          status: "ready",
          reviewStatus: "pending",
        },
      ],
      boundaryLabel: "本地模拟，未同步公众号",
      visualSemanticEnabled: false,
      visualSemanticProviderMode: "disabled",
      generatedVisualsEnabled: false,
    },
    isLoading: false,
    isError: false,
  }),
  useOfficialAccountRuns: () => ({
    data: [run],
    isLoading: false,
  }),
  useOfficialAccountRun: () => ({
    data: detail,
    isLoading: false,
    isError: false,
  }),
  useCreateFixtureArticleRun: () => ({
    mutate: hookMocks.fixtureMutate,
    isPending: false,
    error: null,
  }),
  useCreateLiveArticleRun: () => ({
    mutate: hookMocks.liveMutate,
    isPending: false,
    error: null,
  }),
  useRetryOfficialAccountRun: () => ({
    mutate: hookMocks.retryMutate,
    isPending: false,
    error: null,
  }),
  useOfficialAccountManualReview: () => ({
    mutate: hookMocks.reviewMutate,
    isPending: false,
    error: null,
    data: undefined,
    variables: undefined,
  }),
}));

import { OfficialAccountLocalPanel } from "./OfficialAccountLocalPanel";

describe("official-account local workbench", () => {
  it("keeps live and fixture actions explicit and labels the simulation boundary", async () => {
    const user = userEvent.setup();
    render(<OfficialAccountLocalPanel />);

    expect(
      screen.getAllByText("本地模拟，未同步公众号").length,
    ).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "调用模型生成长文" }));
    expect(hookMocks.liveMutate).toHaveBeenCalledWith(
      "00000000-0000-4000-8000-000000000099",
      expect.any(Object),
    );
    await user.click(screen.getByRole("button", { name: "创建离线演示草稿" }));
    expect(hookMocks.fixtureMutate).toHaveBeenCalledWith(
      undefined,
      expect.any(Object),
    );
    expect(screen.queryByRole("button", { name: /发布|群发|登录/ })).toBeNull();
  });

  it("renders model content as text and previews only in a permissionless iframe", () => {
    render(<OfficialAccountLocalPanel />);

    expect(screen.getByText("<script>只作为标题文本</script>")).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
    const frame = screen.getByTitle("公众号本地模拟草稿预览");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(screen.getByText("local-media-body-safe")).toBeVisible();
    expect(screen.getByText("local-media-body-safe-1")).toBeVisible();
    expect(screen.getByText("local-media-body-safe-2")).toBeVisible();
    expect(screen.getByText("local-media-cover-safe")).toBeVisible();
    expect(screen.getByText("local-media-context-safe")).toBeVisible();
    expect(screen.getByText("新闻原图 01")).toBeVisible();
    expect(screen.getByText(/发布权限未验证/)).toBeVisible();
    expect(
      screen.getByRole("link", { name: "查看新闻原文（新窗口）" }),
    ).toHaveAttribute("href", "https://source.example/news/article");
    expect(screen.getByText("自动选图：3 张正文图")).toBeVisible();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === "STRONG" &&
          element.textContent === "正文块原创配图 0/3",
      ),
    ).toBeVisible();
    expect(screen.getByAltText("第一节观察现象正文块插画")).toBeVisible();
    expect(screen.getAllByText(/多模态语义匹配/).length).toBeGreaterThan(0);
    expect(screen.getByText(/相似度只用于合格图片排序/)).toBeVisible();
    expect(screen.getByText(/观察现象：固定测试素材/)).toBeVisible();
  });

  it("requires an explicit human-review confirmation and sends no publish action", async () => {
    const user = userEvent.setup();
    render(<OfficialAccountLocalPanel />);

    const approve = screen.getByRole("button", { name: "批准文稿" });
    expect(approve).toBeDisabled();
    await user.type(screen.getByLabelText("审稿标识"), "内容审核");
    await user.type(
      screen.getByLabelText("审稿备注（可选）"),
      "已核对事实和配图",
    );
    await user.click(approve);
    expect(screen.getByText("确认批准这份文稿？")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "确认记录" }));

    expect(hookMocks.reviewMutate).toHaveBeenCalledWith({
      runId: run.id,
      decision: "approved",
      reviewerLabel: "内容审核",
      note: "已核对事实和配图",
    });
    expect(screen.queryByRole("button", { name: /发布|群发|发送/ })).toBeNull();
  });

  it("has no basic automated accessibility violations", async () => {
    const { container } = render(<OfficialAccountLocalPanel />);
    const results = await axe(container, { iframes: false });
    expect(results.violations).toEqual([]);
  });
});
