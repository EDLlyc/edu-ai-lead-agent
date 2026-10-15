import type { NewsCandidate, NewsHumanReview, NewsPick, NewsPool } from "./api";

export const SLOT_LABEL = {
  morning: "早间",
  noon: "午间",
  evening: "晚间",
} as const;

type Reason = NonNullable<NewsCandidate["reasons"]>[number];

export const REASON_LABEL: Record<Reason, string> = {
  unresolved_governance: "事件归类待确认",
  ineligible_evidence: "证据不合格",
  tier_c_only: "只有一般来源",
  unverified: "事实未核实",
  unsuitable_negative_incident: "负面事件",
  privacy_legal_safety_uncertain: "隐私或法律风险",
  prohibited_marketing_risk: "营销合规风险",
  repeated_within_window: "近期写过",
  stale_event: "新闻过时",
  outside_science_ai_education_scope: "不在科学/AI 教育范围",
  other_rule: "其他规则拦下",
  below_threshold: "分数没过线",
  same_day_already_selected: "今天已选过",
  not_eligible: "不符合入选条件",
  ranked_out: "排序靠后",
};

export const EXCLUDE_REASONS = [
  "不是教育/科技/AI",
  "太专业，家长看不懂",
  "负面或敏感",
  "地方性、太小众",
  "像营销软文",
  "旧闻或重复",
] as const;

/** One news item as the reviewer sees it. The same story shows up in several slots' pools; it is
 * reviewed once, under the key of its newest appearance. */
export interface ReviewItem {
  readonly key: string;
  readonly title: string;
  readonly sourceName: string | null;
  readonly sourceUrl: string | null;
  readonly tierLabel: string | null;
  readonly publishedAt: string | null;
  readonly snippet: string | null;
  readonly eligible: boolean;
  readonly selected: boolean;
  readonly bestScore: number;
  readonly threshold: number;
  readonly bestRank: number;
  readonly reasons: readonly Reason[];
  readonly slots: readonly string[];
  readonly existingReview: NewsHumanReview | null;
  /** Progress of a 人工加推 of this story, if one was made. */
  readonly pick: NewsPick | null;
}

export type ReviewCall = "include" | "exclude";

export interface ReviewRecord {
  readonly decision: ReviewCall;
  readonly note: string | null;
}

export function normalizeTitle(title: string): string {
  return title.replace(/[\s\p{P}\p{S}]/gu, "").toLowerCase();
}

function isEligible(candidate: NewsCandidate): boolean {
  return candidate.score >= candidate.threshold;
}

export function flattenPool(pool: NewsPool): ReviewItem[] {
  const batches = [...(pool.batches ?? [])].sort((a, b) =>
    b.target_at.localeCompare(a.target_at),
  );
  const byTitle = new Map<string, ReviewItem>();
  for (const batch of batches) {
    const slot = `${batch.business_date.slice(5)} ${SLOT_LABEL[batch.slot]}`;
    for (const candidate of batch.candidates ?? []) {
      const id = normalizeTitle(candidate.title);
      const seen = byTitle.get(id);
      if (seen === undefined) {
        byTitle.set(id, {
          key: candidate.key,
          title: candidate.title,
          sourceName: candidate.source_name ?? null,
          sourceUrl: candidate.source_url ?? null,
          tierLabel: candidate.tier_label ?? null,
          publishedAt: candidate.published_at ?? null,
          snippet: candidate.snippet ?? null,
          eligible: isEligible(candidate),
          selected: candidate.verdict === "selected",
          bestScore: candidate.score,
          threshold: candidate.threshold,
          bestRank: candidate.rank,
          reasons: candidate.reasons ?? [],
          slots: [slot],
          existingReview: candidate.human_review ?? null,
          pick: candidate.human_pick ?? null,
        });
        continue;
      }
      byTitle.set(id, {
        ...seen,
        eligible: seen.eligible || isEligible(candidate),
        selected: seen.selected || candidate.verdict === "selected",
        bestScore: Math.max(seen.bestScore, candidate.score),
        bestRank: Math.min(seen.bestRank, candidate.rank),
        slots: [...seen.slots, slot],
        existingReview: seen.existingReview ?? candidate.human_review ?? null,
        pick: seen.pick ?? candidate.human_pick ?? null,
      });
    }
  }
  return [...byTitle.values()];
}

/** "同意 AI" counts as the call the AI made. */
export function reviewCall(
  review: NewsHumanReview,
  item: ReviewItem,
): ReviewCall {
  if (review.decision === "agree") return item.selected ? "include" : "exclude";
  return review.decision;
}

export interface Agreement {
  readonly labelled: number;
  /** "适合推" vs the AI score clearing its threshold. */
  readonly agreeWithEligibility: number;
  /** "适合推" vs the AI's final top-3 pick (penalises capacity-limited rejections). */
  readonly agreeWithSelection: number;
  readonly includedButBelowThreshold: number;
  readonly excludedButEligible: number;
}

export function measureAgreement(
  items: readonly ReviewItem[],
  records: ReadonlyMap<string, ReviewRecord>,
): Agreement {
  const result = {
    labelled: 0,
    agreeWithEligibility: 0,
    agreeWithSelection: 0,
    includedButBelowThreshold: 0,
    excludedButEligible: 0,
  };
  for (const item of items) {
    const record = records.get(item.key);
    if (record === undefined) continue;
    result.labelled += 1;
    const include = record.decision === "include";
    if (include === item.eligible) result.agreeWithEligibility += 1;
    if (include === item.selected) result.agreeWithSelection += 1;
    if (include && !item.eligible) result.includedButBelowThreshold += 1;
    if (!include && item.eligible) result.excludedButEligible += 1;
  }
  return result;
}

/** What the operator sees for each stage of a 人工加推. */
export const PICK_STAGE_LABEL: Record<NewsPick["stage"], string> = {
  queued: "排队中",
  writing: "正在写文案",
  imaging: "正在配图",
  awaiting_review: "等你确认",
  sending: "正在发送",
  delivered: "已发到正式群",
  partial: "部分发送，需要检查",
  unknown: "发送结果待确认",
  failed: "加推失败",
  expired: "已过 22:30，作废",
};

/** The stages in which production is still working, so the page keeps refreshing them. */
export function pickInProgress(pick: NewsPick | null | undefined): boolean {
  return (
    pick !== null &&
    pick !== undefined &&
    ["queued", "writing", "imaging", "sending"].includes(pick.stage)
  );
}
