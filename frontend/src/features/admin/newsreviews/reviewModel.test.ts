import { describe, expect, it } from "vitest";

import type { NewsCandidate, NewsPool } from "./api";
import {
  flattenPool,
  measureAgreement,
  normalizeTitle,
  reviewCall,
  type ReviewRecord,
} from "./reviewModel";

function candidate(
  key: string,
  title: string,
  extra: Partial<NewsCandidate> = {},
): NewsCandidate {
  return {
    key,
    title,
    score: 0.7,
    threshold: 0.59,
    rank: 1,
    verdict: "selected",
    ...extra,
  };
}

const pool: NewsPool = {
  human_pick_enabled: false,
  review_enabled: true,
  batches: [
    {
      business_date: "2026-10-14",
      slot: "morning",
      target_at: "2026-10-14T01:00:00Z",
      total_count: 2,
      eligible_count: 1,
      selected_count: 1,
      candidates: [
        candidate("vn1_" + "a".repeat(24), "教育部：部署 AI 通识教育"),
        candidate("vn1_" + "b".repeat(24), "某地科技节", {
          score: 0.4,
          rank: 6,
          verdict: "rejected",
        }),
      ],
    },
    {
      business_date: "2026-10-15",
      slot: "noon",
      target_at: "2026-10-15T04:00:00Z",
      total_count: 1,
      eligible_count: 0,
      selected_count: 0,
      candidates: [
        candidate("vn1_" + "c".repeat(24), "教育部 部署AI通识教育", {
          score: 0.5,
          rank: 3,
          verdict: "rejected",
        }),
      ],
    },
  ],
};

describe("flattenPool", () => {
  it("lists one story once, under its newest appearance, with the best AI view", () => {
    const items = flattenPool(pool);
    expect(items.map((item) => item.title)).toEqual([
      "教育部 部署AI通识教育",
      "某地科技节",
    ]);
    const merged = items[0]!;
    expect(merged.key).toBe("vn1_" + "c".repeat(24));
    expect(merged.selected).toBe(true);
    expect(merged.eligible).toBe(true);
    expect(merged.bestScore).toBe(0.7);
    expect(merged.bestRank).toBe(1);
    expect(merged.slots).toEqual(["10-15 午间", "10-14 早间"]);
  });

  it("treats an empty pool as nothing to review", () => {
    expect(
      flattenPool({ human_pick_enabled: false, review_enabled: true }),
    ).toEqual([]);
  });

  it("normalises punctuation, spaces and case when matching titles", () => {
    expect(normalizeTitle("教育部：部署 AI 通识教育")).toBe(
      normalizeTitle("教育部 部署ai通识教育"),
    );
  });
});

describe("agreement", () => {
  it("counts what the reviewer would push against the AI's threshold and pick", () => {
    const items = flattenPool(pool);
    const records = new Map<string, ReviewRecord>([
      [items[0]!.key, { decision: "include", note: null }],
      [items[1]!.key, { decision: "include", note: "家长关心" }],
    ]);
    expect(measureAgreement(items, records)).toEqual({
      labelled: 2,
      agreeWithEligibility: 1,
      agreeWithSelection: 1,
      includedButBelowThreshold: 1,
      excludedButEligible: 0,
    });
  });

  it("reads an old 'agree' as the call the AI made", () => {
    const [selected, rejected] = flattenPool(pool) as [
      ReturnType<typeof flattenPool>[number],
      ReturnType<typeof flattenPool>[number],
    ];
    const agree = {
      decision: "agree",
      reviewed_at: "2026-10-15T05:00:00Z",
    } as const;
    expect(reviewCall(agree, selected)).toBe("include");
    expect(reviewCall(agree, rejected)).toBe("exclude");
  });
});
