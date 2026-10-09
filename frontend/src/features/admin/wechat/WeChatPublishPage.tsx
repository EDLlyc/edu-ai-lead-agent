import { useCallback, useEffect, useState } from "react";

import styles from "../Admin.module.css";
import { AdminSessionExpiredError } from "../api";
import { formatTime } from "../sources/labels";
import {
  JOB_STATUS_LABELS,
  wechatApi as defaultApi,
  type PublishJob,
  type WeChatAccountOption,
  type WeChatApi,
  type WeChatDraft,
  type WeChatPublished,
} from "./api";

type Tab = "drafts" | "jobs" | "published";
type Pending = {
  readonly draft: WeChatDraft;
  readonly when: "now" | "later";
  readonly step: 1 | 2;
} | null;

const OPEN = new Set<PublishJob["status"]>([
  "scheduled",
  "submitting",
  "publishing",
]);
const REFRESH_MS = 15_000;

function draftTitle(draft: WeChatDraft): string {
  const first = draft.articles[0]?.title ?? "（无标题）";
  return draft.articles.length > 1
    ? `${first} 等 ${draft.articles.length} 篇`
    : first;
}

/** `datetime-local` value (Beijing time) at least five minutes from now. */
function defaultLocalTime(): string {
  const date = new Date(Date.now() + 60 * 60_000);
  date.setMinutes(0, 0, 0);
  const shanghai = new Date(date.getTime() + 8 * 3_600_000);
  return shanghai.toISOString().slice(0, 16);
}

function localToIso(value: string): string {
  // The page works in Beijing time whatever the browser's zone.
  return new Date(`${value}:00+08:00`).toISOString();
}

/** 运营后台 · 公众号 · 发布: publish drafts now or at a time. */
export function WeChatPublishPage({
  api = defaultApi,
  onSessionExpired,
}: {
  readonly api?: WeChatApi;
  readonly onSessionExpired: () => void;
}) {
  const [accounts, setAccounts] = useState<
    readonly WeChatAccountOption[] | null
  >(null);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("drafts");
  const [drafts, setDrafts] = useState<readonly WeChatDraft[] | null>(null);
  const [jobs, setJobs] = useState<readonly PublishJob[] | null>(null);
  const [published, setPublished] = useState<readonly WeChatPublished[] | null>(
    null,
  );
  const [pending, setPending] = useState<Pending>(null);
  const [when, setWhen] = useState(defaultLocalTime);
  const [busy, setBusy] = useState(false);
  const [reloads, setReloads] = useState(0);
  const [message, setMessage] = useState<{
    readonly kind: "ok" | "error";
    readonly text: string;
  } | null>(null);

  const fail = useCallback(
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
    api.options().then(
      (items) => {
        if (cancelled) return;
        setAccounts(items);
        setAccountId((current) => current ?? items[0]?.id ?? null);
      },
      (error: unknown) => {
        if (!cancelled) fail(error);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, fail]);

  useEffect(() => {
    if (accountId === null) return;
    let cancelled = false;
    const load =
      tab === "drafts"
        ? api.drafts(accountId, 0).then((page) => {
            if (!cancelled) setDrafts(page.items);
          })
        : tab === "published"
          ? api.published(accountId, 0).then((page) => {
              if (!cancelled) setPublished(page.items);
            })
          : Promise.resolve();
    const jobsLoad = api.jobs(accountId).then((items) => {
      if (!cancelled) setJobs(items);
    });
    Promise.all([load, jobsLoad]).catch((error: unknown) => {
      if (!cancelled) fail(error);
    });
    return () => {
      cancelled = true;
    };
  }, [api, accountId, tab, reloads, fail]);

  const anyOpen = jobs?.some((job) => OPEN.has(job.status)) ?? false;
  useEffect(() => {
    if (!anyOpen) return;
    const timer = window.setInterval(
      () => setReloads((count) => count + 1),
      REFRESH_MS,
    );
    return () => window.clearInterval(timer);
  }, [anyOpen]);

  const confirm = async () => {
    if (pending === null || accountId === null) return;
    setBusy(true);
    setMessage(null);
    try {
      const job = await api.publish({
        accountId,
        mediaId: pending.draft.media_id,
        title: draftTitle(pending.draft),
        scheduledAt: pending.when === "later" ? localToIso(when) : null,
      });
      setMessage(
        job.status === "failed" || job.status === "outcome_unknown"
          ? {
              kind: "error",
              text: `「${job.title}」${JOB_STATUS_LABELS[job.status]}：${job.error ?? ""}`,
            }
          : {
              kind: "ok",
              text:
                job.status === "scheduled"
                  ? `已排期：${formatTime(job.scheduled_at)} 发布「${job.title}」`
                  : `已提交「${job.title}」，微信发布一般需要几分钟，可以在「发布记录」里看结果`,
            },
      );
      setPending(null);
      setTab("jobs");
      setReloads((count) => count + 1);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const cancelJob = async (job: PublishJob) => {
    setBusy(true);
    try {
      await api.cancel(job.id);
      setMessage({ kind: "ok", text: `已取消「${job.title}」的定时发布` });
      setReloads((count) => count + 1);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  if (accounts !== null && accounts.length === 0) {
    return (
      <section aria-labelledby="admin-section-title">
        <header className={styles.sectionHeader}>
          <h2 id="admin-section-title">公众号 · 发布</h2>
        </header>
        <p className={styles.notice}>
          还没有可用的公众号。请管理员先在「公众号 · 账号」里绑定。
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">公众号 · 发布</h2>
        {accounts === null || accounts.length < 2 ? null : (
          <label className={styles.inlineField}>
            <span>公众号</span>
            <select
              value={accountId ?? ""}
              onChange={(event) => {
                setAccountId(event.target.value);
                setDrafts(null);
                setJobs(null);
                setPublished(null);
                setPending(null);
              }}
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>
      <p className={styles.lede}>
        从草稿箱选文章立即发布或定时发布。发布后所有关注者都能看到，不能撤回，请先在手机上预览确认。
      </p>
      <div className={styles.filters} role="tablist" aria-label="发布视图">
        {(
          [
            ["drafts", "草稿箱"],
            ["jobs", "发布记录"],
            ["published", "已发布"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {message === null ? null : (
        <p
          className={message.kind === "error" ? styles.error : styles.success}
          role={message.kind === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}

      {tab === "drafts" ? (
        drafts === null ? (
          <p role="status">正在读取草稿箱…</p>
        ) : drafts.length === 0 ? (
          <p>草稿箱是空的。</p>
        ) : (
          <ul className={styles.cards} aria-label="草稿">
            {drafts.map((draft) => (
              <li key={draft.media_id}>
                <strong>{draftTitle(draft)}</strong>
                <span className={styles.hint}>
                  {draft.articles[0]?.author
                    ? `作者 ${draft.articles[0].author} · `
                    : ""}
                  更新于 {formatTime(draft.updated_at)}
                </span>
                {draft.articles[0]?.digest ? (
                  <small>{draft.articles[0].digest}</small>
                ) : null}
                {pending?.draft.media_id === draft.media_id ? (
                  <PublishConfirm
                    pending={pending}
                    when={when}
                    busy={busy}
                    onWhen={setWhen}
                    onNext={() => setPending({ ...pending, step: 2 })}
                    onConfirm={() => {
                      void confirm();
                    }}
                    onCancel={() => setPending(null)}
                  />
                ) : draft.open_job_id !== null ? (
                  <span className={styles.hint}>
                    已在发布或排期中，见「发布记录」
                  </span>
                ) : (
                  <span className={styles.rowActions}>
                    <button
                      type="button"
                      className={styles.primary}
                      onClick={() => {
                        setMessage(null);
                        setPending({ draft, when: "now", step: 1 });
                      }}
                    >
                      立即发布
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setMessage(null);
                        setWhen(defaultLocalTime());
                        setPending({ draft, when: "later", step: 1 });
                      }}
                    >
                      定时发布
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )
      ) : tab === "jobs" ? (
        jobs === null ? (
          <p role="status">正在读取…</p>
        ) : jobs.length === 0 ? (
          <p>还没有发布记录。</p>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">文章</th>
                <th scope="col">发布时间</th>
                <th scope="col">状态</th>
                <th scope="col">操作人</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id} data-status={job.status}>
                  <td>
                    {job.article_url === null ? (
                      job.title
                    ) : (
                      <a
                        href={job.article_url}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        {job.title}
                      </a>
                    )}
                  </td>
                  <td>{formatTime(job.scheduled_at)}</td>
                  <td>
                    {JOB_STATUS_LABELS[job.status]}
                    {job.error === null ? "" : `：${job.error}`}
                  </td>
                  <td>{job.cancelled_by ?? job.created_by}</td>
                  <td>
                    {job.status === "scheduled" ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          void cancelJob(job);
                        }}
                      >
                        取消
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : published === null ? (
        <p role="status">正在读取…</p>
      ) : published.length === 0 ? (
        <p>还没有已发布的文章。</p>
      ) : (
        <ol className={styles.articles} aria-label="已发布的文章">
          {published.map((item) => (
            <li key={item.article_id}>
              {item.articles.map((article) => (
                <a
                  key={article.url || article.title}
                  href={article.url}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  {article.title}
                </a>
              ))}
              <span>{formatTime(item.updated_at)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function PublishConfirm({
  pending,
  when,
  busy,
  onWhen,
  onNext,
  onConfirm,
  onCancel,
}: {
  readonly pending: NonNullable<Pending>;
  readonly when: string;
  readonly busy: boolean;
  readonly onWhen: (value: string) => void;
  readonly onNext: () => void;
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
}) {
  if (pending.step === 1) {
    return (
      <div className={styles.confirm} role="group" aria-label="确认发布">
        {pending.when === "later" ? (
          <label className={styles.inlineField}>
            <span>发布时间（北京时间）</span>
            <input
              type="datetime-local"
              value={when}
              onChange={(event) => onWhen(event.target.value)}
            />
          </label>
        ) : (
          <span>将立即发布这篇草稿。</span>
        )}
        <button type="button" className={styles.primary} onClick={onNext}>
          下一步
        </button>
        <button type="button" onClick={onCancel}>
          取消
        </button>
      </div>
    );
  }
  return (
    <div className={styles.issued} role="alertdialog" aria-label="再次确认发布">
      <p>
        <strong>再次确认：</strong>
        {pending.when === "later"
          ? `${when.replace("T", " ")} 发布「${draftTitle(pending.draft)}」。到时间会自动发给所有关注者，之前可以取消。`
          : `现在就把「${draftTitle(pending.draft)}」发给所有关注者，发出后不能撤回。`}
      </p>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          disabled={busy}
          onClick={onConfirm}
        >
          {busy
            ? "正在提交…"
            : pending.when === "later"
              ? "确认排期"
              : "确认发布"}
        </button>
        <button type="button" disabled={busy} onClick={onCancel}>
          返回
        </button>
      </div>
    </div>
  );
}
