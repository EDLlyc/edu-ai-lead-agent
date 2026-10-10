import type { components } from "@/lib/api/generated/schema";

import {
  AdminSessionExpiredError,
  adminClient,
  reach,
  serverMessage,
} from "../api";

export type WeChatAccount = components["schemas"]["AdminWeChatAccountResponse"];
export type WeChatAccountOption =
  components["schemas"]["AdminWeChatAccountOption"];
export type WeChatDraft = components["schemas"]["AdminWeChatDraft"];
export type WeChatPublished = components["schemas"]["AdminWeChatPublished"];
export type PublishJob = components["schemas"]["AdminWeChatPublishJob"];
export type PublishJobPage =
  components["schemas"]["AdminWeChatPublishJobListResponse"];
export type JobFilters = Readonly<{
  status: PublishJob["status"] | "";
  dateFrom: string;
  dateTo: string;
}>;
export type WeChatStats = components["schemas"]["AdminWeChatStatsResponse"];
export type PublishReconcile =
  components["schemas"]["AdminWeChatPublishReconcileRequest"];
export type DailyStats = components["schemas"]["AdminWeChatDailyStats"];
export type ArticleStats = components["schemas"]["AdminWeChatArticleStats"];

export interface WeChatApi {
  readonly status: () => Promise<{ readonly secretKeyConfigured: boolean }>;
  readonly accounts: () => Promise<readonly WeChatAccount[]>;
  readonly options: () => Promise<readonly WeChatAccountOption[]>;
  readonly bind: (input: {
    readonly name: string;
    readonly appId: string;
    readonly appSecret: string;
    readonly topics: readonly string[];
  }) => Promise<WeChatAccount>;
  readonly update: (
    id: string,
    changes: {
      readonly name?: string;
      readonly topics?: readonly string[];
      readonly enabled?: boolean;
      readonly appSecret?: string;
    },
  ) => Promise<WeChatAccount>;
  readonly verify: (id: string) => Promise<WeChatAccount>;
  readonly drafts: (
    accountId: string,
    offset: number,
  ) => Promise<{
    readonly total: number;
    readonly items: readonly WeChatDraft[];
  }>;
  readonly published: (
    accountId: string,
    offset: number,
  ) => Promise<{
    readonly total: number;
    readonly items: readonly WeChatPublished[];
  }>;
  readonly jobs: (accountId: string) => Promise<readonly PublishJob[]>;
  readonly jobsPage: (
    accountId: string,
    offset: number,
    filters: JobFilters,
  ) => Promise<PublishJobPage>;
  readonly publish: (input: {
    readonly accountId: string;
    readonly mediaId: string;
    readonly title: string;
    readonly scheduledAt: string | null;
  }) => Promise<PublishJob>;
  readonly cancel: (jobId: string) => Promise<PublishJob>;
  readonly recheck: (jobId: string) => Promise<PublishJob>;
  readonly reconcile: (
    jobId: string,
    input: PublishReconcile,
  ) => Promise<PublishJob>;
  readonly stats: (accountId: string, days: number) => Promise<WeChatStats>;
  readonly syncStats: (
    accountId: string,
  ) => Promise<{ readonly articles: number; readonly days: number }>;
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

const account = (id: string) => ({ params: { path: { account_id: id } } });

export const wechatApi: WeChatApi = {
  async status() {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/wechat/status"),
    );
    return {
      secretKeyConfigured: check(result, "读取失败").secret_key_configured,
    };
  },
  async accounts() {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/wechat/accounts"),
    );
    return check(result, "读取公众号失败").items;
  },
  async options() {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/wechat/account-options"),
    );
    return check(result, "读取公众号失败").items;
  },
  async bind(input) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/wechat/accounts", {
        body: {
          name: input.name,
          app_id: input.appId,
          app_secret: input.appSecret,
          topics: [...input.topics],
        },
      }),
    );
    return check(result, "绑定失败");
  },
  async update(id, changes) {
    const result = await reach(() =>
      adminClient.PATCH("/api/v1/admin/wechat/accounts/{account_id}", {
        ...account(id),
        body: {
          ...(changes.name === undefined ? {} : { name: changes.name }),
          ...(changes.topics === undefined
            ? {}
            : { topics: [...changes.topics] }),
          ...(changes.enabled === undefined
            ? {}
            : { enabled: changes.enabled }),
          ...(changes.appSecret === undefined
            ? {}
            : { app_secret: changes.appSecret }),
        },
      }),
    );
    return check(result, "保存失败");
  },
  async verify(id) {
    const result = await reach(() =>
      adminClient.POST(
        "/api/v1/admin/wechat/accounts/{account_id}/verify",
        account(id),
      ),
    );
    return check(result, "验证失败");
  },
  async drafts(accountId, offset) {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/wechat/accounts/{account_id}/drafts", {
        params: { path: { account_id: accountId }, query: { offset } },
      }),
    );
    return check(result, "读取草稿箱失败");
  },
  async published(accountId, offset) {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/wechat/accounts/{account_id}/published", {
        params: { path: { account_id: accountId }, query: { offset } },
      }),
    );
    return check(result, "读取已发布文章失败");
  },
  async jobs(accountId) {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/wechat/publish-jobs", {
        params: { query: { account_id: accountId } },
      }),
    );
    return check(result, "读取发布记录失败").items;
  },
  async jobsPage(accountId, offset, filters) {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/wechat/publish-jobs", {
        params: {
          query: {
            account_id: accountId,
            offset,
            limit: 20,
            ...(filters.status === "" ? {} : { status: filters.status }),
            ...(filters.dateFrom === "" ? {} : { date_from: filters.dateFrom }),
            ...(filters.dateTo === "" ? {} : { date_to: filters.dateTo }),
          },
        },
      }),
    );
    return check(result, "读取发布记录失败");
  },
  async publish(input) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/wechat/publish-jobs", {
        body: {
          account_id: input.accountId,
          media_id: input.mediaId,
          title: input.title,
          scheduled_at: input.scheduledAt,
        },
      }),
    );
    return check(result, "发布失败");
  },
  async cancel(jobId) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/wechat/publish-jobs/{job_id}/cancel", {
        params: { path: { job_id: jobId } },
      }),
    );
    return check(result, "取消失败");
  },
  async recheck(jobId) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/wechat/publish-jobs/{job_id}/recheck", {
        params: { path: { job_id: jobId } },
      }),
    );
    return check(result, "查询失败，原发布结果仍待核对");
  },
  async reconcile(jobId, input) {
    const result = await reach(() =>
      adminClient.POST("/api/v1/admin/wechat/publish-jobs/{job_id}/reconcile", {
        params: { path: { job_id: jobId } },
        body: input,
      }),
    );
    return check(result, "核对结果保存失败，请刷新记录");
  },
  async stats(accountId, days) {
    const result = await reach(() =>
      adminClient.GET("/api/v1/admin/wechat/accounts/{account_id}/stats", {
        params: { path: { account_id: accountId }, query: { days } },
      }),
    );
    return check(result, "读取数据失败");
  },
  async syncStats(accountId) {
    const result = await reach(() =>
      adminClient.POST(
        "/api/v1/admin/wechat/accounts/{account_id}/stats/sync",
        account(accountId),
      ),
    );
    return check(result, "同步失败");
  },
};

export const JOB_STATUS_LABELS: Readonly<Record<PublishJob["status"], string>> =
  {
    scheduled: "等待定时发布",
    submitting: "正在提交",
    publishing: "微信发布中",
    succeeded: "已发布",
    failed: "发布失败",
    outcome_unknown: "结果待核对",
    cancelled: "已取消",
  };
