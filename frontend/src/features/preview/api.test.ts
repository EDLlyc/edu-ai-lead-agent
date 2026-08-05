import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchPreviewManifest,
  mapPreviewManifest,
  PreviewManifestError,
} from "./api";

const readyPayload = {
  schema_version: "preview-manifest-v1",
  run_id: "preview-run-1",
  status: "awaiting_manual_use",
  generated_at: "2026-08-05T10:30:00Z",
  business_date: "2026-08-05",
  stages: [
    {
      id: "acquisition",
      label: "权威来源采集",
      status: "completed",
      run_id: "acquisition-run-1",
      version: "acquisition-v1",
      started_at: "2026-08-05T10:00:00Z",
      finished_at: "2026-08-05T10:02:00Z",
    },
    { id: "copy_generation", status: "completed", version: "copy-v1" },
  ],
  acquisition: {
    candidates: [
      {
        candidate_id: "news-1",
        title: "教育部发布科学教育工作进展",
        source_name: "教育部",
        source_tier: "A",
        url: "https://www.moe.gov.cn/news/1",
        published_at: "2026-08-04T09:00:00Z",
        summary: "权威来源摘要",
        is_selected: true,
        status: "selected",
      },
    ],
  },
  topic: {
    decision_kind: "selected",
    title: "孩子如何从科学教育中建立长期好奇心",
    summary: "从真实新闻进入家庭讨论。",
    category: "科学教育",
    source_trust: "教育部权威来源",
    selection_explanation: "来源权威、时间窗口合规，且适合家长理解。",
    score: 0.94,
    selected_candidate_id: "news-1",
  },
  copy: {
    copywriting:
      "科学教育不是背答案，而是给孩子保留提问的空间。\n今天和孩子一起，从一条权威新闻开始聊聊。\n#赛先生科学 #科学教育",
    hashtags: ["赛先生科学", "#科学教育"],
    parent_takeaway: "家长可以把新闻变成一次共同提问。",
    interaction: "你和孩子最近讨论过什么科学问题？",
    source_note: "事实依据已绑定教育部来源。",
    version: "copy-draft-v1",
  },
  image: {
    status: "succeeded",
    preview_url: "./preview-run-1.png",
    filename: "preview-run-1.png",
    media_type: "image/png",
    width: 1024,
    height: 1024,
    byte_size: 2048,
    validation: {
      version: "image-validation-v1",
      configured: true,
      passed: true,
      issue_codes: [],
    },
    audit: {
      version: "image-audit-v1",
      configured: true,
      status: "accepted",
      passed: true,
      issue_codes: [],
    },
  },
  brand_bindings: [
    {
      id: "brand-chunk-1",
      document_title: "赛先生视觉规范",
      role: "identity_reference",
      selection_reason: "匹配科学教育主题",
      tone_tags: ["清晰"],
      safety_tags: ["克制"],
    },
  ],
  validation: { passed: true, rule_version: "copy-rule-v1", issues: [] },
  audit: { accepted: true, rule_version: "audit-v1", issues: [] },
};

describe("preview manifest mapper", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("maps the real preview payload into safe display data", () => {
    const preview = mapPreviewManifest(
      readyPayload,
      "https://preview.test/output/manifest.json",
    );

    expect(preview).toMatchObject({
      schemaVersion: "preview-manifest-v1",
      runId: "preview-run-1",
      status: "ready",
      businessDate: "2026-08-05",
    });
    expect(preview.topic).toMatchObject({
      title: "孩子如何从科学教育中建立长期好奇心",
      decision: "selected",
      selectedSourceId: "news-1",
      score: 0.94,
    });
    expect(preview.sources[0]).toMatchObject({
      title: "教育部发布科学教育工作进展",
      sourceName: "教育部",
      isSelected: true,
      url: "https://www.moe.gov.cn/news/1",
    });
    expect(preview.copy.hashtags).toEqual(["#赛先生科学", "#科学教育"]);
    expect(preview.validation).toMatchObject({
      status: "passed",
      version: "copy-rule-v1",
    });
    expect(preview.audit).toMatchObject({
      status: "passed",
      version: "audit-v1",
    });
    expect(preview.image).toMatchObject({
      status: "ready",
      url: "https://preview.test/output/preview-run-1.png",
      width: 1024,
      height: 1024,
    });
    expect(preview.brandBindings[0]).toMatchObject({
      title: "赛先生视觉规范",
      role: "identity_reference",
    });
    expect(preview.downloadPayload).not.toHaveProperty("image.url");
    expect(JSON.stringify(preview.downloadPayload)).not.toContain("object_key");
  });

  it("resolves a safe image filename beside the manifest and rejects traversal", () => {
    const filenamePreview = mapPreviewManifest(
      {
        status: "ready",
        run_id: "filename-run",
        topic: { decision_kind: "selected", title: "文件名图片" },
        image: { status: "succeeded", filename: "images/preview.png" },
      },
      "https://preview.test/output/manifest.json",
    );
    expect(filenamePreview.image.url).toBe(
      "https://preview.test/output/images/preview.png",
    );

    const unsafePreview = mapPreviewManifest({
      status: "ready",
      run_id: "unsafe-run",
      topic: { decision_kind: "selected", title: "路径图片" },
      image: { status: "succeeded", filename: "../private/object.png" },
    });
    expect(unsafePreview.image.url).toBeNull();

    const signedPreview = mapPreviewManifest({
      status: "ready",
      run_id: "signed-run",
      topic: { decision_kind: "selected", title: "签名图片" },
      image: {
        status: "succeeded",
        image_url: "https://cdn.example.test/preview.png?signature=secret",
      },
    });
    expect(signedPreview.image.url).toBeNull();
  });

  it("keeps no-topic and review-required outcomes distinct from ready", () => {
    const noTopic = mapPreviewManifest({
      status: "no_topic",
      run_id: "preview-no-topic",
      topic: {
        decision_kind: "no_topic",
        selection_explanation: "窗口内没有满足门槛的教育部科学新闻。",
      },
      stages: { acquisition: "completed", topic_selection: "no_topic" },
    });
    expect(noTopic.status).toBe("no_topic");
    expect(noTopic.topic.decision).toBe("no_topic");

    const reviewRequired = mapPreviewManifest({
      status: "review_required",
      run_id: "preview-review",
      topic: { decision_kind: "selected", title: "待复核选题" },
      copy: { copywriting: "需要复核的文案。" },
      image: {
        status: "review_required",
        image_url: "https://preview.test/review.png",
        audit: {
          status: "rejected",
          passed: false,
          issue_codes: ["visual_risk"],
        },
      },
    });
    expect(reviewRequired.status).toBe("review_required");
    expect(reviewRequired.image.status).toBe("review_required");
    expect(reviewRequired.findings).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ stage: "图片审计", code: "visual_risk" }),
      ]),
    );
  });

  it("renders the runner's failed manifest with its first blocking stage", () => {
    const failed = mapPreviewManifest({
      schema_version: "preview-manifest-v1",
      run_id: "preview-failed",
      status: "failed",
      error_code: "api_http_409",
      error_message: "API 请求失败，详细原因请查看对应阶段的安全错误码",
      stages: [
        { id: "acquisition", label: "权威来源采集", status: "completed" },
        { id: "governance", label: "事实治理", status: "completed" },
        {
          id: "topic_selection",
          label: "Top 1 选题",
          status: "failed",
          error_code: "api_http_409",
        },
      ],
      topic: {},
      copy: {
        copywriting: "",
        validation: { status: "pending" },
        audit: { status: "pending" },
      },
      image: {
        status: "missing",
        url: null,
        validation: { status: "pending" },
        audit: { status: "not_configured" },
      },
    });

    expect(failed).toMatchObject({
      status: "failed",
      errorCode: "api_http_409",
      errorMessage: "API 请求失败，详细原因请查看对应阶段的安全错误码",
      image: { status: "missing" },
    });
    expect(failed.stages[2]).toMatchObject({
      label: "Top 1 选题",
      status: "failed",
      errorCode: "api_http_409",
    });
  });

  it("rejects a non-object manifest at the runtime boundary", () => {
    expect(() => mapPreviewManifest([])).toThrow(PreviewManifestError);
  });

  it("translates a missing local resource into a typed API error", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchPreviewManifest("https://preview.test/preview/latest.json"),
    ).rejects.toMatchObject({ code: "not_found", httpStatus: 404 });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://preview.test/preview/latest.json",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });
});
