import type { components } from "@/lib/api/generated/schema";

import {
  AdminSessionExpiredError,
  adminClient,
  reach,
  serverMessage,
} from "../api";

export type ModelProvider = components["schemas"]["AdminModelProvider"];
export type ModelKeyVersion = components["schemas"]["AdminModelKeyVersion"];
export type ModelKeyTest = components["schemas"]["AdminModelKeyTestResponse"];

export interface ModelsApi {
  readonly list: () => Promise<{
    readonly secretKeyConfigured: boolean;
    readonly providers: readonly ModelProvider[];
  }>;
  readonly test: (providerId: string, apiKey: string) => Promise<ModelKeyTest>;
  readonly save: (
    providerId: string,
    apiKey: string,
    note: string,
  ) => Promise<ModelProvider>;
  readonly history: (providerId: string) => Promise<readonly ModelKeyVersion[]>;
  readonly restore: (
    providerId: string,
    version: number,
  ) => Promise<ModelProvider>;
  readonly useEnv: (providerId: string) => Promise<ModelProvider>;
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

const provider = (id: string) => ({ params: { path: { provider_id: id } } });

export const modelsApi: ModelsApi = {
  async list() {
    const result = await reach(() => adminClient.GET("/api/v1/admin/models"));
    const data = check(result, "读取模型配置失败");
    return {
      secretKeyConfigured: data.secret_key_configured,
      providers: data.providers,
    };
  },
  async test(providerId, apiKey) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/models/{provider_id}/test", {
        ...provider(providerId),
        body: { api_key: apiKey },
      }),
    );
    return check(result, "测试失败");
  },
  async save(providerId, apiKey, note) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/models/{provider_id}/keys", {
        ...provider(providerId),
        body: { api_key: apiKey, ...(note === "" ? {} : { note }) },
      }),
    );
    return check(result, "保存失败");
  },
  async history(providerId) {
    const result = await reach(() =>
      adminClient.GET(
        "/api/v1/admin/models/{provider_id}/history",
        provider(providerId),
      ),
    );
    return check(result, "读取历史失败").items;
  },
  async restore(providerId, version) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/models/{provider_id}/restore", {
        ...provider(providerId),
        body: { version },
      }),
    );
    return check(result, "恢复失败");
  },
  async useEnv(providerId) {
    const result = await reach(() =>
      adminClient.POST(
        "/api/v1/admin/models/{provider_id}/use-env",
        provider(providerId),
      ),
    );
    return check(result, "改回失败");
  },
};
