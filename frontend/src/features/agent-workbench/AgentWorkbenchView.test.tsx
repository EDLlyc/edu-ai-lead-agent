import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { AgentWorkbenchView } from "./AgentWorkbenchView";
import { agentWorkbenchFixtureRun } from "./fixture";
import type {
  AgentWorkbenchRunViewModel,
  AgentWorkbenchScreenState,
} from "./view-model";

const completedRun: AgentWorkbenchRunViewModel = {
  ...agentWorkbenchFixtureRun,
  claims: agentWorkbenchFixtureRun.claims.map((claim) =>
    claim.id === "claim-2"
      ? {
          ...claim,
          text: '<img src=x onerror="window.__unsafe=true"> 品牌表达应保持克制。',
        }
      : claim,
  ),
};

function StatefulView({
  initialState = { kind: "idle" },
}: Readonly<{ initialState?: AgentWorkbenchScreenState }>) {
  const [query, setQuery] = useState("");
  return (
    <AgentWorkbenchView
      state={initialState}
      query={query}
      onQueryChange={setQuery}
      onRun={vi.fn()}
      onCancel={vi.fn()}
    />
  );
}

describe("AgentWorkbenchView", () => {
  it("offers bounded presets and native keyboard-operable controls", async () => {
    const user = userEvent.setup();
    const onRun = vi.fn();
    render(
      <AgentWorkbenchView
        state={{ kind: "idle" }}
        query=""
        onQueryChange={vi.fn()}
        onRun={onRun}
        onCancel={vi.fn()}
      />,
    );

    const query = screen.getByRole("textbox", { name: "向受控 Agent 提问" });
    expect(query).toHaveAttribute("maxlength", "500");
    expect(screen.getByRole("button", { name: "运行受控分析" })).toBeDisabled();
    expect(screen.getByText("≤ 4 MODEL STEPS")).toBeVisible();
    expect(screen.getByText("ZERO BUSINESS WRITES")).toBeVisible();

    await user.tab();
    expect(query).toHaveFocus();
  });

  it("applies a fixture-safe preset without initiating a run", async () => {
    const user = userEvent.setup();
    render(<StatefulView />);

    await user.click(screen.getByRole("button", { name: "01 证据核验" }));

    expect(screen.getByRole("textbox")).toHaveValue(
      "这条 AI 教育事件有哪些可靠证据，适合怎样向家长解释？",
    );
    expect(screen.getByRole("button", { name: "01 证据核验" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("renders the claim-used catalog, trace, and telemetry as safe text", async () => {
    const { container } = render(
      <AgentWorkbenchView
        state={{
          kind: "completed",
          query: "核验事件并说明品牌表达边界",
          run: completedRun,
        }}
        query="核验事件并说明品牌表达边界"
        onQueryChange={vi.fn()}
        onRun={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "分析已完成" })).toHaveFocus(),
    );
    expect(screen.getByText(/<img src=x onerror=/)).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("可用于事实证据")).toBeVisible();
    expect(screen.getByText("仅用于表达，不可证明事实")).toBeVisible();
    expect(screen.getByText("3 / 4")).toBeVisible();
    expect(screen.getByText("2 / 4")).toBeVisible();
    expect(screen.getByText("315 ms")).toBeVisible();
    expect(screen.getAllByText("检索事实证据").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /查看来源/ })).toHaveAttribute(
      "href",
      "https://example.edu.cn/policy/ai-education",
    );
    expect(screen.getByRole("link", { name: /查看来源/ })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(screen.queryByRole("button", { name: /发布|发送|投递/ })).toBeNull();
  });

  it("announces budget exhaustion using text rather than color alone", () => {
    const budgetRun: AgentWorkbenchRunViewModel = {
      ...completedRun,
      status: "budget-exhausted",
      statusLabel: "步骤预算已用尽",
      summary: "四步内没有获得足够证据，已停止运行。",
      claims: [],
      citations: [],
      metrics: { ...completedRun.metrics, modelSteps: 4, toolCalls: 4 },
    };
    render(
      <AgentWorkbenchView
        state={{
          kind: "budget-exhausted",
          query: "继续调用第五个工具",
          run: budgetRun,
        }}
        query="继续调用第五个工具"
        onQueryChange={vi.fn()}
        onRun={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "工作台已达到四步预算并停止。",
    );
    expect(screen.getAllByText("步骤预算已用尽").length).toBeGreaterThan(0);
    expect(screen.getAllByText("4 / 4")).toHaveLength(2);
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = render(
      <AgentWorkbenchView
        state={{
          kind: "completed",
          query: "核验事件并说明品牌表达边界",
          run: completedRun,
        }}
        query="核验事件并说明品牌表达边界"
        onQueryChange={vi.fn()}
        onRun={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
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
