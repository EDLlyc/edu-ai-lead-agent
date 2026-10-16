import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";

import {
  KeywordApiError,
  matchedTerms,
  splitTerms,
  type KeywordImpact,
  type KeywordLists,
  type KeywordsApi,
  type KeywordsOverview,
} from "./api";
import type { BuiltinPhrasesApi } from "./builtinApi";
import { KeywordsPage } from "./KeywordsPage";

const builtinApi: BuiltinPhrasesApi = {
  load: vi.fn(() =>
    Promise.resolve({
      version: null,
      marketing: ["保证提分"],
      anxiety: ["输在起跑线"],
      defaults_marketing: ["保证提分"],
      defaults_anxiety: ["输在起跑线"],
      locked: [{ name: "提示词注入", terms: ["忽略之前的指令"] }],
    }),
  ),
  save: vi.fn(() => Promise.reject(new Error("not used"))),
};

const V2: KeywordsOverview = {
  current: {
    version: 2,
    focus: ["人工智能", "机器人"],
    block: ["彩票"],
    copy_banned: ["保证提分"],
    note: null,
    created_by: "teacher.li",
    created_at: "2026-10-08T03:00:00Z",
  },
  history: [
    {
      version: 2,
      note: null,
      created_by: "teacher.li",
      created_at: "2026-10-08T03:00:00Z",
      focus_count: 2,
      block_count: 1,
      copy_banned_count: 1,
    },
    {
      version: 1,
      note: "第一版",
      created_by: "teacher.li",
      created_at: "2026-10-07T03:00:00Z",
      focus_count: 1,
      block_count: 0,
      copy_banned_count: 0,
    },
  ],
};

const IMPACT: KeywordImpact = {
  days: 7,
  candidate_count: 40,
  blocked_count: 2,
  blocked_selected_count: 1,
  blocked_share: 0.05,
  wide: false,
  blocked: [
    { title: "彩票中奖新规", terms: ["彩票"], selected: true },
    { title: "体育彩票销售", terms: ["彩票"], selected: false },
  ],
  per_block_term: [{ term: "彩票", count: 2 }],
  focused_count: 1,
  focused: [{ title: "机器人进课堂", terms: ["机器人"] }],
};

function saved(lists: KeywordLists, version = 3): KeywordsOverview {
  return {
    current: {
      ...V2.current!,
      ...lists,
      focus: [...lists.focus],
      block: [...lists.block],
      copy_banned: [...lists.copy_banned],
      version,
    },
    history: V2.history,
  };
}

function api(overrides: Partial<KeywordsApi> = {}) {
  return {
    load: vi.fn(() => Promise.resolve(V2)),
    version: vi.fn(() =>
      Promise.resolve({
        ...V2.current!,
        version: 1,
        focus: ["人工智能"],
        block: [],
        copy_banned: [],
        note: "第一版",
      }),
    ),
    impact: vi.fn(() => Promise.resolve(IMPACT)),
    save: vi.fn((lists: KeywordLists) => Promise.resolve(saved(lists))),
    ...overrides,
  } satisfies KeywordsApi;
}

describe("关键词", () => {
  it("shows the current lists, adds and removes terms, and saves a new version", async () => {
    const user = userEvent.setup();
    const save = vi.fn((lists: KeywordLists) => Promise.resolve(saved(lists)));
    const view = render(
      <KeywordsPage
        api={api({ save })}
        builtinApi={builtinApi}
        onSessionExpired={vi.fn()}
      />,
    );

    const focus = await screen.findByRole("list", { name: "关注词" });
    expect(
      within(focus)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["人工智能×", "机器人×"]);
    expect(screen.getByText(/当前第 2 版/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存为新版本" })).toBeDisabled();
    expect((await axe(view.container)).violations).toEqual([]);

    await user.type(
      screen.getByLabelText("添加关注词"),
      "科学营，青少年 机器人{Enter}",
    );
    await user.click(
      screen.getByRole("button", { name: "删除屏蔽词「彩票」" }),
    );
    expect(screen.getByText("将删除：彩票")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/备注/), "国庆后调整");
    await user.click(screen.getByRole("button", { name: "保存为新版本" }));

    expect(save).toHaveBeenCalledWith(
      {
        focus: ["人工智能", "机器人", "科学营", "青少年"],
        block: [],
        copy_banned: ["保证提分"],
      },
      { note: "国庆后调整", confirmWideBlock: false },
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "已保存为第 3 版",
    );
    expect(screen.getByRole("button", { name: "保存为新版本" })).toBeDisabled();
  });

  it("asks for a second confirmation when the block list is too wide", async () => {
    const user = userEvent.setup();
    const save = vi
      .fn()
      .mockRejectedValueOnce(
        new KeywordApiError(
          "keyword_block_too_wide",
          "屏蔽词会拦下最近 7 天 40 条候选里的 20 条（50%），请确认后再保存",
        ),
      )
      .mockImplementationOnce((lists: KeywordLists) =>
        Promise.resolve(saved(lists)),
      );
    render(
      <KeywordsPage
        api={api({ save })}
        builtinApi={builtinApi}
        onSessionExpired={vi.fn()}
      />,
    );

    await user.type(await screen.findByLabelText("添加屏蔽词"), "教育{Enter}");
    await user.click(screen.getByRole("button", { name: "保存为新版本" }));
    const dialog = await screen.findByRole("alertdialog", {
      name: "确认屏蔽范围",
    });
    expect(dialog).toHaveTextContent("50%");
    await user.click(
      within(dialog).getByRole("button", { name: "确认，仍然保存" }),
    );
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1]![1]).toEqual({
      note: "",
      confirmWideBlock: true,
    });
  });

  it("checks the impact on recent candidates", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(
      <KeywordsPage
        api={calls}
        builtinApi={builtinApi}
        onSessionExpired={vi.fn()}
      />,
    );
    await user.click(await screen.findByRole("button", { name: /检查影响/ }));
    const report = await screen.findByRole("region", { name: "影响检查" });
    expect(report).toHaveTextContent(
      "最近 7 天共有 40 条候选新闻：屏蔽词会拦下 2 条（5%，其中 1 条当时被选中了）；关注词命中 1 条。",
    );
    expect(
      within(report).getByRole("list", { name: "会被拦下的新闻" }),
    ).toHaveTextContent("彩票中奖新规命中：彩票 · 当时被选中");
    expect(calls.impact).toHaveBeenCalledWith(["人工智能", "机器人"], ["彩票"]);
  });

  it("tries a title against the lists without saving", async () => {
    const user = userEvent.setup();
    render(
      <KeywordsPage
        api={api()}
        builtinApi={builtinApi}
        onSessionExpired={vi.fn()}
      />,
    );
    await user.type(
      await screen.findByRole("textbox", { name: /粘贴一条新闻标题/ }),
      "机器人彩票，保证提分",
    );
    const hits = screen.getByRole("list", { name: "命中结果" });
    expect(
      within(hits)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["关注词：机器人", "屏蔽词：彩票", "文案禁用词：保证提分"]);
  });

  it("loads an old version into the editor without saving it", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(
      <KeywordsPage
        api={calls}
        builtinApi={builtinApi}
        onSessionExpired={vi.fn()}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "载入这一版" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "已载入第 1 版",
    );
    expect(
      within(screen.getByRole("list", { name: "关注词" }))
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["人工智能×"]);
    expect(screen.getByLabelText(/备注/)).toHaveValue("恢复第 1 版");
    expect(calls.save).not.toHaveBeenCalled();
  });

  it("rejects a term that is too long before sending anything", async () => {
    const user = userEvent.setup();
    render(
      <KeywordsPage
        api={api()}
        builtinApi={builtinApi}
        onSessionExpired={vi.fn()}
      />,
    );
    await user.type(
      await screen.findByLabelText("添加文案禁用词"),
      `${"长".repeat(21)}{Enter}`,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("每个词最多 20 个字");
  });
});

it("saves a changed built-in phrase list without touching the extra keyword lists", async () => {
  const user = userEvent.setup();
  const phrases = {
    version: 1,
    marketing: ["包过"],
    anxiety: ["输在起跑线"],
    defaults_marketing: ["保证提分"],
    defaults_anxiety: ["输在起跑线"],
    locked: [{ name: "提示词注入", terms: ["忽略之前的指令"] }],
  };
  const save = vi.fn(() => Promise.resolve(phrases));
  render(
    <KeywordsPage
      api={api()}
      builtinApi={{
        load: vi.fn(() =>
          Promise.resolve({
            ...phrases,
            version: null,
            marketing: ["保证提分"],
          }),
        ),
        save,
      }}
      onSessionExpired={vi.fn()}
    />,
  );
  const section = await screen.findByRole("region", { name: "系统内置词" });
  await user.click(
    within(section).getByRole("button", { name: "删除营销承诺「保证提分」" }),
  );
  await user.type(
    within(section).getByLabelText("添加营销承诺"),
    "包过{Enter}",
  );
  await user.click(within(section).getByRole("button", { name: "保存内置词" }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(["包过"], ["输在起跑线"]),
  );
  expect(
    within(section).getByText("已保存。从下一场选题开始，文案按这份词检查。"),
  ).toBeInTheDocument();
});

describe("keyword helpers", () => {
  it("split pasted input and match like the server", () => {
    expect(splitTerms("人工智能，机器人、 科学营\nAI;  ")).toEqual([
      "人工智能",
      "机器人",
      "科学营",
      "AI",
    ]);
    expect(matchedTerms("OpenAI 发布新模型", ["openai", "芯片"])).toEqual([
      "openai",
    ]);
  });
});

it("freezes notes together with keyword lists while saving", async () => {
  const user = userEvent.setup();
  const calls = api({
    save: vi.fn(() => new Promise<KeywordsOverview>(() => undefined)),
  });
  render(
    <KeywordsPage
      api={calls}
      builtinApi={builtinApi}
      onSessionExpired={vi.fn()}
    />,
  );
  await user.type(await screen.findByLabelText("添加关注词"), "新增词{Enter}");
  await user.type(screen.getByLabelText(/备注（可选/), "这次提交说明");
  await user.click(screen.getByRole("button", { name: "保存为新版本" }));
  expect(screen.getByLabelText(/备注（可选/)).toBeDisabled();
  expect(screen.getByLabelText("添加关注词")).toBeDisabled();
});
