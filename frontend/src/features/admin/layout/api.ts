import type { components } from "@/lib/api/generated/schema";

import {
  AdminSessionExpiredError,
  adminClient,
  reach,
  serverMessage,
} from "../api";

export type LayoutTemplate = components["schemas"]["AdminLayoutTemplate"];
export type LayoutAccount = components["schemas"]["AdminLayoutAccount"];

export interface LayoutApi {
  readonly list: () => Promise<{
    readonly templates: readonly LayoutTemplate[];
    readonly accounts: readonly LayoutAccount[];
  }>;
  /** The sample article body in this template, as HTML. */
  readonly preview: (templateId: string) => Promise<string>;
  readonly choose: (
    accountId: string,
    templateId: string,
  ) => Promise<LayoutAccount>;
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

export const layoutApi: LayoutApi = {
  async list() {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/wechat/layout-templates"),
    );
    return check(result, "读取排版模板失败");
  },
  async preview(templateId) {
    const result = await reach(() =>
      adminClient.GET(
        "/api/v1/admin/wechat/layout-templates/{template_id}/preview",
        { params: { path: { template_id: templateId } } },
      ),
    );
    return check(result, "读取预览失败").html;
  },
  async choose(accountId, templateId) {
    const result = await reach(() =>
      adminClient.PUT(
        "/api/v1/admin/wechat/accounts/{account_id}/layout-template",
        {
          params: { path: { account_id: accountId } },
          body: { template_id: templateId },
        },
      ),
    );
    return check(result, "启用失败");
  },
};
