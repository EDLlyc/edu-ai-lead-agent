import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminSessionExpiredError } from "../api";
import { UnsavedChangesProvider } from "../unsaved/UnsavedChanges";
import type { WeChatApi, WeChatDraft, WeChatPublished } from "./api";
import { ACCOUNT, DRAFT, fakeWeChatApi, job } from "./testApi";
import { WeChatPublishPage } from "./WeChatPublishPage";

const DRAFTS: readonly WeChatDraft[] = Array.from(
  { length: 45 },
  (_, index) => ({
    ...DRAFT,
    media_id: `draft-${index + 1}`,
    articles: [{ title: `草稿第 ${index + 1} 篇`, author: "", digest: "" }],
  }),
);
const PUBLISHED: readonly WeChatPublished[] = Array.from(
  { length: 45 },
  (_, index) => ({
    article_id: `published-${index + 1}`,
    updated_at: DRAFT.updated_at,
    articles: [
      {
        title: `文章第 ${index + 1} 篇`,
        url: `https://mp.weixin.qq.com/s/${index + 1}`,
      },
    ],
  }),
);
const OPTIONS = [
  { id: ACCOUNT.id, name: ACCOUNT.name, topics: ACCOUNT.topics },
  { id: "second-account", name: "第二公众号", topics: [] },
];

function deferred<T>() {
  let resolve: ((value: T) => void) | undefined;
  let reject: ((error: unknown) => void) | undefined;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return {
    promise,
    resolve: (value: T) => {
      if (!resolve) throw new Error("Promise not initialized");
      resolve(value);
    },
    reject: (error: unknown) => {
      if (!reject) throw new Error("Promise not initialized");
      reject(error);
    },
  };
}

function paginatedApi(overrides: Partial<WeChatApi> = {}) {
  return fakeWeChatApi({
    drafts: vi.fn<WeChatApi["drafts"]>((_account, offset) =>
      Promise.resolve({
        total: DRAFTS.length,
        items: DRAFTS.slice(offset, offset + 20),
      }),
    ),
    published: vi.fn<WeChatApi["published"]>((_account, offset) =>
      Promise.resolve({
        total: PUBLISHED.length,
        items: PUBLISHED.slice(offset, offset + 20),
      }),
    ),
    ...overrides,
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("公众号列表分页", () => {
  it("reaches all 45 drafts and published records and resets the view to page one", async () => {
    const user = userEvent.setup();
    const calls = paginatedApi();
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    let list = await screen.findByRole("list", { name: "草稿" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(20);
    expect(
      screen.getByRole("navigation", { name: "草稿分页" }),
    ).toHaveTextContent("共 45 条记录 · 第 1–20 条 · 第 1/3 页");
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(await screen.findByText("草稿第 21 篇")).toBeInTheDocument();
    expect(screen.queryByText("草稿第 1 篇")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(await screen.findByText("草稿第 45 篇")).toBeInTheDocument();
    list = screen.getByRole("list", { name: "草稿" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
    expect(
      screen.getByRole("navigation", { name: "草稿分页" }),
    ).toHaveTextContent("第 41–45 条 · 第 3/3 页");
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(calls.drafts).toHaveBeenLastCalledWith(ACCOUNT.id, 40);
    await user.click(screen.getByRole("button", { name: "上一页" }));
    expect(await screen.findByText("草稿第 21 篇")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "已发布" }));
    expect(
      await screen.findByRole("link", { name: "文章第 1 篇" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(
      await screen.findByRole("link", { name: "文章第 21 篇" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(
      await screen.findByRole("link", { name: "文章第 45 篇" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "已发布的文章" })).toHaveAttribute(
      "start",
      "41",
    );
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(calls.published).toHaveBeenLastCalledWith(ACCOUNT.id, 40);
    await user.click(screen.getByRole("tab", { name: "草稿箱" }));
    expect(await screen.findByText("草稿第 1 篇")).toBeInTheDocument();
    expect(calls.drafts).toHaveBeenLastCalledWith(ACCOUNT.id, 0);
    expect(calls.publish).not.toHaveBeenCalled();
  });

  it("corrects a removed final page and then an emptied collection using the new total", async () => {
    const user = userEvent.setup();
    let total = 45;
    const calls = paginatedApi({
      drafts: vi.fn<WeChatApi["drafts"]>((_account, offset) =>
        Promise.resolve({
          total,
          items: DRAFTS.slice(offset, Math.min(offset + 20, total)),
        }),
      ),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("草稿第 1 篇");
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("草稿第 21 篇");
    total = 21;
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() =>
      expect(calls.drafts).toHaveBeenLastCalledWith(ACCOUNT.id, 20),
    );
    expect(
      await screen.findByText(/共 21 条记录 · 第 21–21 条/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    total = 0;
    await user.click(screen.getByRole("button", { name: "上一页" }));
    expect(await screen.findByText("草稿箱是空的。")).toBeInTheDocument();
    expect(screen.getByText("共 0 条记录")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });

  it("hides stale page actions on failure and retries the failed offset", async () => {
    const user = userEvent.setup();
    let fail = true;
    const calls = paginatedApi({
      drafts: vi.fn<WeChatApi["drafts"]>((_account, offset) =>
        offset === 20 && fail
          ? Promise.reject(new Error("草稿读取失败"))
          : Promise.resolve({
              total: 45,
              items: DRAFTS.slice(offset, offset + 20),
            }),
      ),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("草稿第 1 篇");
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("草稿读取失败");
    expect(
      screen.queryByRole("button", { name: "立即发布" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("草稿第 1 篇")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上一页" })).toBeEnabled();
    fail = false;
    await user.click(screen.getByRole("button", { name: "重试读取" }));
    expect(await screen.findByText("草稿第 21 篇")).toBeInTheDocument();
    expect(calls.drafts).toHaveBeenLastCalledWith(ACCOUNT.id, 20);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("isolates a delayed page after account switching and confirms only the new account's draft", async () => {
    const user = userEvent.setup();
    const late = deferred<Awaited<ReturnType<WeChatApi["drafts"]>>>();
    const next = {
      ...DRAFT,
      media_id: "second-draft",
      articles: [{ title: "第二公众号的草稿", author: "", digest: "" }],
    };
    const calls = paginatedApi({
      options: vi.fn(() => Promise.resolve(OPTIONS)),
      drafts: vi.fn<WeChatApi["drafts"]>((account, offset) =>
        account !== ACCOUNT.id
          ? Promise.resolve({ total: 1, items: [next] })
          : offset === 20
            ? late.promise
            : Promise.resolve({ total: 45, items: DRAFTS.slice(0, 20) }),
      ),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("草稿第 1 篇");
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(
      screen.queryByRole("button", { name: "立即发布" }),
    ).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("公众号"), "second-account");
    expect(await screen.findByText("第二公众号的草稿")).toBeInTheDocument();
    await act(async () => {
      late.resolve({ total: 45, items: DRAFTS.slice(20, 40) });
      await late.promise;
    });
    expect(screen.queryByText("草稿第 21 篇")).not.toBeInTheDocument();
    expect(screen.getByText(/共 1 条记录/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "立即发布" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(
      screen.getByRole("alertdialog", { name: "再次确认发布" }),
    ).toHaveTextContent("公众号：第二公众号");
    await user.click(screen.getByRole("button", { name: "确认发布" }));
    expect(calls.publish).toHaveBeenCalledTimes(1);
    expect(calls.publish).toHaveBeenCalledWith(
      expect.objectContaining({
        accountId: "second-account",
        mediaId: "second-draft",
      }),
    );
  });

  it("ignores an old view's delayed rejection when published records are ready", async () => {
    const user = userEvent.setup();
    const late = deferred<Awaited<ReturnType<WeChatApi["drafts"]>>>();
    const calls = paginatedApi({ drafts: vi.fn(() => late.promise) });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    await waitFor(() => expect(calls.drafts).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: "已发布" }));
    await screen.findByRole("link", { name: "文章第 1 篇" });
    await act(async () => {
      late.reject(new Error("旧请求失败"));
      await late.promise.catch(() => undefined);
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "已发布分页" }),
    ).toHaveTextContent("共 45 条记录");
    expect(
      screen.queryByRole("button", { name: "立即发布" }),
    ).not.toBeInTheDocument();
  });

  it.each(["account", "tab"] as const)(
    "waits for fresh data when returning through a pending %s context",
    async (target) => {
      const user = userEvent.setup();
      const returning = deferred<Awaited<ReturnType<WeChatApi["drafts"]>>>();
      const other = deferred<Awaited<ReturnType<WeChatApi["drafts"]>>>();
      const otherPublished =
        deferred<Awaited<ReturnType<WeChatApi["published"]>>>();
      let firstVisits = 0;
      const calls = fakeWeChatApi({
        options: vi.fn(() => Promise.resolve(OPTIONS)),
        drafts: vi.fn<WeChatApi["drafts"]>((account) => {
          if (account !== ACCOUNT.id) return other.promise;
          firstVisits += 1;
          return firstVisits === 1
            ? Promise.resolve({ total: 1, items: [DRAFT] })
            : returning.promise;
        }),
        published: vi.fn(() => otherPublished.promise),
      });
      render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
      await screen.findByRole("button", { name: "立即发布" });
      if (target === "account") {
        await user.selectOptions(
          screen.getByLabelText("公众号"),
          "second-account",
        );
        await user.selectOptions(screen.getByLabelText("公众号"), ACCOUNT.id);
      } else {
        await user.click(screen.getByRole("tab", { name: "已发布" }));
        await user.click(screen.getByRole("tab", { name: "草稿箱" }));
      }
      await waitFor(() => expect(firstVisits).toBe(2));
      expect(
        screen.queryByRole("button", { name: "立即发布" }),
      ).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
      await act(async () => {
        // Another operator occupied this draft while this page was away.
        returning.resolve({
          total: 1,
          items: [{ ...DRAFT, open_job_id: job().id }],
        });
        await returning.promise;
      });
      expect(
        await screen.findByText("已发布、正在发布或结果待核对，见「发布记录」"),
      ).toBeInTheDocument();
      expect(calls.publish).not.toHaveBeenCalled();
    },
  );

  it("waits for the account's records before allowing draft actions, and forces expired sessions", async () => {
    const user = userEvent.setup();
    const records = deferred<Awaited<ReturnType<WeChatApi["jobs"]>>>();
    const expired = vi.fn();
    const calls = fakeWeChatApi({
      jobs: vi.fn(() => records.promise),
      published: vi.fn(() => Promise.reject(new AdminSessionExpiredError())),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={expired} />);
    await waitFor(() => expect(calls.drafts).toHaveBeenCalled());
    expect(
      screen.queryByRole("button", { name: "立即发布" }),
    ).not.toBeInTheDocument();
    await act(async () => {
      records.resolve([]);
      await records.promise;
    });
    expect(
      await screen.findByRole("button", { name: "立即发布" }),
    ).toBeEnabled();
    await user.click(screen.getByRole("tab", { name: "已发布" }));
    await waitFor(() => expect(expired).toHaveBeenCalledOnce());
    expect(calls.publish).not.toHaveBeenCalled();
  });

  it("keeps a pending publication bound to its context until explicitly discarded, and submits only once", async () => {
    const user = userEvent.setup();
    const result = deferred<Awaited<ReturnType<WeChatApi["publish"]>>>();
    const calls = fakeWeChatApi({
      options: vi.fn(() => Promise.resolve(OPTIONS)),
      publish: vi.fn(() => result.promise),
    });
    render(
      <UnsavedChangesProvider>
        <WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />
      </UnsavedChangesProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "立即发布" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.selectOptions(screen.getByLabelText("公众号"), "second-account");
    expect(
      screen.getByRole("alertdialog", { name: "有未保存的修改" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("公众号")).toHaveValue(ACCOUNT.id);
    await user.dblClick(screen.getByRole("button", { name: "确认发布" }));
    expect(calls.publish).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("公众号")).toBeDisabled();
    expect(screen.getByRole("tab", { name: "已发布" })).toBeDisabled();
    await act(async () => {
      result.resolve(job());
      await result.promise;
    });
    expect(await screen.findByRole("status")).toHaveTextContent("已提交");
    await user.click(screen.getByRole("tab", { name: "已发布" }));
    expect(
      screen.queryByRole("alertdialog", { name: "有未保存的修改" }),
    ).not.toBeInTheDocument();
  });

  it("preserves failed reconciliation edits until a tab change or cancel is explicitly discarded", async () => {
    const user = userEvent.setup();
    const calls = fakeWeChatApi({
      jobs: vi.fn(() => Promise.resolve([job({ status: "outcome_unknown" })])),
      reconcile: vi.fn(() => Promise.reject(new Error("保存失败，请重试"))),
    });
    render(
      <UnsavedChangesProvider>
        <WeChatPublishPage
          api={calls}
          onSessionExpired={vi.fn()}
          canReconcile
        />
      </UnsavedChangesProvider>,
    );
    await screen.findByRole("list", { name: "草稿" });
    await user.click(screen.getByRole("tab", { name: "发布记录" }));
    await user.click(
      await screen.findByRole("button", { name: "记录人工核对" }),
    );
    await user.type(screen.getByLabelText("核对依据"), "已经核对微信后台");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "保存核对结果" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("保存失败");
    await user.click(screen.getByRole("tab", { name: "草稿箱" }));
    await user.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("核对依据")).toHaveValue("已经核对微信后台");
    await user.click(screen.getByRole("button", { name: "取消核对" }));
    await user.click(screen.getByRole("button", { name: "放弃修改并继续" }));
    expect(
      screen.queryByRole("form", { name: "记录人工核对" }),
    ).not.toBeInTheDocument();
    expect(calls.publish).not.toHaveBeenCalled();
  });

  it("polls open records, stops on terminal status and clears the timer on unmount", async () => {
    vi.useFakeTimers();
    const calls = fakeWeChatApi({
      jobs: vi
        .fn<WeChatApi["jobs"]>()
        .mockResolvedValueOnce([job()])
        .mockResolvedValue([job({ status: "succeeded" })]),
    });
    const view = render(
      <WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />,
    );
    await act(() => Promise.resolve());
    expect(calls.jobs).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(calls.jobs).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(calls.jobs).toHaveBeenCalledTimes(2);
    view.unmount();
    const open = fakeWeChatApi({ jobs: vi.fn(() => Promise.resolve([job()])) });
    const second = render(
      <WeChatPublishPage api={open} onSessionExpired={vi.fn()} />,
    );
    await act(() => Promise.resolve());
    second.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(open.jobs).toHaveBeenCalledTimes(1);
  });

  it("disables an already-reviewed draft when a refresh discovers an occupied publication", async () => {
    vi.useFakeTimers();
    const calls = fakeWeChatApi({
      drafts: vi
        .fn<WeChatApi["drafts"]>()
        .mockResolvedValueOnce({ total: 1, items: [DRAFT] })
        .mockResolvedValue({
          total: 1,
          items: [{ ...DRAFT, open_job_id: job().id }],
        }),
      jobs: vi.fn(() => Promise.resolve([job()])),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    await act(() => Promise.resolve());
    fireEvent.click(screen.getByRole("button", { name: "立即发布" }));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByRole("button", { name: "确认发布" })).toBeEnabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(screen.getByRole("button", { name: "确认发布" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "草稿内容已更新或已有发布记录",
    );
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    expect(
      screen.getByText("已发布、正在发布或结果待核对，见「发布记录」"),
    ).toBeInTheDocument();
    expect(calls.publish).not.toHaveBeenCalled();
  });
});
