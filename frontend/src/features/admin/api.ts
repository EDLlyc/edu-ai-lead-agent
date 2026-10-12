import createClient from "openapi-fetch";

import type { components, paths } from "@/lib/api/generated/schema";

export type AdminMe = components["schemas"]["AdminMeResponse"];
export type AdminRole = AdminMe["role"];
export type AdminAuditEvent = components["schemas"]["AdminAuditEventResponse"];

/** The session ended (expired, logged out elsewhere, account disabled): show the login page. */
export class AdminSessionExpiredError extends Error {
  constructor() {
    super("登录已过期，请重新登录");
    this.name = "AdminSessionExpiredError";
  }
}

/** Everything the 运营后台 asks the API; injected so tests never touch the network. */
export interface AdminApi {
  readonly me: (signal?: AbortSignal) => Promise<AdminMe | null>;
  readonly login: (username: string, password: string) => Promise<AdminMe>;
  readonly logout: () => Promise<void>;
  readonly auditEvents: (
    query?: AuditQuery,
  ) => Promise<readonly AdminAuditEvent[]>;
  /** Resolves with how many other sessions ended; rejects with a plain message. */
  readonly changePassword: (current: string, next: string) => Promise<number>;
}

export type AuditKind =
  "auth" | "user" | "source" | "keywords" | "wechat" | "model";
export interface AuditQuery {
  readonly kind?: AuditKind;
  /** Only events before this time (paging back). */
  readonly before?: string;
}

export const AUDIT_PAGE_SIZE = 50;

// Same origin on purpose: the dev server (and later the reverse proxy) forwards /api/v1/admin to
// the API, so the SameSite=Strict session cookie needs no credentialed CORS.
export const adminClient = createClient<paths>({
  baseUrl: "",
  credentials: "same-origin",
  headers: { "X-Admin-Request": "1" },
});

type ErrorBody = { readonly error?: { readonly message?: unknown } };

export function serverMessage(error: unknown, fallback: string): string {
  const message = (error as ErrorBody | undefined)?.error?.message;
  return typeof message === "string" && message !== "" ? message : fallback;
}

export async function reach<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch {
    throw new Error("连不上后台服务，请确认服务已启动");
  }
}

export const adminApi: AdminApi = {
  async me(signal) {
    const { data, response } = await reach(() =>
      adminClient.GET("/api/v1/admin/auth/me", { signal: signal ?? null }),
    );
    if (response.status === 401) return null;
    if (data === undefined) throw new Error("读取登录状态失败，请刷新重试");
    return data;
  },
  async login(username, password) {
    const { data, error } = await reach(() =>
      adminClient.POST("/api/v1/admin/auth/login", {
        body: { username, password },
      }),
    );
    if (data === undefined) throw new Error(serverMessage(error, "登录失败"));
    return data;
  },
  async logout() {
    const { response } = await reach(() =>
      adminClient.POST("/api/v1/admin/auth/logout"),
    );
    // Only the contract's no-content acknowledgement confirms server-side revocation.
    if (response.status !== 204 || response.redirected)
      throw new Error("退出未确认，请重试");
  },
  async auditEvents(query = {}) {
    const { data, response } = await reach(() =>
      adminClient.GET("/api/v1/admin/audit-events", {
        params: {
          query: {
            limit: AUDIT_PAGE_SIZE,
            ...(query.kind === undefined ? {} : { kind: query.kind }),
            ...(query.before === undefined ? {} : { before: query.before }),
          },
        },
      }),
    );
    if (response.status === 401) throw new AdminSessionExpiredError();
    if (data === undefined) throw new Error("读取操作记录失败，请重试");
    return data.items;
  },
  async changePassword(current, next) {
    const { data, error, response } = await reach(() =>
      adminClient.POST("/api/v1/admin/auth/password", {
        body: { current_password: current, new_password: next },
      }),
    );
    if (response.status === 401) throw new AdminSessionExpiredError();
    if (data === undefined) throw new Error(serverMessage(error, "修改失败"));
    return data.other_sessions_ended;
  },
};
