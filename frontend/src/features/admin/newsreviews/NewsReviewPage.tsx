import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "../Admin.module.css";
import { AdminSessionExpiredError } from "../api";
import {
  newsReviewsApi as defaultApi,
  NewsReviewApiError,
  type NewsReviewsApi,
} from "./api";
import {
  EXCLUDE_REASONS,
  flattenPool,
  measureAgreement,
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

function score(value: number): string {
  return value.toFixed(2);
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
  const [blind, setBlind] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busyKey, setBusyKey] = useState<string | null>(null);
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
      },
      (error: unknown) => {
        if (!cancelled) fail(error, "读取新闻失败");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, fail]);

  const visible = useMemo(() => {
    if (items === null) return [];
    return items.filter((item) => {
      const record = records.get(item.key);
      if (filter === "todo") return record === undefined;
      if (filter === "disagree") {
        return (
          record !== undefined &&
          (record.decision === "include") !== item.eligible
        );
      }
      return true;
    });
  }, [items, records, filter]);

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
          这个筛选下没有新闻了。
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
                      </span>
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
