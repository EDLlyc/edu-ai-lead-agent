import type { components } from "@/lib/api/generated/schema";

import {
  AdminSessionExpiredError,
  adminClient,
  reach,
  serverMessage,
} from "../api";

export type AdminSource = components["schemas"]["AdminSourceResponse"];
export type SourceConfig = components["schemas"]["AdminSourceConfig"];
export type SourceDraft = components["schemas"]["AdminSourceDraftRequest"];
export type SourcePreview = components["schemas"]["AdminSourcePreviewResponse"];
export type PreviewSample = components["schemas"]["AdminSourcePreviewSample"];

/** Everything the 新闻源 section asks the API; injected so tests never touch the network. */
export interface SourcesApi {
  readonly list: (includeArchived: boolean) => Promise<readonly AdminSource[]>;
  readonly preview: (
    entryUrl: string,
    config: SourceConfig,
  ) => Promise<SourcePreview>;
  readonly create: (draft: SourceDraft) => Promise<AdminSource>;
  readonly update: (id: string, draft: SourceDraft) => Promise<AdminSource>;
  readonly setEnabled: (id: string, enabled: boolean) => Promise<AdminSource>;
  readonly archive: (id: string) => Promise<void>;
}

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
    throw new Error(serverMessage(result.error, fallback));
  }
  return result.data;
}

export const sourcesApi: SourcesApi = {
  async list(includeArchived) {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/sources", {
        params: { query: { include_archived: includeArchived } },
      }),
    );
    return check(result, "读取新闻源失败").items;
  },
  async preview(entryUrl, config) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/sources/preview", {
        body: { entry_url: entryUrl, config },
      }),
    );
    return check(result, "预览失败");
  },
  async create(draft) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/sources", { body: draft }),
    );
    return check(result, "保存失败");
  },
  async update(id, draft) {
    const result = await reach(() =>
      adminClient.PATCH("/api/v1/admin/sources/{source_id}", {
        params: { path: { source_id: id } },
        body: draft,
      }),
    );
    return check(result, "保存失败");
  },
  async setEnabled(id, enabled) {
    const params = { params: { path: { source_id: id } } };
    const result = await reach(() =>
      enabled
        ? adminClient.POST("/api/v1/admin/sources/{source_id}/enable", params)
        : adminClient.POST("/api/v1/admin/sources/{source_id}/disable", params),
    );
    return check(result, enabled ? "打开失败" : "关闭失败");
  },
  async archive(id) {
    const result = await reach(() =>
      adminClient.DELETE("/api/v1/admin/sources/{source_id}", {
        params: { path: { source_id: id } },
      }),
    );
    if (result.response.status === 401) throw new AdminSessionExpiredError();
    if (!result.response.ok) {
      throw new Error(serverMessage(result.error, "归档失败"));
    }
  },
};
