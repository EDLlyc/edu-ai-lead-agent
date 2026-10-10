import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminSessionExpiredError, adminClient } from "../api";
import { wechatApi } from "./api";
import { ACCOUNT, job } from "./testApi";

afterEach(() => vi.restoreAllMocks());

describe("发布记录请求契约", () => {
  it("transmits page and inclusive date filters while keeping the legacy adapter unfiltered", async () => {
    const data = {
      items: [job()],
      offset: 40,
      limit: 20,
      total: 65,
      business_timezone: "Asia/Shanghai",
    };
    const request = vi.spyOn(adminClient, "GET").mockResolvedValue({
      data,
      response: new Response(null, { status: 200 }),
    });
    expect(
      await wechatApi.jobsPage(ACCOUNT.id, 40, {
        status: "outcome_unknown",
        dateFrom: "2026-10-09",
        dateTo: "2026-10-10",
      }),
    ).toEqual(data);
    expect(request).toHaveBeenLastCalledWith(
      "/api/v1/admin/wechat/publish-jobs",
      {
        params: {
          query: {
            account_id: ACCOUNT.id,
            offset: 40,
            limit: 20,
            status: "outcome_unknown",
            date_from: "2026-10-09",
            date_to: "2026-10-10",
          },
        },
      },
    );
    await wechatApi.jobsPage(ACCOUNT.id, 0, {
      status: "",
      dateFrom: "",
      dateTo: "",
    });
    expect(request).toHaveBeenLastCalledWith(
      "/api/v1/admin/wechat/publish-jobs",
      { params: { query: { account_id: ACCOUNT.id, offset: 0, limit: 20 } } },
    );
    expect(await wechatApi.jobs(ACCOUNT.id)).toEqual(data.items);
    expect(request).toHaveBeenLastCalledWith(
      "/api/v1/admin/wechat/publish-jobs",
      { params: { query: { account_id: ACCOUNT.id } } },
    );
  });

  it("surfaces server date validation and forces expired sessions instead of returning empty records", async () => {
    const request = vi.spyOn(adminClient, "GET").mockResolvedValue({
      error: { error: { message: "创建日期的开始日期不能晚于结束日期" } },
      response: new Response(null, { status: 422 }),
    });
    await expect(
      wechatApi.jobsPage(ACCOUNT.id, 0, {
        status: "",
        dateFrom: "2026-10-11",
        dateTo: "2026-10-10",
      }),
    ).rejects.toThrow("创建日期的开始日期不能晚于结束日期");
    request.mockResolvedValue({
      error: {},
      response: new Response(null, { status: 401 }),
    });
    await expect(
      wechatApi.jobsPage(ACCOUNT.id, 0, {
        status: "",
        dateFrom: "",
        dateTo: "",
      }),
    ).rejects.toBeInstanceOf(AdminSessionExpiredError);
  });
});
