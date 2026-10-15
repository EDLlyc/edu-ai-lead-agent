import type { components } from "@/lib/api/generated/schema";

import { AdminSessionExpiredError, adminClient, reach } from "../api";

export type NewsPool = components["schemas"]["VisitorDisplayNewsPool"];
export type NewsCandidate =
  components["schemas"]["VisitorDisplayNewsCandidate"];
export type NewsHumanReview =
  components["schemas"]["VisitorDisplayHumanReview"];
export type NewsDecision = "agree" | "include" | "exclude";

/** A refusal from the API, with the message to show the reviewer. */
export class NewsReviewApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NewsReviewApiError";
  }
}

/** Everything the 新闻审核 section asks the API; injected so tests never touch the network. */
export interface NewsReviewsApi {
  readonly load: () => Promise<NewsPool>;
  readonly review: (
    key: string,
    decision: NewsDecision,
    note: string,
  ) => Promise<NewsHumanReview>;
}

type ErrorBody = { readonly error?: { readonly message?: unknown } };

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
    const message = body?.error?.message;
    throw new NewsReviewApiError(
      typeof message === "string" && message !== "" ? message : fallback,
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
};
