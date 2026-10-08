import type { components } from "@/lib/api/generated/schema";

import { AdminSessionExpiredError, adminClient, reach } from "../api";

export type KeywordsOverview = components["schemas"]["AdminKeywordsResponse"];
export type KeywordVersion =
  components["schemas"]["AdminKeywordVersionResponse"];
export type KeywordImpact = components["schemas"]["AdminKeywordImpactResponse"];

export interface KeywordLists {
  readonly focus: readonly string[];
  readonly block: readonly string[];
  readonly copy_banned: readonly string[];
}

/** A refusal from the API with its stable code (e.g. keyword_block_too_wide). */
export class KeywordApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "KeywordApiError";
  }
}

/** Everything the 关键词 section asks the API; injected so tests never touch the network. */
export interface KeywordsApi {
  readonly load: () => Promise<KeywordsOverview>;
  readonly version: (version: number) => Promise<KeywordVersion>;
  readonly impact: (
    focus: readonly string[],
    block: readonly string[],
  ) => Promise<KeywordImpact>;
  readonly save: (
    lists: KeywordLists,
    options: { readonly note: string; readonly confirmWideBlock: boolean },
  ) => Promise<KeywordsOverview>;
}

type ErrorBody = {
  readonly error?: { readonly code?: unknown; readonly message?: unknown };
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
    const code =
      typeof body?.error?.code === "string" ? body.error.code : "error";
    const message =
      typeof body?.error?.message === "string" && body.error.message !== ""
        ? body.error.message
        : fallback;
    throw new KeywordApiError(code, message);
  }
  return result.data;
}

export const keywordsApi: KeywordsApi = {
  async load() {
    const result = await reach(() => adminClient.GET("/api/v1/admin/keywords"));
    return check(result, "读取关键词失败");
  },
  async version(version) {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/keywords/versions/{version}", {
        params: { path: { version } },
      }),
    );
    return check(result, "读取历史版本失败");
  },
  async impact(focus, block) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/keywords/impact", {
        body: { focus: [...focus], block: [...block] },
      }),
    );
    return check(result, "检查影响失败");
  },
  async save(lists, options) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/keywords", {
        body: {
          focus: [...lists.focus],
          block: [...lists.block],
          copy_banned: [...lists.copy_banned],
          note: options.note === "" ? null : options.note,
          confirm_wide_block: options.confirmWideBlock,
        },
      }),
    );
    return check(result, "保存失败");
  },
};

/** Same rule as the server: plain, case-insensitive substring. */
export function matchedTerms(text: string, terms: readonly string[]): string[] {
  const folded = text.toLocaleLowerCase();
  return terms.filter((term) => folded.includes(term.toLocaleLowerCase()));
}

/** Split typed or pasted input into terms: spaces, commas, 顿号, semicolons, new lines. */
export function splitTerms(value: string): string[] {
  return value
    .split(/[\s,，、;；]+/)
    .map((term) => term.trim())
    .filter((term) => term !== "");
}
