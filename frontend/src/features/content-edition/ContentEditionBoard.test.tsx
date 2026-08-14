import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import type { PropsWithChildren } from "react";
import { describe, expect, it, vi } from "vitest";

import { contentEditionFixture } from "./api.test";

const apiMocks = vi.hoisted(() => ({ getContentEdition: vi.fn() }));

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getContentEdition: apiMocks.getContentEdition,
}));

import { mapContentEdition } from "./api";
import { ContentEditionBoard } from "./ContentEditionBoard";

function Providers({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderBoard() {
  apiMocks.getContentEdition.mockResolvedValue(
    mapContentEdition(contentEditionFixture),
  );
  return render(<ContentEditionBoard />, { wrapper: Providers });
}

describe("ContentEditionBoard", () => {
  it("shows three columns, explicit empty positions and isolated sibling failures", async () => {
    const user = userEvent.setup();
    renderBoard();

    expect(
      await screen.findByRole("heading", { name: "科教晨报" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "午间观察" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "晚间精选" }),
    ).toBeInTheDocument();
    expect(screen.getByText("本栏目暂无独立素材")).toBeInTheDocument();
    expect(screen.getByText("该条生产失败")).toBeInTheDocument();
    expect(screen.getByText("已投递")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /权威原文/ })).toHaveLength(4);
    expect(
      screen.queryByRole("button", { name: /发布/ }),
    ).not.toBeInTheDocument();

    const dateInput = screen.getByLabelText("业务日期（上海时区）");
    await user.clear(dateInput);
    await user.type(dateInput, "2026-08-15");
    expect(apiMocks.getContentEdition).toHaveBeenCalled();
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = renderBoard();
    await screen.findByRole("heading", { name: "科教晨报" });
    const results = await axe(container);

    expect(results.violations).toEqual([]);
  });
});
