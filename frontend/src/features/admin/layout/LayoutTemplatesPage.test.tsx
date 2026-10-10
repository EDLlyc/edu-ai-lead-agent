import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";

import { AdminSessionExpiredError } from "../api";
import type { LayoutApi, LayoutTemplate } from "./api";
import { LayoutTemplatesPage } from "./LayoutTemplatesPage";

const TEMPLATES: readonly LayoutTemplate[] = [
  {
    id: "xiaosai-blue",
    name: "小赛蓝（默认）",
    description: "现在一直在用的蓝色版式。",
    swatches: ["#0D57C8", "#285ACE", "#22D7D6", "#29B6EE"],
    is_default: true,
  },
  {
    id: "jade-green",
    name: "青绿",
    description: "青绿色为主。",
    swatches: ["#0B7A64", "#11806A", "#3CCFB0", "#2BB39A"],
    is_default: false,
  },
];
const ACCOUNT = {
  id: "00000000-0000-0000-0000-0000000000a1",
  name: "赛先生",
  layout_template_id: "xiaosai-blue",
};

function fakeApi(overrides: Partial<LayoutApi> = {}) {
  return {
    list: vi.fn(() =>
      Promise.resolve({ templates: TEMPLATES, accounts: [ACCOUNT] }),
    ),
    preview: vi.fn((id: string) =>
      Promise.resolve(`<section data-template="${id}">示例</section>`),
    ),
    choose: vi.fn((_account: string, templateId: string) =>
      Promise.resolve({ ...ACCOUNT, layout_template_id: templateId }),
    ),
    ...overrides,
  } satisfies LayoutApi;
}

describe("排版模板", () => {
  it("previews the account's template, then switches it", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    const view = render(
      <LayoutTemplatesPage api={api} onSessionExpired={vi.fn()} />,
    );

    expect(
      await screen.findByText("小赛蓝（默认）", { selector: "p strong" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /小赛蓝/ })).toBeChecked();
    expect(
      screen.getByText(/未检测草稿服务的实时运行状态/),
    ).toBeInTheDocument();
    const uploadRules = screen.getByText(/重试沿用首次选择，已有草稿不变/);
    expect(uploadRules).not.toBeVisible();
    await user.click(screen.getByText("使用说明：新草稿、重试与已有草稿"));
    expect(uploadRules).toBeVisible();
    expect(uploadRules).toHaveTextContent("新草稿首次上传时读取这里的选择");
    const frame = await screen.findByTitle("排版预览：小赛蓝（默认）");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame.getAttribute("srcdoc")).toContain(
      'data-template="xiaosai-blue"',
    );
    expect(
      screen.getByRole("button", { name: "已保存这个模板" }),
    ).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: /青绿/ }));
    const green = await screen.findByTitle("排版预览：青绿");
    expect(green.getAttribute("srcdoc")).toContain(
      'data-template="jade-green"',
    );
    // jsdom frames cannot run axe; the frame holds only the sample article.
    expect((await axe(view.container, { iframes: false })).violations).toEqual(
      [],
    );

    await user.click(
      screen.getByRole("button", { name: "给「赛先生」保存「青绿」" }),
    );
    expect(api.choose).toHaveBeenCalledWith(ACCOUNT.id, "jade-green");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "「赛先生」的模板已保存为「青绿」",
    );
    expect(
      screen.getByText("青绿", { selector: "p strong" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "已保存这个模板" }),
    ).toBeDisabled();
  });

  it("still previews without a bound account but cannot enable", async () => {
    render(
      <LayoutTemplatesPage
        api={fakeApi({
          list: vi.fn(() =>
            Promise.resolve({ templates: TEMPLATES, accounts: [] }),
          ),
        })}
        onSessionExpired={vi.fn()}
      />,
    );
    expect(await screen.findByText(/还没有可用的公众号/)).toBeInTheDocument();
    expect(
      await screen.findByTitle("排版预览：小赛蓝（默认）"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows a refusal and hands an expired session back", async () => {
    const user = userEvent.setup();
    render(
      <LayoutTemplatesPage
        api={fakeApi({
          choose: vi.fn(() => Promise.reject(new Error("没有这个排版模板"))),
        })}
        onSessionExpired={vi.fn()}
      />,
    );
    await user.click(await screen.findByRole("radio", { name: /青绿/ }));
    await user.click(screen.getByRole("button", { name: /保存「青绿」/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "没有这个排版模板",
    );

    const expired = vi.fn();
    render(
      <LayoutTemplatesPage
        api={fakeApi({
          list: vi.fn(() => Promise.reject(new AdminSessionExpiredError())),
        })}
        onSessionExpired={expired}
      />,
    );
    await vi.waitFor(() => expect(expired).toHaveBeenCalled());
  });
});
