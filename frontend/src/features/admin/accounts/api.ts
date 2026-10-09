import type { components } from "@/lib/api/generated/schema";

import {
  AdminSessionExpiredError,
  adminClient,
  reach,
  serverMessage,
} from "../api";

export type AdminAccount = components["schemas"]["AdminAccountResponse"];
export type AccountRole = AdminAccount["role"];
export interface AccountWithPassword {
  readonly account: AdminAccount;
  /** Shown once; the server keeps only a hash. */
  readonly initialPassword: string;
}

/** Everything the 账号管理 page asks the API; injected so tests never touch the network. */
export interface AccountsApi {
  readonly list: () => Promise<readonly AdminAccount[]>;
  readonly create: (input: {
    readonly username: string;
    readonly displayName: string;
    readonly role: AccountRole;
  }) => Promise<AccountWithPassword>;
  readonly resetPassword: (username: string) => Promise<AccountWithPassword>;
  readonly setActive: (
    username: string,
    active: boolean,
  ) => Promise<AdminAccount>;
  readonly update: (
    username: string,
    changes: { readonly displayName?: string; readonly role?: AccountRole },
  ) => Promise<AdminAccount>;
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

const path = (username: string) => ({ params: { path: { username } } });

export const accountsApi: AccountsApi = {
  async list() {
    const result = await reach(() => adminClient.GET("/api/v1/admin/accounts"));
    return check(result, "读取账号失败").items;
  },
  async create(input) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/accounts", {
        body: {
          username: input.username,
          display_name: input.displayName,
          role: input.role,
        },
      }),
    );
    const data = check(result, "新建失败");
    return { account: data.account, initialPassword: data.initial_password };
  },
  async resetPassword(username) {
    const result = await reach(() =>
      adminClient.POST(
        "/api/v1/admin/accounts/{username}/reset-password",
        path(username),
      ),
    );
    const data = check(result, "重设失败");
    return { account: data.account, initialPassword: data.initial_password };
  },
  async setActive(username, active) {
    const result = await reach(() =>
      active
        ? adminClient.POST(
            "/api/v1/admin/accounts/{username}/enable",
            path(username),
          )
        : adminClient.POST(
            "/api/v1/admin/accounts/{username}/disable",
            path(username),
          ),
    );
    return check(result, active ? "启用失败" : "停用失败");
  },
  async update(username, changes) {
    const result = await reach(() =>
      adminClient.PATCH("/api/v1/admin/accounts/{username}", {
        ...path(username),
        body: {
          ...(changes.displayName === undefined
            ? {}
            : { display_name: changes.displayName }),
          ...(changes.role === undefined ? {} : { role: changes.role }),
        },
      }),
    );
    return check(result, "保存失败");
  },
};
