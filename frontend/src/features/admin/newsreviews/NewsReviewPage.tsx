import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "../Admin.module.css";
import { AdminSessionExpiredError } from "../api";
import {
  newsReviewsApi as defaultApi,
  NewsReviewApiError,
  type NewsPick,
  type NewsReviewsApi,
} from "./api";
import { HeldPickEditor } from "./HeldPickEditor";
import {
  EXCLUDE_REASONS,
  flattenPool,
  measureAgreement,
  PICK_STAGE_LABEL,
  pickInProgress,
  REASON_LABEL,
  reviewCall,
  type ReviewCall,
  type ReviewItem,
  type ReviewRecord,
} from "./reviewModel";

type Filter = "todo" | "all" | "disagree";

const FILTERS: readonly { readonly key: Filter; readonly title: string }[] = [
  { key: "todo", title: "还没审" },
  { key: "disagree", title: "和 AI 不一致" },
  { key: "all", title: "全部" },
];

function percent(part: number, whole: number): string {
  return whole === 0 ? "–" : `${Math.round((part / whole) * 100)}%`;
}

const PICK_REFRESH_MS = 20_000;

function score(value: number): string {
  return value.toFixed(2);
}

function picksOf(items: readonly ReviewItem[]): Map<string, NewsPick> {
  const found = new Map<string, NewsPick>();
  for (const item of items) {
    if (item.pick !== null) found.set(item.key, item.pick);
  }
  return found;
}

/** Everything about one 人工加推: start it, wait for the copy, review it, push it. */
function PickPanel({
  entry,
  pick,
  busy,
  api,
  onStart,
  onRefresh,
  onPushed,
  onSessionExpired,
}: {
  readonly entry: ReviewItem;
  readonly pick: NewsPick | null;
  readonly busy: boolean;
  readonly api: NewsReviewsApi;
  readonly onStart: () => void;
  readonly onRefresh: () => void;
  readonly onPushed: (pick: NewsPick) => void;
  readonly onSessionExpired: (error: unknown) => boolean;
}) {
  if (pick === null) {
    return (
      <div role="group" aria-label={`人工加推：${entry.title}`}>
        <p className={styles.hint}>
          把这条新闻额外推到正式家长群。先生成文案和配图并留住，你确认、必要时改引导语之后才会发出。每天
          22:30 前可以加推。
        </p>
        <span className={styles.rowActions}>
          <button
            type="button"
            className={styles.primary}
            disabled={busy}
            onClick={onStart}
          >
            生成文案和配图
          </button>
        </span>
      </div>
    );
  }
  if (pick.stage === "awaiting_review") {
    return (
      <HeldPickEditor
        candidateKey={entry.key}
        api={api}
        onPushed={onPushed}
        onSessionExpired={onSessionExpired}
      />
    );
  }
  return (
    <div role="group" aria-label={`人工加推：${entry.title}`}>
      <p className={styles.hint} role="status">
        {PICK_STAGE_LABEL[pick.stage]}
        {pickInProgress(pick) ? "，页面会自动刷新进度。" : "。"}
      </p>
      {pick.failure_code == null ? null : (
        <p className={styles.error}>原因代码：{pick.failure_code}</p>
      )}
      <span className={styles.rowActions}>
        <button type="button" onClick={onRefresh}>
          刷新进度
        </button>
      </span>
    </div>
  );
}

export function NewsReviewPage({
  api = defaultApi,
  onSessionExpired,
}: {
  readonly api?: NewsReviewsApi;
  readonly onSessionExpired: () => void;
}) {
  const [items, setItems] = useState<readonly ReviewItem[] | null>(null);
  const [records, setRecords] = useState<ReadonlyMap<string, ReviewRecord>>(
    new Map(),
  );
  const [filter, setFilter] = useState<Filter>("todo");
  const [query, setQuery] = useState("");
  const [blind, setBlind] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [pickEnabled, setPickEnabled] = useState(false);
  const [picks, setPicks] = useState<ReadonlyMap<string, NewsPick>>(new Map());
  const [panel, setPanel] = useState<string | null>(null);
  const [message, setMessage] = useState<{
    readonly kind: "ok" | "error";
    readonly text: string;
  } | null>(null);

  const fail = useCallback(
    (error: unknown, fallback: string) => {
      if (error instanceof AdminSessionExpiredError) {
        onSessionExpired();
        return;
      }
      setMessage({
        kind: "error",
        text: error instanceof NewsReviewApiError ? error.message : fallback,
      });
    },
    [onSessionExpired],
  );

  /** For the pick editor: a lapsed session ends the page; anything else it shows itself. */
  const sessionEnded = useCallback(
    (error: unknown) => {
      if (!(error instanceof AdminSessionExpiredError)) return false;
      onSessionExpired();
      return true;
    },
    [onSessionExpired],
  );

  useEffect(() => {
    let cancelled = false;
    api.load().then(
      (pool) => {
        if (cancelled) return;
        const flat = flattenPool(pool);
        const existing = new Map<string, ReviewRecord>();
        for (const item of flat) {
          if (item.existingReview !== null) {
            existing.set(item.key, {
              decision: reviewCall(item.existingReview, item),
              note: item.existingReview.note ?? null,
            });
          }
        }
        setItems(flat);
        setRecords(existing);
        setPickEnabled(
          pool.human_pick_enabled === true &&
            pool.human_pick_review_enabled === true,
        );
        setPicks(picksOf(flat));
      },
      (error: unknown) => {
        if (!cancelled) fail(error, "读取新闻失败");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, fail]);

  const refreshPicks = useCallback(async () => {
    try {
      setPicks(picksOf(flattenPool(await api.load())));
    } catch (error) {
      fail(error, "刷新加推进度失败");
    }
  }, [api, fail]);

  const working = useMemo(
    () => [...picks.values()].some((entry) => pickInProgress(entry)),
    [picks],
  );

  useEffect(() => {
    if (!working) return undefined;
    const timer = window.setInterval(() => {
      void refreshPicks();
    }, PICK_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [working, refreshPicks]);

  const visible = useMemo(() => {
    if (items === null) return [];
    const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return items.filter((item) => {
      const record = records.get(item.key);
      if (filter === "todo" && record !== undefined) return false;
      if (
        filter === "disagree" &&
        (record === undefined ||
          (record.decision === "include") === item.eligible)
      ) {
        return false;
      }
      if (terms.length === 0) return true;
      const haystack = [
        item.title,
        item.sourceName,
        item.tierLabel,
        item.snippet,
        record?.note,
      ]
        .join(" ")
        .toLowerCase();
      return terms.every((term) => haystack.includes(term));
    });
  }, [items, records, filter, query]);

  if (items === null) {
    return (
      <section aria-labelledby="admin-section-title">
        <header className={styles.sectionHeader}>
          <h2 id="admin-section-title">新闻审核</h2>
        </header>
        {message === null ? (
          <p className={styles.hint} role="status">
            正在读取…
          </p>
        ) : (
          <p className={styles.error} role="alert">
            {message.text}
          </p>
        )}
      </section>
    );
  }

  const agreement = measureAgreement(items, records);
  const counts: Record<Filter, number> = {
    todo: items.filter((entry) => !records.has(entry.key)).length,
    disagree: items.filter((entry) => {
      const record = records.get(entry.key);
      return (
        record !== undefined &&
        (record.decision === "include") !== entry.eligible
      );
    }).length,
    all: items.length,
  };

  const save = async (
    entry: ReviewItem,
    decision: ReviewCall,
    text: string,
  ) => {
    if (busyKey !== null) return;
    setBusyKey(entry.key);
    setMessage(null);
    try {
      await api.review(entry.key, decision, text);
      setRecords(
        new Map(records).set(entry.key, {
          decision,
          note: text.trim() === "" ? null : text.trim(),
        }),
      );
      setEditing(null);
      setNote("");
    } catch (error) {
      fail(error, "保存审核失败");
    } finally {
      setBusyKey(null);
    }
  };

  const startPick = async (entry: ReviewItem) => {
    if (busyKey !== null) return;
    setBusyKey(entry.key);
    setMessage(null);
    try {
      const created = await api.createPick(entry.key);
      setPicks(new Map(picks).set(entry.key, created));
      setMessage({
        kind: "ok",
        text: "已开始生成文案和配图，几分钟后回到这里审核；确认之前不会发到群里。",
      });
    } catch (error) {
      fail(error, "加推失败，请重试");
    } finally {
      setBusyKey(null);
    }
  };

  const openEditor = (entry: ReviewItem) => {
    if (editing === entry.key) {
      setEditing(null);
      setNote("");
      return;
    }
    setEditing(entry.key);
    setNote(records.get(entry.key)?.note ?? "");
  };

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">新闻审核</h2>
        <span className={styles.hint}>
          共 {items.length} 条 · 已审 {agreement.labelled} 条
        </span>
      </header>
      <p className={styles.lede}>
        看 AI
        每天挑选和落选的新闻，每条点一下「适合推」或「不适合推」。这里只记录你的意见，用来评估
        AI 选得准不准，不会改变已经选好的内容，也不会发出任何消息。
        {pickEnabled
          ? "唯一的例外是「人工加推」：你确认文案后，才会发到正式家长群。"
          : ""}
      </p>
      {message === null ? null : (
        <p
          className={message.kind === "error" ? styles.error : styles.success}
          role={message.kind === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}
      <div className={styles.filters} role="group" aria-label="筛选">
        {FILTERS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            aria-pressed={filter === entry.key}
            onClick={() => {
              setFilter(entry.key);
              setEditing(null);
            }}
          >
            {entry.title}（{counts[entry.key]}）
          </button>
        ))}
        <button
          type="button"
          aria-pressed={blind}
          onClick={() => setBlind(!blind)}
        >
          盲审（先不看 AI 的判断）
        </button>
      </div>
      <div className={styles.field}>
        <label htmlFor="news-review-search">搜索新闻</label>
        <input
          id="news-review-search"
          type="search"
          value={query}
          placeholder="标题、来源、摘要或备注里的字，多个词用空格隔开"
          onChange={(event) => {
            setQuery(event.target.value);
            setEditing(null);
          }}
        />
        {query.trim() === "" ? null : (
          <span className={styles.hint} role="status">
            找到 {visible.length} 条
          </span>
        )}
      </div>
      {agreement.labelled === 0 ? null : (
        <p className={styles.hint} aria-label="与 AI 的一致率">
          你的意见和 AI 过线与否一致：
          {percent(agreement.agreeWithEligibility, agreement.labelled)}（
          {agreement.agreeWithEligibility}/{agreement.labelled}
          ）；和最终入选一致：
          {percent(agreement.agreeWithSelection, agreement.labelled)}
          。你认为该推但 AI 没过线 {agreement.includedButBelowThreshold}{" "}
          条，你认为不该推但 AI 过线 {agreement.excludedButEligible} 条。
        </p>
      )}
      {visible.length === 0 ? (
        <p className={styles.hint} role="status">
          {query.trim() === ""
            ? "这个筛选下没有新闻了。"
            : "没有找到符合的新闻，可以换个词，或者切到「全部」再搜。"}
        </p>
      ) : (
        <div
          className={styles.tableScroll}
          tabIndex={0}
          role="region"
          aria-label="新闻列表，可横向滚动"
        >
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">新闻</th>
                <th scope="col">AI 判断</th>
                <th scope="col">你的意见</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((entry) => {
                const record = records.get(entry.key);
                const busy = busyKey === entry.key;
                const hidden = blind && record === undefined;
                return (
                  <tr key={entry.key}>
                    <th scope="row">
                      {entry.sourceUrl === null ? (
                        <span className={styles.cellTitle}>{entry.title}</span>
                      ) : (
                        <a
                          className={styles.cellTitle}
                          href={entry.sourceUrl}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {entry.title}
                        </a>
                      )}
                      <div className={styles.metadata}>
                        {[
                          entry.sourceName,
                          entry.tierLabel,
                          entry.slots.join("、"),
                        ]
                          .filter(
                            (part): part is string =>
                              part !== null && part !== "",
                          )
                          .join(" · ")}
                      </div>
                      {entry.snippet === null ? null : (
                        <div className={styles.metadata}>{entry.snippet}</div>
                      )}
                    </th>
                    <td>
                      {hidden ? (
                        <span className={styles.hint}>盲审中</span>
                      ) : (
                        <>
                          <strong>
                            {entry.selected
                              ? "入选"
                              : entry.eligible
                                ? "过线没入选"
                                : "没过线"}
                          </strong>
                          <div className={styles.metadata}>
                            分数 {score(entry.bestScore)}（线{" "}
                            {score(entry.threshold)}）· 第 {entry.bestRank} 名
                            {entry.reasons.length === 0
                              ? ""
                              : ` · ${entry.reasons.map((reason) => REASON_LABEL[reason]).join("、")}`}
                          </div>
                        </>
                      )}
                    </td>
                    <td>
                      <span className={styles.rowActions}>
                        <button
                          type="button"
                          className={
                            record?.decision === "include"
                              ? styles.primary
                              : undefined
                          }
                          aria-pressed={record?.decision === "include"}
                          aria-label={`适合推：${entry.title}`}
                          disabled={busy}
                          onClick={() =>
                            void save(entry, "include", record?.note ?? "")
                          }
                        >
                          适合推
                        </button>
                        <button
                          type="button"
                          className={
                            record?.decision === "exclude"
                              ? styles.danger
                              : undefined
                          }
                          aria-pressed={record?.decision === "exclude"}
                          aria-label={`不适合推：${entry.title}`}
                          disabled={busy}
                          onClick={() =>
                            void save(entry, "exclude", record?.note ?? "")
                          }
                        >
                          不适合推
                        </button>
                        <button
                          type="button"
                          aria-expanded={editing === entry.key}
                          aria-label={`备注：${entry.title}`}
                          disabled={busy}
                          onClick={() => openEditor(entry)}
                        >
                          备注
                        </button>
                        {!pickEnabled || entry.selected ? null : (
                          <button
                            type="button"
                            aria-expanded={panel === entry.key}
                            aria-label={`加推：${entry.title}`}
                            disabled={busy}
                            onClick={() =>
                              setPanel(panel === entry.key ? null : entry.key)
                            }
                          >
                            {picks.has(entry.key) ? "加推进度" : "人工加推"}
                          </button>
                        )}
                      </span>
                      {!picks.has(entry.key) ? null : (
                        <div className={styles.metadata}>
                          加推：{PICK_STAGE_LABEL[picks.get(entry.key)!.stage]}
                        </div>
                      )}
                      {panel !== entry.key ? null : (
                        <PickPanel
                          entry={entry}
                          pick={picks.get(entry.key) ?? null}
                          busy={busy}
                          api={api}
                          onStart={() => void startPick(entry)}
                          onRefresh={() => void refreshPicks()}
                          onPushed={(pushed) =>
                            setPicks(new Map(picks).set(entry.key, pushed))
                          }
                          onSessionExpired={sessionEnded}
                        />
                      )}
                      {record?.note == null ? null : (
                        <div className={styles.metadata}>
                          备注：{record.note}
                        </div>
                      )}
                      {editing !== entry.key ? null : (
                        <div role="group" aria-label={`备注：${entry.title}`}>
                          <label className={styles.field}>
                            <span>备注（可不填）</span>
                            <input
                              value={note}
                              maxLength={280}
                              disabled={busy}
                              onChange={(event) => setNote(event.target.value)}
                            />
                          </label>
                          <span className={styles.rowActions}>
                            {EXCLUDE_REASONS.map((reason) => (
                              <button
                                key={reason}
                                type="button"
                                disabled={busy}
                                onClick={() =>
                                  void save(entry, "exclude", reason)
                                }
                              >
                                {reason}
                              </button>
                            ))}
                          </span>
                          <span className={styles.rowActions}>
                            <button
                              type="button"
                              className={styles.primary}
                              disabled={busy || record === undefined}
                              onClick={() =>
                                record === undefined
                                  ? undefined
                                  : void save(entry, record.decision, note)
                              }
                            >
                              保存备注
                            </button>
                            {record === undefined ? (
                              <span className={styles.hint}>
                                先点「适合推」或「不适合推」
                              </span>
                            ) : null}
                          </span>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
