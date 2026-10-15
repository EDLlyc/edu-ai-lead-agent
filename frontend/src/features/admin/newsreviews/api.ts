import type { components } from "@/lib/api/generated/schema";

import { AdminSessionExpiredError, adminClient, reach } from "../api";

export type NewsPool = components["schemas"]["VisitorDisplayNewsPool"];
export type NewsCandidate =
  components["schemas"]["VisitorDisplayNewsCandidate"];
export type NewsHumanReview =
  components["schemas"]["VisitorDisplayHumanReview"];
export type NewsDecision = "agree" | "include" | "exclude";
export type NewsPick = components["schemas"]["VisitorDisplayHumanPick"];
export type HeldPickReview = components["schemas"]["VisitorHumanPickReview"];

/** A refusal from the API, with the message to show the reviewer. */
export class NewsReviewApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NewsReviewApiError";
  }
}

/** What 人工加推 can do to a held pick; every refusal arrives as a plain Chinese message. */
export interface HeldPickApi {
  readonly loadReview: (key: string) => Promise<HeldPickReview>;
  readonly revise: (
    key: string,
    input: {
      readonly hook: string;
      readonly hashtags: readonly string[];
      readonly dryRun: boolean;
    },
  ) => Promise<HeldPickReview>;
  readonly push: (key: string) => Promise<NewsPick>;
}

/** Everything the 新闻审核 section asks the API; injected so tests never touch the network. */
export interface NewsReviewsApi extends HeldPickApi {
  readonly load: () => Promise<NewsPool>;
  readonly review: (
    key: string,
    decision: NewsDecision,
    note: string,
  ) => Promise<NewsHumanReview>;
  /** Make the copy and picture for one item and hold them; nothing is sent. */
  readonly createPick: (key: string) => Promise<NewsPick>;
}

type ErrorBody = {
  readonly error?: { readonly code?: unknown; readonly message?: unknown };
};

const PICK_REFUSAL: Record<string, string> = {
  human_pick_already_selected: "这条新闻今天已经入选过了，不用重复推",
  human_pick_already_delivered: "这条新闻之前已经推送过企微群了",
  human_pick_slot_busy: "AI 正在选题，请 1 分钟后再试",
  human_pick_no_lineage: "今天的第一场还没选完题，请稍后再试",
  human_pick_too_late: "22:30 以后不再加推，请明天再试",
  content_slot_disabled: "内容生产没有开启，暂时不能加推",
  human_pick_not_ready: "文案或配图还没准备好，请稍后再试",
  human_pick_already_pushed: "这条已经推送过了",
  human_pick_rejected: "这条已被拒绝，不能推送",
  human_pick_expired: "已过当天 22:30，这条加推作废了",
  human_pick_copy_invalid: "文案还有不通过的规则，请先修改并保存",
  not_found: "没有找到这条新闻或加推记录，请刷新后再试",
};

function check<T>(
  result: {
    readonly data?: T;
    readonly error?: unknown;
    readonly response: Response;
  },
  fallback: string,
): T {
  if (result.response.status === 401) throw new AdminSessionExpiredError();
  if (result.data === undefined) {
    const body = result.error as ErrorBody | undefined;
    const code = body?.error?.code;
    const message = body?.error?.message;
    const known = typeof code === "string" ? PICK_REFUSAL[code] : undefined;
    throw new NewsReviewApiError(
      known ??
        (typeof message === "string" && message !== "" ? message : fallback),
    );
  }
  return result.data;
}

export const newsReviewsApi: NewsReviewsApi = {
  async load() {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/news-reviews"),
    );
    return check(result, "读取新闻失败");
  },
  async review(key, decision, note) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/news-reviews", {
        body: { key, decision, note: note.trim() === "" ? null : note.trim() },
      }),
    );
    return check(result, "保存审核失败");
  },
  async createPick(key) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/human-picks", { body: { key } }),
    );
    return check(result, "加推失败，请重试");
  },
  async loadReview(key) {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/human-picks/{key}/review", {
        params: { path: { key } },
      }),
    );
    return check(result, "读取待审核文案失败，请重试");
  },
  async revise(key, input) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/human-picks/{key}/copy", {
        params: { path: { key } },
        body: {
          hook: input.hook,
          hashtags: [...input.hashtags],
          dry_run: input.dryRun,
        },
      }),
    );
    return check(result, "提交失败，请重试");
  },
  async push(key) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/human-picks/{key}/push", {
        params: { path: { key } },
      }),
    );
    return check(result, "推送失败，请重试");
  },
};
