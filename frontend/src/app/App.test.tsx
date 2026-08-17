import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  activateBrandVersion: vi.fn(),
  deactivateBrandDocument: vi.fn(),
  listBrandDocuments: vi.fn(() => Promise.resolve({ items: [], count: 0 })),
  retrieveBrandContext: vi.fn(),
  uploadBrandDocument: vi.fn(() =>
    Promise.resolve({
      created: true,
      document_id: "00000000-0000-4000-8000-000000000001",
      document_url:
        "/api/v1/brand-documents/00000000-0000-4000-8000-000000000001",
      ingestion_job_id: "00000000-0000-4000-8000-000000000003",
      status: "queued",
      status_url:
        "/api/v1/brand-ingestion-jobs/00000000-0000-4000-8000-000000000003",
      version_id: "00000000-0000-4000-8000-000000000002",
    }),
  ),
}));

vi.mock("@/features/brand/api", () => apiMocks);

import { App } from "./App";

afterEach(() => {
  vi.unstubAllEnvs();
});

function TestProviders({ children }: PropsWithChildren) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function renderApp() {
  return render(<App />, { wrapper: TestProviders });
}

describe("brand knowledge workspace", () => {
  it("keeps the Agent workbench absent without an explicit local flag", () => {
    renderApp();

    expect(
      screen.queryByRole("heading", { name: "Agent 研究工作台" }),
    ).not.toBeInTheDocument();
  });

  it("loads the Agent workbench only after the local development opt-in", async () => {
    vi.stubEnv("VITE_AGENT_WORKBENCH_ENABLED", "true");
    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Agent 研究工作台" }),
    ).toBeInTheDocument();
    expect(screen.getByText("仅限本地开发")).toBeVisible();
  });

  it("positions brand retrieval as internal copy-generation context", async () => {
    renderApp();

    expect(
      screen.getByRole("heading", { level: 1, name: /品牌知识/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "文案上下文召回测试" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/不是面向家长的检索服务/)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "家长语境检索" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("品牌资料不能证明外部事实")).toBeInTheDocument();
    expect(screen.getByText(/最大 25 MiB/)).toBeInTheDocument();
    expect(await screen.findByText("等待第一份品牌资料")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /发布/ }),
    ).not.toBeInTheDocument();
  });

  it("uploads a controlled brand file and announces the durable job", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.type(screen.getByLabelText("文档标题"), "赛先生家长沟通规范");
    await user.upload(
      screen.getByLabelText(/^原始文件/),
      new File(["准确、克制、温暖"], "tone.md", { type: "text/markdown" }),
    );
    const submit = screen.getByRole("button", { name: "上传并建立新版本" });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.submit(screen.getByRole("form", { name: "上传品牌资料" }));

    await waitFor(() =>
      expect(apiMocks.uploadBrandDocument).toHaveBeenCalledOnce(),
    );
    expect(
      await screen.findByText(/00000000-0000-4000-8000-000000000003/),
    ).toHaveAttribute("role", "status");
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = renderApp();
    await screen.findByText("等待第一份品牌资料");
    const results = await axe(container);

    expect(
      results.violations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        targets: violation.nodes.map((node) => node.target),
      })),
    ).toEqual([]);
  });
});
