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
    expect(final).toHaveTextContent("公众号：赛先生");
    expect(final).toHaveTextContent("不会向粉丝群发");
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
      await screen.findByText("已发布、正在发布或结果待核对，见「发布记录」"),
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
  it("confirms every article and the selected account for multi-article publication", async () => {
    const user = userEvent.setup();
    const calls = fakeWeChatApi({
      drafts: vi.fn(() =>
        Promise.resolve({
          total: 1,
          items: [
            {
              ...DRAFT,
              articles: [
                ...DRAFT.articles,
                { title: "第二篇机器人课堂", author: "", digest: "" },
              ],
            },
          ],
        }),
      ),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "立即发布" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    const final = screen.getByRole("alertdialog", { name: "再次确认发布" });
    expect(final).toHaveTextContent("赛先生");
    const titles = within(final).getByRole("list", {
      name: "本次发布的全部篇目",
    });
    expect(within(titles).getAllByRole("listitem")).toHaveLength(2);
    expect(titles).toHaveTextContent("科学营开营");
    expect(titles).toHaveTextContent("第二篇机器人课堂");
    expect(final).toHaveTextContent("不会向粉丝群发");
    expect(final).not.toHaveTextContent("发给所有关注者");
    expect(calls.publish).not.toHaveBeenCalled();
  });

  it("rechecks an uncertain result without resubmitting the draft", async () => {
    const user = userEvent.setup();
    const calls = fakeWeChatApi({
      jobs: vi.fn(() =>
        Promise.resolve([
          job({ status: "outcome_unknown", can_recheck: true }),
        ]),
      ),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByRole("list", { name: "草稿" });
    await user.click(screen.getByRole("tab", { name: "发布记录" }));
    await user.click(
      await screen.findByRole("button", { name: "重新查询结果" }),
    );
    expect(calls.recheck).toHaveBeenCalledWith(job().id);
    expect(calls.publish).not.toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "查询结果：已发布",
    );
    expect(
      screen.queryByRole("button", { name: "记录人工核对" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("请管理员记录核对结果。")).toBeInTheDocument();
  });

  it("requires verification evidence and explicit confirmation to release an unknown draft", async () => {
    const user = userEvent.setup();
    const uncertain = job({ status: "outcome_unknown", can_recheck: false });
    const calls = fakeWeChatApi({
      jobs: vi.fn(() => Promise.resolve([uncertain])),
    });
    const view = render(
      <WeChatPublishPage api={calls} onSessionExpired={vi.fn()} canReconcile />,
    );
    await screen.findByRole("list", { name: "草稿" });
    await user.click(screen.getByRole("tab", { name: "发布记录" }));
    expect(
      screen.queryByRole("button", { name: "重新查询结果" }),
    ).not.toBeInTheDocument();
    await user.click(
      await screen.findByRole("button", { name: "记录人工核对" }),
    );
    const form = screen.getByRole("form", { name: "记录人工核对" });
    const save = within(form).getByRole("button", { name: "保存核对结果" });
    expect(save).toBeDisabled();
    await user.selectOptions(
      within(form).getByLabelText("核对结果"),
      "not_published",
    );
    await user.type(
      within(form).getByLabelText("核对依据"),
      "已核对微信后台，文章未发布",
    );
    expect(save).toBeDisabled();
    await user.click(within(form).getByRole("checkbox"));
    expect((await axe(view.container)).violations).toEqual([]);
    await user.click(save);
    expect(calls.reconcile).toHaveBeenCalledWith(uncertain.id, {
      result: "not_published",
      note: "已核对微信后台，文章未发布",
      confirmed: true,
      expected_updated_at: uncertain.updated_at,
    });
    expect(calls.publish).not.toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "可以返回草稿箱重新提交",
    );
  });

  it("distinguishes an operator-verified publication from a provider query result", async () => {
    const user = userEvent.setup();
    const calls = fakeWeChatApi({
      jobs: vi.fn(() =>
        Promise.resolve([
          job({
            status: "succeeded",
            can_recheck: false,
            reconciled_by: "老师",
            reconciliation_note: "已在公众号后台核对文章链接",
          }),
        ]),
      ),
    });
    render(
      <WeChatPublishPage api={calls} onSessionExpired={vi.fn()} canReconcile />,
    );
    await screen.findByRole("list", { name: "草稿" });
    await user.click(screen.getByRole("tab", { name: "发布记录" }));
    expect(await screen.findByText("人工核对已发布")).toBeInTheDocument();
    expect(
      screen.getByText("核对依据：已在公众号后台核对文章链接"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "记录人工核对" }),
    ).not.toBeInTheDocument();
  });
  it("returns to records after losing the submit response instead of leaving a resubmit button", async () => {
    const user = userEvent.setup();
    const calls = fakeWeChatApi({
      publish: vi.fn(() =>
        Promise.reject(new Error("连接中断，请核对发布记录")),
      ),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "立即发布" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("button", { name: "确认发布" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("连接中断");
    expect(screen.getByRole("tab", { name: "发布记录" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.queryByRole("button", { name: "确认发布" }),
    ).not.toBeInTheDocument();
    expect(calls.publish).toHaveBeenCalledTimes(1);
  });
});
