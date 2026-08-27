import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/schema";

import {
  mapCapabilities,
  mapEditorHandoff,
  mapRunDetail,
  mapRunSummary,
} from "./api";
import { shouldPollOfficialAccountRun } from "./hooks";

type RunDetail = components["schemas"]["OfficialAccountRunDetailResponse"];

const summary: components["schemas"]["OfficialAccountRunSummaryResponse"] = {
  id: "00000000-0000-4000-8000-000000000001",
  source_kind: "fixture",
  material_package_id: null,
  fixture_id: "official-account-article-v1",
  generation_mode: "fixture",
  provider: "fake",
  model: "official-account-fixture-v1",
  request_fingerprint: "a".repeat(64),
  status: "ready",
  current_stage: "ready",
  attempt_count: 1,
  error_code: null,
  error_retryable: false,
  created_at: "2026-08-21T00:00:00Z",
  started_at: "2026-08-21T00:00:01Z",
  completed_at: "2026-08-21T00:00:02Z",
  detail_url:
    "/api/v1/official-account-local/article-runs/00000000-0000-4000-8000-000000000001",
  retry_url:
    "/api/v1/official-account-local/article-runs/00000000-0000-4000-8000-000000000001/retry",
  simulation: true,
  boundary_label: "本地模拟，未同步公众号",
};

describe("official-account local API mapping", () => {
  it("maps generated capability and run contracts without duplicating wire enums", () => {
    const capabilities = mapCapabilities({
      enabled: true,
      simulation: true,
      fixture_available: true,
      fixture_id: "official-account-article-v1",
      live_available: false,
      live_unavailable_reason: "未配置",
      eligible_material_packages: [
        {
          id: "00000000-0000-4000-8000-000000000002",
          title: "合格素材",
          status: "ready",
          review_status: "pending",
        },
      ],
      boundary_label: "本地模拟，未同步公众号",
      visual_semantic_enabled: false,
      visual_semantic_provider_mode: "disabled",
      generated_visuals_enabled: false,
      editor_handoff_enabled: true,
    });
    const run = mapRunSummary(summary);

    expect(capabilities.eligibleMaterials[0]?.title).toBe("合格素材");
    expect(capabilities.liveAvailable).toBe(false);
    expect(capabilities.editorHandoffEnabled).toBe(true);
    expect(run.statusLabel).toBe("本地草稿就绪");
    expect(run.modeLabel).toContain("离线");
  });

  it("maps editor handoff gates, safe URLs and direct-use rights disclosure", () => {
    const handoff = mapEditorHandoff({
      state: "ready",
      copy_ready: true,
      simulation: true,
      local_only: true,
      published: false,
      boundary_label: "本地交接，未同步公众号",
      fingerprint: "f".repeat(64),
      identity: {
        renderer_version: "wechat-editor-handoff-renderer-v1-gzh-xiaosai",
        style_version: "wechat-editor-handoff-style-v1-xiaosai-blue",
        template_version: "wechat-editor-handoff-template-v1-moyu-layout",
        bundle_version: "official-account-editor-handoff-bundle-v1",
        preflight_version: "wechat-editor-handoff-preflight-v1",
        rights_policy_version:
          "editor-handoff-context-rights-v1-direct-use-disclosed",
        theme_id: "xiaosai-moyu-layout-v1",
        theme_sha256: "a".repeat(64),
      },
      checks: [
        {
          code: "context_image_rights_unverified_direct_use",
          severity: "warning",
          passed: false,
          field: "assets/context-00.jpg",
          detail: "按当前本地策略直接使用，发布权未验证",
        },
      ],
      blocking_codes: [],
      warning_codes: ["context_image_rights_unverified_direct_use"],
      media: [
        {
          name: "context-00.jpg",
          role: "context",
          ordinal: 0,
          download_url:
            "/api/v1/official-account-local/article-runs/run/editor-handoff/assets/context-00.jpg",
          media_type: "image/jpeg",
          byte_size: 128,
          sha256: "b".repeat(64),
          width: 1200,
          height: 800,
          alt_text: "新闻现场",
          assigned_section_index: 0,
          source_page_url: "https://example.invalid/news",
          credit: "来源机构",
          rights_status: "publish_permission_unverified",
          context_only_not_evidence: true,
        },
      ],
      mobile_validation: { status: "not_run", viewports: [320, 430] },
      body_url: "/safe/body",
      preview_url: "javascript:alert(1)",
      bundle_url: "/safe/bundle",
      bundle_filename: "wechat-editor-handoff-safe.zip",
      bundle_sha256: "c".repeat(64),
    });

    expect(handoff.copyReady).toBe(true);
    expect(handoff.checks[0]?.label).toBe("新闻图片权利");
    expect(handoff.media[0]?.rightsStatus).toBe(
      "publish_permission_unverified",
    );
    expect(handoff.previewUrl).toBeNull();
    expect(handoff.bundleUrl).toContain("/safe/bundle");
  });

  it("normalizes only safe API media and preview URLs", () => {
    const response: RunDetail = {
      ...summary,
      article: null,
      validation: null,
      audit: null,
      usage: null,
      media: [
        {
          local_media_id: "local-media-body-safe",
          role: "body",
          ordinal: 0,
          media_url: "javascript:alert(1)",
          media_type: "image/png",
          byte_size: 42,
          sha256: "b".repeat(64),
          alt_text: "第一节观察现象正文块插画",
          semantic_label: "观察现象",
          assigned_section_index: 0,
          score_band: "heading",
          selection_reason_code: "semantic_heading_match",
          selection_method: "deterministic_tag",
          similarity_band: null,
          context_only_not_evidence: false,
        },
        {
          local_media_id: "local-media-context-safe",
          role: "context",
          ordinal: 0,
          media_url:
            "/api/v1/official-account-local/media/local-media-context-safe",
          media_type: "image/jpeg",
          byte_size: 84,
          sha256: "9".repeat(64),
          alt_text: "新闻现场中的科学教育活动",
          semantic_label: "新闻原图",
          provenance_kind: "source_news",
          source_page_url: "https://source.example/news/article",
          caption: "新闻现场",
          credit: "来源机构",
          rights_status: "publish_permission_unverified",
          context_only_not_evidence: true,
        },
      ],
      body_image: {
        local_media_id: "local-media-body-safe",
        role: "body",
        ordinal: 0,
        media_url: "javascript:alert(1)",
        media_type: "image/png",
        byte_size: 42,
        sha256: "b".repeat(64),
        context_only_not_evidence: false,
      },
      body_images: [
        {
          local_media_id: "local-media-body-safe",
          role: "body",
          ordinal: 0,
          media_url: "javascript:alert(1)",
          media_type: "image/png",
          byte_size: 42,
          sha256: "b".repeat(64),
          context_only_not_evidence: false,
        },
      ],
      context_images: [
        {
          local_media_id: "local-media-context-safe",
          role: "context",
          ordinal: 0,
          media_url:
            "/api/v1/official-account-local/media/local-media-context-safe",
          media_type: "image/jpeg",
          byte_size: 84,
          sha256: "9".repeat(64),
          alt_text: "新闻现场中的科学教育活动",
          semantic_label: "新闻原图",
          provenance_kind: "source_news",
          source_page_url: "https://source.example/news/article",
          caption: "新闻现场",
          credit: "来源机构",
          rights_status: "publish_permission_unverified",
          context_only_not_evidence: true,
        },
      ],
      context_media_status: "partial",
      cover_image: null,
      media_selection: {
        policy_version: "official-account-media-plan-v1-deterministic",
        body_image_count: 1,
        target_body_image_count: "3–5 张（候选充足时）",
        safely_degraded: true,
        explanation: ["当前素材包仅暴露一张已审核图片，按安全降级使用单图"],
        selection_mode: "deterministic_fallback",
        semantic_status: "single_candidate",
        semantic_unavailable_reason: "single_candidate",
        visual_query_version: "official-account-visual-query-v1",
        visual_selector_version:
          "official-account-visual-selector-v3-multimodal-hybrid",
        embedding_identity: null,
      },
      generated_visuals: [
        {
          ordinal: 0,
          section_index: 0,
          reference_asset_ref: "d".repeat(16),
          selection_method: "deterministic_tag",
          similarity_band: null,
          status: "ready",
          request_fingerprint: "e".repeat(64),
          plan_version: "official-account-generated-visual-plan-v1",
          prompt_version: "official-account-generated-visual-prompt-v1",
          provider: "fake",
          model: "gpt-image-2",
          media_type: "image/png",
          byte_size: 42,
          sha256: "f".repeat(64),
          width: 320,
          height: 180,
          error_code: null,
        },
      ],
      draft: {
        local_draft_id: "local-draft-safe",
        state: "ready",
        simulation: true,
        preview_url:
          "/api/v1/official-account-local/drafts/local-draft-safe/preview",
        resolved_fingerprint: "c".repeat(64),
        created_at: "2026-08-21T00:00:02Z",
        boundary_label: "本地模拟，未同步公众号",
      },
      manual_review: {
        status: "pending",
        review_id: null,
        reviewer_label: null,
        note: null,
        reviewed_at: null,
        request_fingerprint: null,
        idempotent_replay: false,
        editorially_approved: false,
      },
    };

    const detail = mapRunDetail(response);

    expect(detail.media[0]?.url).toBeNull();
    expect(detail.media[0]?.altText).toBe("第一节观察现象正文块插画");
    expect(detail.media[0]?.semanticLabel).toBe("观察现象");
    expect(detail.media[0]?.selectionMethodLabel).toBe("确定性标签回退");
    expect(detail.bodyImages).toHaveLength(1);
    expect(detail.contextImages[0]?.roleLabel).toBe("新闻原图 01");
    expect(detail.contextImages[0]?.sourcePageUrl).toBe(
      "https://source.example/news/article",
    );
    expect(detail.contextImages[0]?.rightsStatus).toBe(
      "publish_permission_unverified",
    );
    expect(detail.contextMediaStatus).toBe("partial");
    expect(detail.primaryBodyImageId).toBe("local-media-body-safe");
    expect(detail.mediaSelection.safelyDegraded).toBe(true);
    expect(detail.mediaSelection.modeLabel).toBe("确定性标签回退");
    expect(detail.mediaSelection.closedReasonLabel).toContain("一个合格候选");
    expect(detail.generatedVisuals[0]?.statusLabel).toBe("生成完成");
    expect(detail.generatedVisuals[0]?.referenceAssetRef).toBe("d".repeat(16));
    expect(detail.generatedVisualProgress).toEqual({ ready: 1, total: 1 });
    expect(detail.draft?.previewUrl).toMatch(/^http:\/\/127\.0\.0\.1:8000/);
    expect(detail.draft?.id).toBe("local-draft-safe");
    expect(detail.manualReview.statusLabel).toBe("等待最终人工审稿");
  });

  it("polls only non-terminal server states", () => {
    expect(shouldPollOfficialAccountRun("queued")).toBe(true);
    expect(shouldPollOfficialAccountRun("running")).toBe(true);
    expect(shouldPollOfficialAccountRun("ready")).toBe(false);
    expect(shouldPollOfficialAccountRun("review_required")).toBe(false);
    expect(shouldPollOfficialAccountRun("failed")).toBe(false);
    expect(shouldPollOfficialAccountRun("result_unknown")).toBe(false);
  });
});
