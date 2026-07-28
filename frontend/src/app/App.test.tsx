import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("development environment shell", () => {
  it("presents the configured environment without claiming business behavior", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { level: 1, name: /开发环境/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("环境壳，不是业务流水线")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /发布/ }),
    ).not.toBeInTheDocument();
  });

  it("announces copied commands", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getAllByRole("button", { name: "复制" })[0]!);

    expect(await screen.findByText("已复制：make setup")).toHaveAttribute(
      "role",
      "status",
    );
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = render(<App />);
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
