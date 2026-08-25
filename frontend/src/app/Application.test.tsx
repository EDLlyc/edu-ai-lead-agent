import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const routeMocks = vi.hoisted(() => ({
  consoleRender: vi.fn(),
  ipAssetRender: vi.fn(),
  creationRender: vi.fn(),
}));

vi.mock("@/features/ip-assets/IpAssetCreationPage", () => ({
  IpAssetCreationPage: () => {
    routeMocks.creationRender();
    return <h1>AI 视觉创作室</h1>;
  },
}));

vi.mock("./App", () => ({
  App: () => {
    routeMocks.consoleRender();
    return (
      <main>
        <h1>品牌知识</h1>
        <p>EAL Brand Knowledge System</p>
      </main>
    );
  },
}));

vi.mock("@/features/ip-assets/IpAssetPage", () => ({
  IpAssetPage: () => {
    routeMocks.ipAssetRender();
    return (
      <section aria-labelledby="mock-ip-title">
        <h1 id="mock-ip-title">IP 数字资产中心</h1>
        <p>公司内网 · 无登录</p>
      </section>
    );
  },
}));

import { Application } from "./Application";
import { resolveApplicationPath } from "./pathResolver";

const defaultTitle = "Edu AI // Development Console";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
  document.title = defaultTitle;
});

function renderPath(pathname: string, enabled = false, strict = false) {
  window.history.replaceState(null, "", pathname);
  vi.stubEnv("VITE_IP_ASSET_HUB_ENABLED", enabled ? "true" : "false");
  return render(
    strict ? (
      <StrictMode>
        <Application />
      </StrictMode>
    ) : (
      <Application />
    ),
  );
}

describe("Application route composition", () => {
  it("resolves only explicit standalone and console paths", () => {
    expect(resolveApplicationPath("/")).toBe("console");
    expect(resolveApplicationPath("/ip-assets")).toBe("ip-assets");
    expect(resolveApplicationPath("/ip-assets/")).toBe("ip-assets");
    expect(resolveApplicationPath("/ip-assets/create")).toBe(
      "ip-assets-create",
    );
    expect(resolveApplicationPath("/ip-assets/create/")).toBe(
      "ip-assets-create",
    );
    expect(resolveApplicationPath("/ip-assets/archive")).toBe("not-found");
    expect(resolveApplicationPath("/unknown")).toBe("not-found");
  });

  it("keeps the IP hub outside the shared root console", () => {
    renderPath("/", true);

    expect(screen.getByRole("heading", { name: "品牌知识" })).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "IP 数字资产中心" }),
    ).not.toBeInTheDocument();
    expect(routeMocks.consoleRender).toHaveBeenCalledOnce();
    expect(routeMocks.ipAssetRender).not.toHaveBeenCalled();
  });

  it.each(["/ip-assets", "/ip-assets/"])(
    "renders the standalone IP page at %s without console content",
    async (pathname) => {
      renderPath(pathname, true);

      expect(
        await screen.findByRole("heading", {
          level: 1,
          name: "IP 数字资产中心",
        }),
      ).toBeVisible();
      expect(screen.getByText("公司内网 · 无登录")).toBeVisible();
      expect(screen.queryByText("品牌知识")).not.toBeInTheDocument();
      expect(
        screen.queryByText("EAL Brand Knowledge System"),
      ).not.toBeInTheDocument();
      expect(screen.getAllByRole("main")).toHaveLength(1);
      expect(
        screen.getByRole("link", { name: "跳到主要内容" }),
      ).toHaveAttribute("href", "#standalone-main");
      expect(routeMocks.consoleRender).not.toHaveBeenCalled();
      expect(routeMocks.ipAssetRender).toHaveBeenCalledOnce();
      await waitFor(() => expect(document.title).toBe("IP 数字资产中心"));
    },
  );

  it.each(["/ip-assets/create", "/ip-assets/create/"])(
    "renders the standalone creation studio at %s",
    async (pathname) => {
      renderPath(pathname, true);

      expect(
        await screen.findByRole("heading", { level: 1, name: "AI 视觉创作室" }),
      ).toBeVisible();
      expect(screen.queryByText("品牌知识")).not.toBeInTheDocument();
      expect(routeMocks.consoleRender).not.toHaveBeenCalled();
      expect(routeMocks.ipAssetRender).not.toHaveBeenCalled();
      expect(routeMocks.creationRender).toHaveBeenCalledOnce();
      await waitFor(() => expect(document.title).toBe("AI 视觉创作室"));
    },
  );

  it("fails closed at the standalone path when its flag is disabled", async () => {
    renderPath("/ip-assets");

    expect(
      screen.getByRole("heading", { level: 1, name: "页面不可用" }),
    ).toBeVisible();
    expect(screen.getByText(/本地功能当前未启用/)).toBeVisible();
    expect(screen.queryByText("品牌知识")).not.toBeInTheDocument();
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(routeMocks.consoleRender).not.toHaveBeenCalled();
    expect(routeMocks.ipAssetRender).not.toHaveBeenCalled();
    await waitFor(() => expect(document.title).toBe("页面不可用"));
  });

  it("fails closed at unknown paths without rendering either application", async () => {
    renderPath("/ip-assets/archive", true);

    expect(
      screen.getByRole("heading", { level: 1, name: "页面不可用" }),
    ).toBeVisible();
    expect(screen.getByText(/当前地址不存在/)).toBeVisible();
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.queryByText("品牌知识")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "IP 数字资产中心" }),
    ).not.toBeInTheDocument();
    expect(routeMocks.consoleRender).not.toHaveBeenCalled();
    expect(routeMocks.ipAssetRender).not.toHaveBeenCalled();
    await waitFor(() => expect(document.title).toBe("页面未找到"));
  });

  it("restores the previous document title when the standalone route unmounts", async () => {
    document.title = "Previous local title";
    const view = renderPath("/ip-assets", true, true);
    await screen.findByRole("heading", { name: "IP 数字资产中心" });
    await waitFor(() => expect(document.title).toBe("IP 数字资产中心"));

    view.unmount();

    expect(document.title).toBe("Previous local title");
  });
});
