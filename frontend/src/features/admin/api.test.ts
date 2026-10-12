import { afterEach, describe, expect, it, vi } from "vitest";

import { adminApi, adminClient } from "./api";

afterEach(() => vi.restoreAllMocks());

describe("admin session transport", () => {
  it("accepts only the server's no-content logout acknowledgement", async () => {
    const request = vi
      .spyOn(adminClient, "POST")
      .mockResolvedValue({ response: new Response(null, { status: 204 }) });
    await expect(adminApi.logout()).resolves.toBeUndefined();
    expect(request).toHaveBeenCalledWith("/api/v1/admin/auth/logout");
  });

  it.each([200, 202, 401, 403, 500, 502])(
    "does not claim logout for HTTP %i",
    async (status) => {
      vi.spyOn(adminClient, "POST").mockResolvedValue({
        response: new Response(null, { status }),
      });
      await expect(adminApi.logout()).rejects.toThrow("退出未确认");
    },
  );

  it("rejects transport errors and redirected logout acknowledgements", async () => {
    const request = vi
      .spyOn(adminClient, "POST")
      .mockRejectedValueOnce(new Error("network"));
    await expect(adminApi.logout()).rejects.toThrow("连不上后台服务");
    const response = new Response(null, { status: 204 });
    Object.defineProperty(response, "redirected", { value: true });
    request.mockResolvedValueOnce({ response });
    await expect(adminApi.logout()).rejects.toThrow("退出未确认");
  });

  it("distinguishes confirmed 401 from a failed session check and passes cancellation", async () => {
    const request = vi.spyOn(adminClient, "GET").mockResolvedValueOnce({
      error: {},
      response: new Response(null, { status: 401 }),
    });
    const controller = new AbortController();
    await expect(adminApi.me(controller.signal)).resolves.toBeNull();
    expect(request).toHaveBeenCalledWith("/api/v1/admin/auth/me", {
      signal: controller.signal,
    });
    request.mockResolvedValueOnce({
      error: {},
      response: new Response(null, { status: 503 }),
    });
    await expect(adminApi.me()).rejects.toThrow("读取登录状态失败");
  });
});
