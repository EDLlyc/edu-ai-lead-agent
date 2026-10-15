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
  const [blind, setBlind] = useState(true);
  const [cursor, setCursor] = useState(0);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
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
  const index = Math.min(cursor, Math.max(visible.length - 1, 0));
  const item = visible[index];
  const record = item === undefined ? undefined : records.get(item.key);
  const showAi = !blind || record !== undefined;

  const submit = async (decision: ReviewCall) => {
    if (item === undefined || busy) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.review(item.key, decision, note);
      setRecords(
        new Map(records).set(item.key, {
          decision,
          note: note.trim() === "" ? null : note.trim(),
        }),
      );
      setNote("");
      setMessage({
        kind: "ok",
        text: decision === "include" ? "已记下：适合推" : "已记下：不适合推",
      });
    } catch (error) {
      fail(error, "保存审核失败");
    } finally {
      setBusy(false);
    }
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
        每天挑选和落选的新闻，说说你觉得适不适合推给家长。这里只记录你的意见，用来评估
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
              setCursor(0);
              setNote("");
            }}
          >
            {entry.title}
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
      {item === undefined ? (
        <p className={styles.hint} role="status">
          这个筛选下没有新闻了。
        </p>
      ) : (
        <ul className={styles.cards} aria-label="待审新闻">
          <li>
            <div>
              <h3>{item.title}</h3>
              <small>
                {[item.sourceName, item.tierLabel, item.slots.join("、")]
                  .filter(
                    (part): part is string => part !== null && part !== "",
                  )
                  .join(" · ")}
              </small>
              {item.snippet === null ? null : <p>{item.snippet}</p>}
              {item.sourceUrl === null ? null : (
                <a href={item.sourceUrl} target="_blank" rel="noreferrer">
                  打开原文
                </a>
              )}
            </div>
            {showAi ? (
              <p className={styles.hint}>
                AI 判断：
                {item.selected
                  ? "入选"
                  : item.eligible
                    ? "过线但没入选"
                    : "没过线"}
                {" · "}分数 {score(item.bestScore)}（过线{" "}
                {score(item.threshold)}） · 排名第 {item.bestRank}
                {item.reasons.length === 0
                  ? ""
                  : ` · ${item.reasons.map((reason) => REASON_LABEL[reason]).join("、")}`}
              </p>
            ) : (
              <p className={styles.hint}>
                盲审中：审完这条才会看到 AI 的判断。
              </p>
            )}
            {record === undefined ? null : (
              <p className={styles.success}>
                你已审：{record.decision === "include" ? "适合推" : "不适合推"}
                {record.note === null ? "" : `（${record.note}）`}。可以再改。
              </p>
            )}
            <label className={styles.field}>
              <span>备注（可不填）</span>
              <input
                value={note}
                maxLength={280}
                disabled={busy}
                onChange={(event) => setNote(event.target.value)}
              />
            </label>
            <div
              className={styles.filters}
              role="group"
              aria-label="不适合的原因"
            >
              {EXCLUDE_REASONS.map((reason) => (
                <button
                  key={reason}
                  type="button"
                  disabled={busy}
                  onClick={() => setNote(reason)}
                >
                  {reason}
                </button>
              ))}
            </div>
            <div className={styles.filters}>
              <button
                type="button"
                className={styles.primary}
                disabled={busy}
                onClick={() => void submit("include")}
              >
                适合推
              </button>
              <button
                type="button"
                className={styles.danger}
                disabled={busy}
                onClick={() => void submit("exclude")}
              >
                不适合推
              </button>
              <button
                type="button"
                disabled={busy || index === 0}
                onClick={() => {
                  setCursor(index - 1);
                  setNote("");
                }}
              >
                上一条
              </button>
              <button
                type="button"
                disabled={busy || index >= visible.length - 1}
                onClick={() => {
                  setCursor(index + 1);
                  setNote("");
                }}
              >
                下一条
              </button>
              <span className={styles.hint}>
                {index + 1} / {visible.length}
              </span>
            </div>
          </li>
        </ul>
      )}
    </section>
  );
}
