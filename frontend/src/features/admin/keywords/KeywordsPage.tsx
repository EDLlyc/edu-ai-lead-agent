import { useCallback, useEffect, useState } from "react";

import styles from "../Admin.module.css";
import { useUnsavedChanges, useUnsavedNavigation } from "../unsaved/context";
import { AdminSessionExpiredError } from "../api";
import { formatTime } from "../sources/labels";
import {
  KeywordApiError,
  keywordsApi as defaultApi,
  matchedTerms,
  splitTerms,
  type KeywordImpact,
  type KeywordLists,
  type KeywordsApi,
  type KeywordsOverview,
} from "./api";
import {
  builtinPhrasesApi as defaultBuiltinApi,
  type BuiltinPhrases,
  type BuiltinPhrasesApi,
} from "./builtinApi";

type ListName = keyof KeywordLists;

const LISTS: readonly {
  readonly name: ListName;
  readonly title: string;
  readonly help: string;
}[] = [
  {
    name: "focus",
    title: "关注词",
    help: "标题或摘要里有这些词的新闻，在同一时段里排得更靠前（不会让不合格的新闻入选）。",
  },
  {
    name: "block",
    title: "屏蔽词",
    help: "标题或摘要里有这些词的新闻不会被选中。",
  },
  {
    name: "copy_banned",
    title: "文案禁用词",
    help: "生成的朋友圈文案里出现这些词就判定不通过，系统会自动改写或重写。",
  },
];

const EMPTY: KeywordLists = { focus: [], block: [], copy_banned: [] };

function sameTerms(left: readonly string[], right: readonly string[]): boolean {
  return (
    left.length === right.length &&
    left.every((term, index) => term === right[index])
  );
}

function listsOf(overview: KeywordsOverview): KeywordLists {
  const current = overview.current;
  return current === null
    ? EMPTY
    : {
        focus: current.focus,
        block: current.block,
        copy_banned: current.copy_banned,
      };
}

/** 运营后台 · 关键词: the operator's 关注词 / 屏蔽词 / 文案禁用词. */
export function KeywordsPage({
  api = defaultApi,
  builtinApi = defaultBuiltinApi,
  onSessionExpired,
}: {
  readonly api?: KeywordsApi;
  readonly builtinApi?: BuiltinPhrasesApi;
  readonly onSessionExpired: () => void;
}) {
  const [overview, setOverview] = useState<KeywordsOverview | null>(null);
  const [draft, setDraft] = useState<KeywordLists>(EMPTY);
  const [note, setNote] = useState("");
  const [impact, setImpact] = useState<KeywordImpact | null>(null);
  const [wideWarning, setWideWarning] = useState<string | null>(null);
  const [trial, setTrial] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{
    readonly kind: "ok" | "error";
    readonly text: string;
  } | null>(null);

  const handleError = useCallback(
    (error: unknown) => {
      if (error instanceof AdminSessionExpiredError) {
        onSessionExpired();
        return;
      }
      setMessage({
        kind: "error",
        text: error instanceof Error ? error.message : "操作失败",
      });
    },
    [onSessionExpired],
  );

  useEffect(() => {
    let cancelled = false;
    api.load().then(
      (loaded) => {
        if (cancelled) return;
        setOverview(loaded);
        setDraft(listsOf(loaded));
      },
      (error: unknown) => {
        if (!cancelled) handleError(error);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, handleError]);

  const saved = overview === null ? EMPTY : listsOf(overview);
  const dirty = LISTS.some(({ name }) => !sameTerms(draft[name], saved[name]));
  const { requestNavigation } = useUnsavedNavigation();
  const discard = () => {
    setDraft(saved);
    setImpact(null);
    setWideWarning(null);
    setNote("");
  };
  useUnsavedChanges(dirty || note !== "", discard);

  if (overview === null) {
    return message === null ? (
      <p role="status">正在读取…</p>
    ) : (
      <p className={styles.error} role="alert">
        {message.text}
      </p>
    );
  }

  const update = (name: ListName, terms: readonly string[]) => {
    setDraft((current) => ({ ...current, [name]: terms }));
    setImpact(null);
    setWideWarning(null);
    setMessage(null);
  };

  const checkImpact = async () => {
    setBusy(true);
    setMessage(null);
    try {
      setImpact(await api.impact(draft.focus, draft.block));
    } catch (error) {
      handleError(error);
    } finally {
      setBusy(false);
    }
  };

  const save = async (confirmWideBlock: boolean) => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.save(draft, {
        note: note.trim(),
        confirmWideBlock,
      });
      setOverview(result);
      setDraft(listsOf(result));
      setNote("");
      setImpact(null);
      setWideWarning(null);
      setMessage({
        kind: "ok",
        text: `已保存为第 ${result.current?.version ?? "?"} 版，下一个选题时段开始生效`,
      });
    } catch (error) {
      if (
        error instanceof KeywordApiError &&
        error.code === "keyword_block_too_wide"
      ) {
        setWideWarning(error.message);
      } else {
        handleError(error);
      }
    } finally {
      setBusy(false);
    }
  };

  const loadVersion = async (version: number) => {
    setBusy(true);
    try {
      const old = await api.version(version);
      setDraft({
        focus: old.focus,
        block: old.block,
        copy_banned: old.copy_banned,
      });
      setNote(`恢复第 ${version} 版`);
      setImpact(null);
      setWideWarning(null);
      setMessage({
        kind: "ok",
        text: `已载入第 ${version} 版，检查后点「保存为新版本」才会生效`,
      });
    } catch (error) {
      handleError(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">关键词</h2>
        <span className={styles.hint}>
          {overview.current === null
            ? "还没有设置过，现在只用系统内置规则"
            : `当前第 ${overview.current.version} 版 · ${overview.current.created_by} · ${formatTime(overview.current.created_at)}`}
        </span>
      </header>
      <p className={styles.lede}>
        在下面「系统内置词」之外再加的词。按包含匹配，不分大小写；每次保存是一个新版本，已经开始的选题不受影响。
      </p>
      <BuiltinPhrasesSection
        api={builtinApi}
        onSessionExpired={onSessionExpired}
      />
      {message === null ? null : (
        <p
          className={message.kind === "error" ? styles.error : styles.success}
          role={message.kind === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}

      <div className={styles.keywordLists}>
        {LISTS.map((list) => (
          <TermList
            key={list.name}
            title={list.title}
            help={list.help}
            terms={draft[list.name]}
            saved={saved[list.name]}
            disabled={busy}
            onChange={(terms) => update(list.name, terms)}
          />
        ))}
      </div>

      <section className={styles.trial} aria-label="试一下">
        <label className={styles.field}>
          <span>试一下：粘贴一条新闻标题或一段文案，看会命中哪些词</span>
          <textarea
            rows={2}
            value={trial}
            onChange={(event) => setTrial(event.target.value)}
          />
        </label>
        {trial.trim() === "" ? null : (
          <ul aria-label="命中结果">
            {LISTS.map((list) => {
              const hits = matchedTerms(trial, draft[list.name]);
              return (
                <li key={list.name}>
                  {list.title}：
                  {hits.length === 0 ? "没有命中" : hits.join("、")}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {impact === null ? null : <ImpactReport impact={impact} />}
      {wideWarning === null ? null : (
        <div
          className={styles.confirm}
          role="alertdialog"
          aria-label="确认屏蔽范围"
        >
          <p className={styles.error}>{wideWarning}</p>
          <button
            type="button"
            className={styles.primary}
            disabled={busy}
            onClick={() => {
              void save(true);
            }}
          >
            确认，仍然保存
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setWideWarning(null)}
          >
            再改改
          </button>
        </div>
      )}

      <div className={styles.actions}>
        <label className={styles.field}>
          <span>备注（可选，写清楚为什么改）</span>
          <input
            disabled={busy}
            value={note}
            maxLength={200}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
      </div>
      <div className={styles.actions}>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            void checkImpact();
          }}
        >
          检查影响（最近 7 天）
        </button>
        <button
          type="button"
          className={styles.primary}
          disabled={busy || !dirty}
          title={dirty ? undefined : "没有改动"}
          onClick={() => {
            void save(false);
          }}
        >
          保存为新版本
        </button>
        {dirty ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              requestNavigation(discard);
            }}
          >
            放弃修改
          </button>
        ) : null}
      </div>

      {overview.history.length === 0 ? null : (
        <section aria-label="历史版本">
          <h3 className={styles.subheading}>历史版本</h3>
          <div
            className={styles.tableScroll}
            tabIndex={0}
            role="region"
            aria-label="关键词历史版本，可横向滚动"
          >
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">版本</th>
                  <th scope="col">时间</th>
                  <th scope="col">账号</th>
                  <th scope="col">词数（关注/屏蔽/禁用）</th>
                  <th scope="col">备注</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {overview.history.map((item, index) => (
                  <tr key={item.version}>
                    <td>
                      第 {item.version} 版{index === 0 ? "（当前）" : ""}
                    </td>
                    <td>{formatTime(item.created_at)}</td>
                    <td>{item.created_by}</td>
                    <td>
                      {item.focus_count} / {item.block_count} /{" "}
                      {item.copy_banned_count}
                    </td>
                    <td>{item.note ?? ""}</td>
                    <td>
                      {index === 0 ? null : (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            requestNavigation(() => {
                              void loadVersion(item.version);
                            });
                          }}
                        >
                          载入这一版
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </section>
  );
}

function TermList({
  title,
  help,
  terms,
  saved,
  disabled,
  onChange,
}: {
  readonly title: string;
  readonly help: string;
  readonly terms: readonly string[];
  readonly saved: readonly string[];
  readonly disabled: boolean;
  readonly onChange: (terms: readonly string[]) => void;
}) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  useUnsavedChanges(input !== "", () => {
    setInput("");
    setError(null);
  });
  const savedKeys = new Set(saved.map((term) => term.toLocaleLowerCase()));
  const removed = saved.filter(
    (term) =>
      !terms.some(
        (item) => item.toLocaleLowerCase() === term.toLocaleLowerCase(),
      ),
  );

  const add = () => {
    const keys = new Set(terms.map((term) => term.toLocaleLowerCase()));
    const fresh: string[] = [];
    for (const term of splitTerms(input)) {
      if (term.length > 20) {
        setError(`「${term.slice(0, 24)}」太长，每个词最多 20 个字`);
        return;
      }
      const key = term.toLocaleLowerCase();
      if (!keys.has(key)) {
        keys.add(key);
        fresh.push(term);
      }
    }
    setError(null);
    setInput("");
    if (fresh.length > 0) onChange([...terms, ...fresh]);
  };

  return (
    <fieldset className={styles.termList}>
      <legend>
        {title}（{terms.length}）
      </legend>
      <p className={styles.hint}>{help}</p>
      <ul aria-label={title}>
        {terms.map((term) => (
          <li key={term} data-new={!savedKeys.has(term.toLocaleLowerCase())}>
            {term}
            <button
              type="button"
              aria-label={`删除${title}「${term}」`}
              disabled={disabled}
              onClick={() => onChange(terms.filter((item) => item !== term))}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      {removed.length === 0 ? null : (
        <p className={styles.hint}>将删除：{removed.join("、")}</p>
      )}
      <div className={styles.addTerm}>
        <input
          aria-label={`添加${title}`}
          placeholder="输入后回车，多个词用空格或逗号分隔"
          value={input}
          disabled={disabled}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing) {
              event.preventDefault();
              add();
            }
          }}
        />
        <button
          type="button"
          disabled={disabled || input.trim() === ""}
          onClick={add}
        >
          添加
        </button>
      </div>
      {error === null ? null : (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </fieldset>
  );
}

function ImpactReport({ impact }: { readonly impact: KeywordImpact }) {
  return (
    <section className={styles.preview} aria-label="影响检查">
      {impact.candidate_count === 0 ? (
        <p>最近 {impact.days} 天还没有选题记录，没法估计影响。</p>
      ) : (
        <>
          <p>
            最近 {impact.days} 天共有 {impact.candidate_count}{" "}
            条候选新闻：屏蔽词会拦下 {impact.blocked_count} 条（
            {Math.round(impact.blocked_share * 100)}%
            {impact.blocked_selected_count > 0
              ? `，其中 ${impact.blocked_selected_count} 条当时被选中了`
              : ""}
            ）；关注词命中 {impact.focused_count} 条。
          </p>
          {impact.wide ? (
            <p className={styles.error}>屏蔽范围偏大，保存时需要再确认一次。</p>
          ) : null}
          {impact.per_block_term.length === 0 ? null : (
            <p className={styles.hint}>
              每个屏蔽词：
              {impact.per_block_term
                .map((item) => `${item.term} ${item.count} 条`)
                .join("，")}
            </p>
          )}
          {impact.blocked.length === 0 ? null : (
            <ul className={styles.samples} aria-label="会被拦下的新闻">
              {impact.blocked.map((item) => (
                <li key={item.title} data-kept="false">
                  <strong>{item.title}</strong>
                  <span>
                    命中：{item.terms.join("、")}
                    {item.selected ? " · 当时被选中" : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {impact.focused.length === 0 ? null : (
            <ul className={styles.samples} aria-label="关注词命中的新闻">
              {impact.focused.map((item) => (
                <li key={item.title} data-kept="true">
                  <strong>{item.title}</strong>
                  <span>命中：{item.terms.join("、")}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function sameList(left: readonly string[], right: readonly string[]): boolean {
  return (
    left.length === right.length &&
    left.every((term, index) => term === right[index])
  );
}

/** The editorial built-in phrase lists. Safety checks stay locked. */
function BuiltinPhrasesSection({
  api,
  onSessionExpired,
}: {
  readonly api: BuiltinPhrasesApi;
  readonly onSessionExpired: () => void;
}) {
  const [current, setCurrent] = useState<BuiltinPhrases | null>(null);
  const [marketing, setMarketing] = useState<readonly string[]>([]);
  const [anxiety, setAnxiety] = useState<readonly string[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fail = useCallback(
    (caught: unknown, fallback: string) => {
      if (caught instanceof AdminSessionExpiredError) {
        onSessionExpired();
        return;
      }
      setError(caught instanceof Error ? caught.message : fallback);
    },
    [onSessionExpired],
  );

  useEffect(() => {
    let cancelled = false;
    api.load().then(
      (loaded) => {
        if (cancelled) return;
        setCurrent(loaded);
        setMarketing(loaded.marketing);
        setAnxiety(loaded.anxiety);
      },
      (caught: unknown) => {
        if (!cancelled) fail(caught, "读取系统内置词失败");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, fail]);

  const dirty =
    current !== null &&
    (!sameList(marketing, current.marketing) ||
      !sameList(anxiety, current.anxiety));
  useUnsavedChanges(dirty, () => {
    if (current === null) return;
    setMarketing(current.marketing);
    setAnxiety(current.anxiety);
  });

  if (current === null) {
    return error === null ? null : (
      <p className={styles.error} role="alert">
        {error}
      </p>
    );
  }

  const save = async () => {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const saved = await api.save(marketing, anxiety);
      setCurrent(saved);
      setMarketing(saved.marketing);
      setAnxiety(saved.anxiety);
      setMessage("已保存。从下一场选题开始，文案按这份词检查。");
    } catch (caught) {
      fail(caught, "保存失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.preview} aria-label="系统内置词">
      <h3>系统内置词</h3>
      <p className={styles.hint}>
        文案里出现这些词就判定不通过。可以增删，保存后从下一场选题开始生效；已经开始的选题仍用保存前的词。
        {current.version === null
          ? "现在用的是系统原来的词。"
          : `当前第 ${current.version} 版。`}
      </p>
      {message === null ? null : (
        <p className={styles.success} role="status">
          {message}
        </p>
      )}
      {error === null ? null : (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <TermList
        title="营销承诺"
        help="例如「保证提分」「最权威」。删掉之后，文案里出现这个词不再因此被拦住。"
        terms={marketing}
        saved={current.marketing}
        disabled={busy}
        onChange={setMarketing}
      />
      <TermList
        title="焦虑话术"
        help="例如「输在起跑线」。删掉之后，文案里出现这个词不再因此被拦住。"
        terms={anxiety}
        saved={current.anxiety}
        disabled={busy}
        onChange={setAnxiety}
      />
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          disabled={!dirty || busy}
          onClick={() => void save()}
        >
          保存内置词
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setMarketing(current.defaults_marketing);
            setAnxiety(current.defaults_anxiety);
          }}
        >
          载入系统原版
        </button>
      </div>
      <details>
        <summary>这些检查不能在这里改</summary>
        <ul>
          {current.locked.map((list) => (
            <li key={list.name}>
              {list.name}：{list.terms.join("、")}
            </li>
          ))}
          <li>手机号、身份证号、邮箱仍由系统识别，不能改成词表。</li>
        </ul>
      </details>
    </section>
  );
}
