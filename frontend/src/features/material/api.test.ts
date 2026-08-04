import type { components } from "@/lib/api/generated/schema";
import { describe, expect, it } from "vitest";

import { mapMaterialPackage } from "./api";

const response = {
  id: "00000000-0000-4000-8000-000000000001",
  copy_generation_run_id: "00000000-0000-4000-8000-000000000002",
  status: "awaiting_manual_use",
  review_status: "pending",
  business_date: "2026-08-03",
  created_at: "2026-08-03T08:00:00Z",
  detail_url: "/api/v1/material-packages/00000000-0000-4000-8000-000000000001",
  package_version: 1,
  topic: {
    title: "儿童如何观察一片叶子",
    summary: "从日常观察进入科学提问。",
    category: "科学观察",
    source_trust: "权威来源",
    decision_kind: "selected",
    selection_explanation: "满足时效、相关性和来源可信度门槛。",
    score: 0.92,
    score_breakdown: { relevance: 0.9, freshness: 0.94 },
    selected_event_id: "event-1",
    selected_event_version_id: "event-version-1",
    business_date: "2026-08-03",
    timezone: "Asia/Shanghai",
  },
  copy: {
    draft_version_id: "draft-1",
    version: 2,
    copywriting: "一片叶子，也能成为孩子提出问题的起点。",
    parent_takeaway: "孩子可以从观察开始练习提问。",
    interaction: "你和孩子最近观察过什么？",
    source_note: "来源已绑定在下方证据。",
    claims: [
      {
        claim_id: "claim-1",
        text: "观察可以成为提问的起点。",
        kind: "brand_statement",
        evidence_ids: ["evidence-1"],
        brand_chunk_ids: ["brand-chunk-1"],
      },
    ],
  },
  sources: [
    {
      claim_id: "claim-1",
      source_url: "https://example.com/evidence",
      source_tier: "A",
      published_at: "2026-08-02T00:00:00Z",
      exact_quote: "观察是提出问题的入口。",
    },
  ],
  brand_bindings: [
    {
      claim_id: "claim-1",
      brand_chunk_id: "brand-chunk-1",
      document_title: "赛先生科学品牌资料",
      audience: "家长和儿童",
      text: "用观察和提问进入科学世界。",
      tone_tags: ["清晰", "亲切"],
      safety_tags: ["不夸大"],
    },
  ],
  validation: {
    passed: true,
    rule_version: "copy-rule-v1",
    issues: [
      {
        code: "deterministic_note",
        message: "验证记录来自素材包顶层快照。",
        severity: "info",
      },
    ],
  },
  audit: {
    accepted: true,
    rule_version: "copy-rule-v1",
    prompt_version: "copy-prompt-v1",
    schema_version: "copy-schema-v1",
    audit_id: "audit-1",
    issues: [
      {
        code: "style_note",
        message: "可保持句子简洁。",
        severity: "warning",
      },
    ],
  },
  image: {
    id: "00000000-0000-4000-8000-000000000003",
    status: "succeeded",
    provider: "fake",
    model: "fake-image",
    request_fingerprint: "fingerprint-1",
    width: 1024,
    height: 1024,
    media_type: "image/png",
    byte_size: 12,
    sha256: "abc",
    error_code: null,
    storage_metadata: {
      access: "private",
      immutable: true,
      content_addressed: true,
    },
    download_url:
      "/api/v1/material-packages/00000000-0000-4000-8000-000000000001/image",
  },
  versions: {
    copy: { version: 2 },
    image: { model: "fake-image", pipeline_version: "image-pipeline-v1" },
    package: 1,
  },
  download_url:
    "/api/v1/material-packages/00000000-0000-4000-8000-000000000001/download",
  review_note: null,
  reviewed_at: null,
  review_url:
    "/api/v1/material-packages/00000000-0000-4000-8000-000000000001/review",
} satisfies components["schemas"]["MaterialPackageResponse"];

describe("mapMaterialPackage", () => {
  it("narrows open snapshots once for the material-package view", () => {
    const materialPackage = mapMaterialPackage(response);

    expect(materialPackage.topic).toMatchObject({
      title: "儿童如何观察一片叶子",
      explanation: "满足时效、相关性和来源可信度门槛。",
      score: 0.92,
    });
    expect(materialPackage.copy.copywriting).toContain("一片叶子");
    expect(materialPackage.evidence[0]).toMatchObject({
      claimId: "claim-1",
      sourceUrl: "https://example.com/evidence",
      exactQuote: "观察是提出问题的入口。",
    });
    expect(materialPackage.brandBindings[0]).toMatchObject({
      claimId: "claim-1",
      brandChunkId: "brand-chunk-1",
      documentTitle: "赛先生科学品牌资料",
      text: "用观察和提问进入科学世界。",
    });
    expect(materialPackage.validation.passed).toBe(true);
    expect(materialPackage.validation.issues[0]).toMatchObject({
      code: "deterministic_note",
      message: "验证记录来自素材包顶层快照。",
    });
    expect(materialPackage.audit.issues[0]).toMatchObject({
      code: "style_note",
      severity: "warning",
    });
    expect(materialPackage.image.downloadUrl).toContain(
      "/api/v1/material-packages/00000000-0000-4000-8000-000000000001/image",
    );
  });
});
