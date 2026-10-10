import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UnsavedChangesProvider } from "../unsaved/UnsavedChanges";
import type { PublishJobPage, WeChatApi } from "./api";
import { ACCOUNT, DRAFT, fakeWeChatApi, job } from "./testApi";
import { WeChatPublishPage } from "./WeChatPublishPage";

const RECORDS = Array.from({ length: 65 }, (_, index) =>
  job({
    id: `history-${index}`,
    title: `发布记录第 ${index + 1} 篇`,
    media_id: `M-${index}`,
    status: index % 2 ? "failed" : "succeeded",
    can_recheck: false,
  }),
);
function result(items = RECORDS, offset = 0): PublishJobPage {
  return {
    items: items.slice(offset, offset + 20),
    total: items.length,
    offset,
    limit: 20,
    business_timezone: "Asia/Shanghai",
  };
}
function paginated(overrides: Partial<WeChatApi> = {}) {
  return fakeWeChatApi({
    options: vi.fn(() =>
      Promise.resolve([
        { id: ACCOUNT.id, name: ACCOUNT.name, topics: [] },
        { id: "second", name: "第二公众号", topics: [] },
      ]),
    ),
    jobsPage: vi.fn<WeChatApi["jobsPage"]>((account, offset, filters) =>
      Promise.resolve(
        result(
          account === "second"
            ? []
            : RECORDS.filter(
                (item) => !filters.status || item.status === filters.status,
              ),
          offset,
        ),
      ),
    ),
    ...overrides,
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
async function openRecords(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("list", { name: "草稿" });
  await user.click(screen.getByRole("tab", { name: "发布记录" }));
}
afterEach(() => vi.useRealTimers());

describe("发布记录历史与筛选", () => {
  it("browses beyond 50 and resets pages for status, inclusive creation dates, account and tab", async () => {
    const user = userEvent.setup();
    const calls = paginated();
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    await openRecords(user);
    await screen.findByText("发布记录第 1 篇");
    expect(
      screen.getByRole("columnheader", { name: "创建时间" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("按北京时间筛选创建日期，包含起止当天。"),
    ).toBeInTheDocument();
    for (const first of [21, 41, 61]) {
      await user.click(screen.getByRole("button", { name: "下一页" }));
      await screen.findByText(`发布记录第 ${first} 篇`);
    }
    expect(screen.getAllByRole("row")).toHaveLength(6);
    expect(
      screen.getByRole("navigation", { name: "发布记录分页" }),
    ).toHaveTextContent("共 65 条记录 · 第 61–65 条 · 第 4/4 页");
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("发布状态"), "failed");
    await screen.findByText("发布记录第 2 篇");
    expect(calls.jobsPage).toHaveBeenLastCalledWith(ACCOUNT.id, 0, {
      status: "failed",
      dateFrom: "",
      dateTo: "",
    });
    expect(
      screen.getByRole("navigation", { name: "发布记录分页" }),
    ).toHaveTextContent("共 32 条记录 · 第 1–20 条");
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("发布记录第 42 篇");
    fireEvent.change(screen.getByLabelText("创建日期起"), {
      target: { value: "2026-10-09" },
    });
    fireEvent.change(screen.getByLabelText("创建日期止"), {
      target: { value: "2026-10-10" },
    });
    await waitFor(() =>
      expect(calls.jobsPage).toHaveBeenLastCalledWith(ACCOUNT.id, 0, {
        status: "failed",
        dateFrom: "2026-10-09",
        dateTo: "2026-10-10",
      }),
    );
    await user.selectOptions(screen.getByLabelText("公众号"), "second");
    expect(
      await screen.findByText("没有符合筛选条件的发布记录。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("公众号"), ACCOUNT.id);
    await screen.findByText("发布记录第 2 篇");
    await user.click(screen.getByRole("button", { name: "清除筛选" }));
    await screen.findByText("发布记录第 1 篇");
    expect(screen.getByLabelText("发布状态")).toHaveValue("");
    expect(screen.getByLabelText("创建日期起")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("发布记录第 21 篇");
    await user.click(screen.getByRole("tab", { name: "已发布" }));
    await screen.findByRole("link", { name: "已发布的一篇" });
    await user.click(screen.getByRole("tab", { name: "发布记录" }));
    await screen.findByText("发布记录第 1 篇");
    expect(calls.publish).not.toHaveBeenCalled();
  });

  it.each(["success", "error"])(
    "isolates late %s during status A → B → A and waits for the fresh visit",
    async (outcome) => {
      const user = userEvent.setup();
      const old = deferred<PublishJobPage>();
      const fresh = deferred<PublishJobPage>();
      let visits = 0;
      const calls = paginated({
        jobsPage: vi.fn<WeChatApi["jobsPage"]>((_account, _offset, filters) => {
          if (filters.status === "failed") return old.promise;
          return ++visits === 1
            ? Promise.resolve(result([job({ status: "scheduled" })]))
            : fresh.promise;
        }),
      });
      render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
      await openRecords(user);
      await screen.findByRole("button", { name: "取消" });
      await user.selectOptions(screen.getByLabelText("发布状态"), "failed");
      await user.selectOptions(screen.getByLabelText("发布状态"), "");
      expect(
        screen.queryByRole("button", { name: "取消" }),
      ).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
      await act(async () => {
        if (outcome === "success")
          old.resolve(result([job({ title: "旧筛选响应" })]));
        else old.reject(new Error("旧筛选错误"));
        await old.promise.catch(() => undefined);
      });
      expect(screen.queryByText("旧筛选响应")).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      await act(async () => {
        fresh.resolve(
          result([
            job({ title: "最新记录", status: "failed", can_recheck: false }),
          ]),
        );
        await fresh.promise;
      });
      expect(await screen.findByText("最新记录")).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "取消" }),
      ).not.toBeInTheDocument();
      expect(calls.cancel).not.toHaveBeenCalled();
    },
  );

  it("retries the selected page and filter after an error, then corrects a removed last page", async () => {
    const user = userEvent.setup();
    let fail = true;
    let total = 65;
    const calls = paginated({
      jobsPage: vi.fn<WeChatApi["jobsPage"]>((_account, offset) =>
        offset === 20 && fail
          ? Promise.reject(new Error("记录读取失败"))
          : Promise.resolve(result(RECORDS.slice(0, total), offset)),
      ),
    });
    render(<WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />);
    await openRecords(user);
    await screen.findByText("发布记录第 1 篇");
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("记录读取失败");
    expect(screen.queryByText("发布记录第 1 篇")).not.toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole("button", { name: "重试读取" }));
    await screen.findByText("发布记录第 21 篇");
    total = 21;
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() =>
      expect(
        screen.getByRole("navigation", { name: "发布记录分页" }),
      ).toHaveTextContent("共 21 条记录 · 第 21–21 条 · 第 2/2 页"),
    );
    expect(calls.jobsPage).toHaveBeenLastCalledWith(ACCOUNT.id, 20, {
      status: "",
      dateFrom: "",
      dateTo: "",
    });
  });

  it("guards dirty reconciliation on filters and page changes and keeps other views unfiltered", async () => {
    const user = userEvent.setup();
    const calls = paginated({
      drafts: vi.fn(() =>
        Promise.resolve({
          total: 1,
          items: [{ ...DRAFT, open_job_id: job().id }],
        }),
      ),
      jobsPage: vi.fn<WeChatApi["jobsPage"]>((_account, offset, filters) =>
        Promise.resolve(
          result(
            filters.status
              ? []
              : [job({ status: "outcome_unknown" }), ...RECORDS],
            offset,
          ),
        ),
      ),
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
    await openRecords(user);
    await user.click(
      await screen.findByRole("button", { name: "记录人工核对" }),
    );
    await user.type(
      screen.getByLabelText("核对依据"),
      "已核对后台，正在确认结果",
    );
    await user.selectOptions(screen.getByLabelText("发布状态"), "failed");
    await user.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("发布状态")).toHaveValue("");
    expect(screen.getByLabelText("核对依据")).toHaveValue(
      "已核对后台，正在确认结果",
    );
    expect(calls.jobsPage).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await user.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("核对依据")).toHaveValue(
      "已核对后台，正在确认结果",
    );
    await user.selectOptions(screen.getByLabelText("发布状态"), "failed");
    await user.click(screen.getByRole("button", { name: "放弃修改并继续" }));
    await screen.findByText("没有符合筛选条件的发布记录。");
    expect(screen.queryByLabelText("核对依据")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "草稿箱" }));
    expect(
      await screen.findByText("已发布、正在发布或结果待核对，见「发布记录」"),
    ).toBeInTheDocument();
    expect(calls.jobs).toHaveBeenLastCalledWith(ACCOUNT.id);
    expect(
      screen.queryByRole("button", { name: "立即发布" }),
    ).not.toBeInTheDocument();
    expect(calls.publish).not.toHaveBeenCalled();
    expect(calls.reconcile).not.toHaveBeenCalled();
  });

  it("polls only the current page without overlapping pending requests and stops after account change", async () => {
    vi.useFakeTimers();
    const late = deferred<PublishJobPage>();
    const calls = paginated({
      jobsPage: vi
        .fn<WeChatApi["jobsPage"]>()
        .mockResolvedValueOnce(result([job()]))
        .mockImplementationOnce(() => late.promise)
        .mockResolvedValue(result([])),
    });
    const view = render(
      <WeChatPublishPage api={calls} onSessionExpired={vi.fn()} />,
    );
    await act(() => Promise.resolve());
    fireEvent.click(screen.getByRole("tab", { name: "发布记录" }));
    await act(() => Promise.resolve());
    expect(calls.jobsPage).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(calls.jobsPage).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "重新查询结果" })).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(45_000);
    });
    expect(calls.jobsPage).toHaveBeenCalledTimes(2);
    fireEvent.change(screen.getByLabelText("公众号"), {
      target: { value: "second" },
    });
    await act(() => Promise.resolve());
    expect(calls.jobsPage).toHaveBeenCalledTimes(3);
    await act(async () => {
      late.resolve(result([job({ title: "过期轮询" })]));
      await late.promise;
      await vi.advanceTimersByTimeAsync(45_000);
    });
    expect(screen.queryByText("过期轮询")).not.toBeInTheDocument();
    expect(calls.jobsPage).toHaveBeenCalledTimes(3);
    view.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(calls.jobsPage).toHaveBeenCalledTimes(3);
  });
});
