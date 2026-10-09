import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";

import { DRAFT, fakeWeChatApi, job } from "./testApi";
import { WeChatPublishPage } from "./WeChatPublishPage";

describe("公众号发布", () => {
  it("publishes a draft now only after two confirmations", async () => {
    const user = userEvent.setup();
    const calls = fakeWeChatApi();
    const view = render(
      <WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />,
    );
    const drafts = await screen.findByRole("list", { name: "草稿" });
    expect(drafts).toHaveTextContent("科学营开营");
    expect((await axe(view.container)).violations).toEqual([]);

    await user.click(within(drafts).getByRole("button", { name: "立即发布" }));
    await user.click(within(drafts).getByRole("button", { name: "下一步" }));
    const final = within(drafts).getByRole("alertdialog", {
      name: "再次确认发布",
    });
    expect(final).toHaveTextContent("发出后不能撤回");
    expect(calls.publish).not.toHaveBeenCalled();
    await user.click(within(final).getByRole("button", { name: "确认发布" }));

    expect(calls.publish).toHaveBeenCalledWith({
      accountId: "00000000-0000-0000-0000-0000000000a1",
      mediaId: "M1",
      title: "科学营开营",
      scheduledAt: null,
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "已提交「科学营开营」",
    );
    expect(screen.getByRole("tab", { name: "发布记录" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("schedules in Beijing time and lets a scheduled job be cancelled", async () => {
    const user = userEvent.setup();
    const calls = fakeWeChatApi({
      publish: vi.fn(() =>
        Promise.resolve(
          job({ status: "scheduled", scheduled_at: "2026-10-10T00:30:00Z" }),
        ),
      ),
      jobs: vi.fn(() =>
        Promise.resolve([
          job({ status: "scheduled", scheduled_at: "2026-10-10T00:30:00Z" }),
        ]),
      ),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    const drafts = await screen.findByRole("list", { name: "草稿" });
    await user.click(within(drafts).getByRole("button", { name: "定时发布" }));
    const time = within(drafts).getByLabelText(/发布时间/);
    await user.clear(time);
    await user.type(time, "2026-10-10T08:30");
    await user.click(within(drafts).getByRole("button", { name: "下一步" }));
    await user.click(within(drafts).getByRole("button", { name: "确认排期" }));
    expect(calls.publish).toHaveBeenCalledWith(
      expect.objectContaining({ scheduledAt: "2026-10-10T00:30:00.000Z" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "已排期：10/10 08:30",
    );

    const row = (await screen.findAllByRole("row"))[1]!;
    expect(row).toHaveTextContent("等待定时发布");
    await user.click(within(row).getByRole("button", { name: "取消" }));
    await waitFor(() => expect(calls.cancel).toHaveBeenCalledWith(job().id));
  });

  it("shows results, failures and the published list", async () => {
    const user = userEvent.setup();
    const calls = fakeWeChatApi({
      drafts: vi.fn(() =>
        Promise.resolve({
          total: 1,
          items: [{ ...DRAFT, open_job_id: job().id }],
        }),
      ),
      jobs: vi.fn(() =>
        Promise.resolve([
          job({
            status: "succeeded",
            article_url: "https://mp.weixin.qq.com/s/art1",
          }),
          job({
            id: "x2",
            title: "第二篇",
            status: "failed",
            error: "平台审核不通过",
          }),
        ]),
      ),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    expect(
      await screen.findByText("已在发布或排期中，见「发布记录」"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "发布记录" }));
    const rows = await screen.findAllByRole("row");
    expect(
      within(rows[1]!).getByRole("link", { name: "科学营开营" }),
    ).toHaveAttribute("href", "https://mp.weixin.qq.com/s/art1");
    expect(rows[2]).toHaveTextContent("发布失败：平台审核不通过");

    await user.click(screen.getByRole("tab", { name: "已发布" }));
    expect(
      await screen.findByRole("link", { name: "已发布的一篇" }),
    ).toBeInTheDocument();
  });

  it("asks for an account to be bound first", async () => {
    render(
      <WeChatPublishPage
        api={fakeWeChatApi({ options: vi.fn(() => Promise.resolve([])) })}
        onSessionExpired={vi.fn()}
      />,
    );
    expect(await screen.findByText(/还没有可用的公众号/)).toBeInTheDocument();
  });
});
