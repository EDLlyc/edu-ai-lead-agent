import { AdminSessionExpiredError, adminClient, reach } from "../api";
import { KeywordApiError } from "./api";

export interface BuiltinPhrases {
  readonly version: number | null;
  readonly marketing: readonly string[];
  readonly anxiety: readonly string[];
  readonly defaults_marketing: readonly string[];
  readonly defaults_anxiety: readonly string[];
  readonly locked: readonly {
    readonly name: string;
    readonly terms: readonly string[];
  }[];
  readonly note?: string | null;
  readonly created_by?: string | null;
  readonly created_at?: string | null;
}

export interface BuiltinPhrasesApi {
  readonly load: () => Promise<BuiltinPhrases>;
  readonly save: (
    marketing: readonly string[],
    anxiety: readonly string[],
  ) => Promise<BuiltinPhrases>;
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

export const builtinPhrasesApi: BuiltinPhrasesApi = {
  async load() {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/builtin-phrases"),
    );
    return check(result, "读取系统内置词失败");
  },
  async save(marketing, anxiety) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/builtin-phrases", {
        body: { marketing: [...marketing], anxiety: [...anxiety] },
      }),
    );
    return check(result, "保存系统内置词失败");
  },
};
