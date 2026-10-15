import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminNavigation } from "./AdminNavigation";
import { visibleSections } from "./sections";

function viewport(initialMobile = true) {
  let mobile = initialMobile;
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", () => ({
    get matches() {
      return mobile;
    },
    addEventListener: (_event: string, listener: () => void) =>
      listeners.add(listener),
    removeEventListener: (_event: string, listener: () => void) =>
      listeners.delete(listener),
  }));
  return (nextMobile: boolean) => {
    act(() => {
      mobile = nextMobile;
      for (const listener of listeners) listener();
    });
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("responsive admin navigation", () => {
  it("shows the current page, reveals all grouped links and restores focus with Escape", async () => {
    viewport();
    const user = userEvent.setup();
    const sections = visibleSections("owner");
    const view = render(
      <AdminNavigation
        sections={sections}
        current={sections.find((item) => item.key === "models")}
        path="/admin/models"
        navigate={vi.fn()}
      />,
    );
    const toggle = screen.getByRole("button", {
      name: "系统 模型配置 切换页面",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    await user.tab();
    expect(toggle).toHaveFocus();
    await user.keyboard("{Enter}");
    const menu = screen.getByRole("navigation", { name: "后台菜单" });
    expect(menu).toHaveAttribute("id", toggle.getAttribute("aria-controls"));
    expect(within(menu).getAllByRole("link")).toHaveLength(12);
    expect(
      within(menu).getByRole("link", { name: "模型配置" }),
    ).toHaveAttribute("aria-current", "page");
    expect((await axe(view.container)).violations).toEqual([]);
    await user.tab();
    expect(within(menu).getByRole("link", { name: "新闻源" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("collapses after an accepted route change and stays closed on return to a previously open page", async () => {
    viewport();
    const user = userEvent.setup();
    const sections = visibleSections("owner");
    const navigate = vi.fn();
    const page = (key: string) => (
      <AdminNavigation
        sections={sections}
        current={sections.find((item) => item.key === key)}
        path={`/admin/${key}`}
        navigate={navigate}
      />
    );
    const view = render(page("models"));
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("link", { name: "操作记录" }));
    expect(navigate).toHaveBeenCalledWith("/admin/audit");
    // The history owner decides when the transition is accepted.
    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "true");
    view.rerender(page("audit"));
    expect(
      screen.getByRole("button", { name: "系统 操作记录 切换页面" }),
    ).toHaveFocus();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    view.rerender(page("models"));
    expect(screen.getByRole("button")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("keeps editor destinations filtered and moves focus safely across the mobile breakpoint", async () => {
    const resize = viewport(false);
    const user = userEvent.setup();
    const sections = visibleSections("editor");
    render(
      <AdminNavigation
        sections={sections}
        current={sections[0]}
        path="/admin/sources"
        navigate={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(8);
    expect(
      screen.queryByRole("link", { name: "模型配置" }),
    ).not.toBeInTheDocument();
    const current = screen.getByRole("link", { name: "新闻源" });
    current.focus();
    resize(true);
    const toggle = screen.getByRole("button", {
      name: "内容来源 新闻源 切换页面",
    });
    expect(toggle).toHaveFocus();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    resize(false);
    expect(current).toHaveFocus();
    resize(true);
    await user.click(toggle);
    expect(screen.getAllByRole("link")).toHaveLength(8);
    await user.click(screen.getByRole("link", { name: "新闻源" }));
    expect(toggle).toHaveFocus();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});
