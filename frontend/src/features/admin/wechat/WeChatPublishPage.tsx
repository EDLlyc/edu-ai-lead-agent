import { useCallback, useEffect, useRef, useState } from "react";

import styles from "../Admin.module.css";
import { AdminSessionExpiredError } from "../api";
import { formatTime } from "../sources/labels";
import { useUnsavedChanges, useUnsavedNavigation } from "../unsaved/context";
import {
  PUBLICATION_PAGE_SIZE,
  usePublicationPage,
  type PublicationTab,
} from "./usePublicationPage";
import {
  JOB_STATUS_LABELS,
  wechatApi as defaultApi,
  type PublishJob,
  type PublishReconcile,
  type WeChatAccountOption,
  type WeChatApi,
  type WeChatDraft,
} from "./api";

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
  canReconcile = false,
}: {
  readonly api?: WeChatApi;
  readonly onSessionExpired: () => void;
  readonly canReconcile?: boolean;
}) {
  const [accounts, setAccounts] = useState<
    readonly WeChatAccountOption[] | null
  >(null);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [tab, setTab] = useState<PublicationTab>("drafts");
  const [pending, setPending] = useState<Pending>(null);
  const [reconciling, setReconciling] = useState<PublishJob | null>(null);
  const [when, setWhen] = useState(defaultLocalTime);
  const [busy, setBusy] = useState(false);
  const [optionsReloads, setOptionsReloads] = useState(0);
  const [initialWhen, setInitialWhen] = useState(defaultLocalTime);
  const submitting = useRef(false);
  const { requestNavigation } = useUnsavedNavigation();
  const page = usePublicationPage({ api, accountId, tab, onSessionExpired });
  const { refresh } = page;
  const drafts = page.data?.tab === "drafts" ? page.data.page.items : null;
  const published =
    page.data?.tab === "published" ? page.data.page.items : null;
  const jobs = page.jobs;
  const actionsDisabled = busy || !page.ready;
  const pendingDraft = drafts?.find(
    (draft) => draft.media_id === pending?.draft.media_id,
  );
  const pendingInvalid =
    pending !== null &&
    pendingDraft !== undefined &&
    (pendingDraft.open_job_id !== null ||
      pendingDraft.updated_at !== pending.draft.updated_at ||
      JSON.stringify(pendingDraft.articles) !==
        JSON.stringify(pending.draft.articles));
  const { requestDiscard: discardPending } = useUnsavedChanges(
    pending?.step === 2 || (pending?.when === "later" && when !== initialWhen),
    () => {
      setPending(null);
    },
  );

  const changeContext = (action: () => void) => {
    if (busy) return;
    requestNavigation(() => {
      setPending(null);
      setReconciling(null);
      setMessage(null);
      action();
    });
  };
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
  }, [api, fail, optionsReloads]);

  const anyOpen = jobs?.some((job) => OPEN.has(job.status)) ?? false;
  useEffect(() => {
    if (!anyOpen || page.loading || busy) return;
    const timer = window.setInterval(refresh, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [anyOpen, busy, page.loading, refresh]);

  const confirm = async () => {
    if (
      pending === null ||
      accountId === null ||
      actionsDisabled ||
      pendingInvalid ||
      submitting.current
    )
      return;
    const currentDraft = drafts?.find(
      (draft) => draft.media_id === pending.draft.media_id,
    );
    if (!currentDraft || currentDraft.open_job_id !== null) return;
    submitting.current = true;
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
      refresh();
    } catch (error) {
      fail(error);
      // A lost browser response does not prove that the API never submitted the draft.
      setPending(null);
      setTab("jobs");
      refresh();
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };

  const cancelJob = async (job: PublishJob) => {
    if (actionsDisabled || job.account_id !== accountId) return;
    setBusy(true);
    try {
      await api.cancel(job.id);
      setMessage({ kind: "ok", text: `已取消「${job.title}」的定时发布` });
      refresh();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const recheck = async (job: PublishJob) => {
    if (actionsDisabled || job.account_id !== accountId) return;
    setBusy(true);
    try {
      const result = await api.recheck(job.id);
      setMessage({
        kind: result.status === "outcome_unknown" ? "error" : "ok",
        text: `查询结果：${JOB_STATUS_LABELS[result.status]}${result.error ? `：${result.error}` : ""}`,
      });
      refresh();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const reconcile = async (input: PublishReconcile) => {
    if (
      reconciling === null ||
      actionsDisabled ||
      reconciling.account_id !== accountId
    )
      return;
    setBusy(true);
    try {
      await api.reconcile(reconciling.id, input);
      setReconciling(null);
      setMessage({
        kind: "ok",
        text:
          input.result === "published"
            ? "已记录人工核对：文章已发布，仍禁止重复提交。"
            : "已记录人工核对：文章未发布。可以返回草稿箱重新提交。",
      });
      refresh();
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
              disabled={busy}
              onChange={(event) => {
                const nextAccount = event.target.value;
                changeContext(() => {
                  page.changePage(0);
                  setAccountId(nextAccount);
                });
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
        从草稿箱选择文章公开发布或定时公开发布。本操作不会向粉丝群发；请先在公众号后台预览全部篇目。已发布和结果待核对的草稿不能重复提交。
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
            disabled={busy}
            onClick={() => {
              if (key !== tab)
                changeContext(() => {
                  page.changePage(0);
                  setTab(key);
                });
            }}
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

      {reconciling === null ? null : (
        <ReconcileForm
          key={reconciling.id}
          job={reconciling}
          busy={actionsDisabled}
          onConfirm={(input) => {
            void reconcile(input);
          }}
          onCancel={() => setReconciling(null)}
        />
      )}
      {accounts === null && message?.kind === "error" ? (
        <button
          type="button"
          onClick={() => {
            setMessage(null);
            setOptionsReloads((value) => value + 1);
          }}
        >
          重新读取公众号
        </button>
      ) : page.error !== null ? (
        <div>
          <p className={styles.error} role="alert">
            {page.error}
          </p>
          <button type="button" onClick={refresh}>
            重试读取
          </button>
        </div>
      ) : tab === "drafts" ? (
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
                    accountName={
                      accounts?.find((account) => account.id === accountId)
                        ?.name ?? ""
                    }
                    when={when}
                    busy={busy}
                    disabled={actionsDisabled || pendingInvalid}
                    invalid={pendingInvalid}
                    onWhen={setWhen}
                    onNext={() => setPending({ ...pending, step: 2 })}
                    onConfirm={() => {
                      void confirm();
                    }}
                    onCancel={() =>
                      discardPending(() => {
                        setPending(null);
                      })
                    }
                  />
                ) : draft.open_job_id !== null ? (
                  <span className={styles.hint}>
                    已发布、正在发布或结果待核对，见「发布记录」
                  </span>
                ) : (
                  <span className={styles.rowActions}>
                    <button
                      type="button"
                      className={styles.primary}
                      disabled={actionsDisabled}
                      onClick={() =>
                        changeContext(() => {
                          setPending({ draft, when: "now", step: 1 });
                        })
                      }
                    >
                      立即发布
                    </button>
                    <button
                      type="button"
                      disabled={actionsDisabled}
                      onClick={() =>
                        changeContext(() => {
                          const nextWhen = defaultLocalTime();
                          setWhen(nextWhen);
                          setInitialWhen(nextWhen);
                          setPending({ draft, when: "later", step: 1 });
                        })
                      }
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
          <table className={styles.table} data-responsive="cards">
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
                <tr key={job.id}>
                  <td data-label="文章">
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
                  <td data-label="发布时间">{formatTime(job.scheduled_at)}</td>
                  <td data-label="状态">
                    <span
                      className={styles.statusBadge}
                      data-status={job.status}
                    >
                      {job.reconciled_by && job.status === "succeeded"
                        ? "人工核对已发布"
                        : JOB_STATUS_LABELS[job.status]}
                    </span>
                    {job.error === null ? null : (
                      <span className={styles.hint}>：{job.error}</span>
                    )}
                    {job.reconciliation_note ? (
                      <p className={styles.hint}>
                        核对依据：{job.reconciliation_note}
                      </p>
                    ) : null}
                  </td>
                  <td data-label="操作人">
                    {job.reconciled_by ?? job.cancelled_by ?? job.created_by}
                  </td>
                  <td data-label="操作">
                    {job.status === "scheduled" ? (
                      <button
                        type="button"
                        disabled={actionsDisabled}
                        onClick={() => {
                          void cancelJob(job);
                        }}
                      >
                        取消
                      </button>
                    ) : null}
                    {job.can_recheck ? (
                      <button
                        type="button"
                        disabled={actionsDisabled}
                        onClick={() => {
                          void recheck(job);
                        }}
                      >
                        重新查询结果
                      </button>
                    ) : null}
                    {job.status === "outcome_unknown" ? (
                      <>
                        <p className={styles.hint}>
                          请核对公众号后台，确认前不要再次发布。
                        </p>
                        {canReconcile ? (
                          <button
                            type="button"
                            disabled={actionsDisabled}
                            onClick={() =>
                              changeContext(() => setReconciling(job))
                            }
                          >
                            记录人工核对
                          </button>
                        ) : (
                          <span className={styles.hint}>
                            请管理员记录核对结果。
                          </span>
                        )}
                      </>
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
        <ol
          className={styles.articles}
          aria-label="已发布的文章"
          start={page.offset + 1}
        >
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
      {accountId !== null && tab !== "jobs" ? (
        <PageNavigation
          tab={tab}
          offset={page.offset}
          total={page.error !== null ? null : (page.data?.page?.total ?? null)}
          count={page.data?.page?.items.length ?? 0}
          loading={page.loading}
          busy={busy}
          onPage={(offset) => changeContext(() => page.changePage(offset))}
        />
      ) : null}
    </section>
  );
}

function PageNavigation({
  tab,
  offset,
  total,
  count,
  loading,
  busy,
  onPage,
}: {
  readonly tab: "drafts" | "published";
  readonly offset: number;
  readonly total: number | null;
  readonly count: number;
  readonly loading: boolean;
  readonly busy: boolean;
  readonly onPage: (offset: number) => void;
}) {
  return (
    <nav
      className={styles.pagination}
      aria-label={tab === "drafts" ? "草稿分页" : "已发布分页"}
    >
      <span aria-live="polite">
        {total === null
          ? loading
            ? "正在读取分页…"
            : "分页读取失败"
          : total === 0
            ? "共 0 条记录"
            : `共 ${total} 条记录 · 第 ${count === 0 ? 0 : offset + 1}–${Math.min(offset + count, total)} 条 · 第 ${Math.floor(offset / PUBLICATION_PAGE_SIZE) + 1}/${Math.ceil(total / PUBLICATION_PAGE_SIZE)} 页`}
      </span>
      <div className={styles.rowActions}>
        <button
          type="button"
          disabled={busy || loading || offset === 0}
          onClick={() => onPage(offset - PUBLICATION_PAGE_SIZE)}
        >
          上一页
        </button>
        <button
          type="button"
          disabled={
            busy ||
            loading ||
            total === null ||
            offset + PUBLICATION_PAGE_SIZE >= total
          }
          onClick={() => onPage(offset + PUBLICATION_PAGE_SIZE)}
        >
          下一页
        </button>
      </div>
    </nav>
  );
}

function PublishConfirm({
  pending,
  accountName,
  when,
  busy,
  disabled,
  invalid,
  onWhen,
  onNext,
  onConfirm,
  onCancel,
}: {
  readonly pending: NonNullable<Pending>;
  readonly accountName: string;
  readonly when: string;
  readonly busy: boolean;
  readonly disabled: boolean;
  readonly invalid: boolean;
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
              disabled={disabled}
              onChange={(event) => onWhen(event.target.value)}
            />
          </label>
        ) : (
          <span>将立即公开发布这组草稿的全部篇目。</span>
        )}
        <button
          type="button"
          className={styles.primary}
          disabled={disabled}
          onClick={onNext}
        >
          下一步
        </button>
        <button type="button" disabled={busy} onClick={onCancel}>
          取消
        </button>
      </div>
    );
  }
  return (
    <div className={styles.issued} role="alertdialog" aria-label="再次确认发布">
      {invalid ? (
        <p className={styles.error} role="alert">
          草稿内容已更新或已有发布记录，请返回后重新核对。
        </p>
      ) : null}
      <p>
        <strong>再次确认：</strong>
        {pending.when === "later"
          ? `${when.replace("T", " ")} 将公开发布以下全部篇目，开始前可以取消排期。`
          : "即将公开发布以下全部篇目。"}
      </p>
      <p>
        公众号：<strong>{accountName}</strong>
      </p>
      <ol aria-label="本次发布的全部篇目">
        {pending.draft.articles.map((article, index) => (
          <li key={index}>{article.title || "（无标题）"}</li>
        ))}
      </ol>
      <p>
        这是公开发布，不会向粉丝群发。发布后可通过文章链接访问，请确认公众号与全部篇目无误。
      </p>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          disabled={disabled}
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

function ReconcileForm({
  job,
  busy,
  onConfirm,
  onCancel,
}: {
  readonly job: PublishJob;
  readonly busy: boolean;
  readonly onConfirm: (input: PublishReconcile) => void;
  readonly onCancel: () => void;
}) {
  const [result, setResult] = useState<PublishReconcile["result"]>("published");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const { requestDiscard } = useUnsavedChanges(
    note !== "" || result !== "published" || confirmed,
    () => {
      setNote("");
      setResult("published");
      setConfirmed(false);
    },
  );
  return (
    <form
      className={styles.reconcileForm}
      aria-label="记录人工核对"
      onSubmit={(event) => {
        event.preventDefault();
        if (busy || !confirmed || note.trim().length < 5) return;
        onConfirm({
          result,
          note: note.trim(),
          confirmed: true,
          expected_updated_at: job.updated_at,
        });
      }}
    >
      <p>
        公众号：{job.account_name} · {job.title}
      </p>
      <p>请先在公众号后台核实文章状态。这里只记录核对结果，不会提交发布。</p>
      <label>
        核对结果
        <select
          value={result}
          disabled={busy}
          onChange={(event) => {
            setResult(
              event.target.value === "not_published"
                ? "not_published"
                : "published",
            );
            setConfirmed(false);
          }}
        >
          <option value="published">已发布（继续禁止重复提交）</option>
          <option value="not_published">确认未发布（允许重新提交）</option>
        </select>
      </label>
      <label>
        核对依据
        <textarea
          value={note}
          minLength={5}
          maxLength={500}
          required
          disabled={busy}
          onChange={(event) => setNote(event.target.value)}
          placeholder="填写核对时间、文章链接或后台核对情况（至少 5 字）"
        />
      </label>
      <label className={styles.checkboxField}>
        <input
          type="checkbox"
          checked={confirmed}
          disabled={busy}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        我已在公众号后台核对，确认上述结果准确
      </label>
      <div className={styles.actions}>
        <button
          type="submit"
          className={styles.primary}
          disabled={busy || !confirmed || note.trim().length < 5}
        >
          保存核对结果
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => requestDiscard(onCancel)}
        >
          取消核对
        </button>
      </div>
    </form>
  );
}
