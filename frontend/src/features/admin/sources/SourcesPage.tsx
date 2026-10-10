import { Fragment, useCallback, useEffect, useState } from "react";

import styles from "../Admin.module.css";
import { AdminSessionExpiredError } from "../api";
import {
  sourcesApi as defaultApi,
  type AdminSource,
  type SourceArticle,
  type SourcesApi,
} from "./api";
import { SourceEditor } from "./SourceEditor";
import {
  TIER_LABELS,
  formatDate,
  formatTime,
  kindLabel,
  latestJobLabel,
} from "./labels";

type Editing = { readonly source: AdminSource | null } | null;
type Pending = {
  readonly id: string;
  readonly action: "enable" | "disable" | "archive";
} | null;

const CONFIRM_TEXT = {
  enable: "确认打开？下一轮抓取开始抓它。",
  disable: "确认关闭？下一轮抓取起不再抓它，已抓的新闻保留。",
  archive: "确认删除？会从列表里移走、不再抓取，历史记录保留。",
} as const;

/** 运营后台 · 新闻源: which sites feed the daily news selection. */
export function SourcesPage({
  api = defaultApi,
  onSessionExpired,
}: {
  readonly api?: SourcesApi;
  readonly onSessionExpired: () => void;
}) {
  const [sources, setSources] = useState<readonly AdminSource[] | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [reloads, setReloads] = useState(0);
  const [editing, setEditing] = useState<Editing>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [busy, setBusy] = useState(false);
  const [openArticles, setOpenArticles] = useState<{
    readonly id: string;
    readonly items: readonly SourceArticle[] | null;
  } | null>(null);
  const [message, setMessage] = useState<{
    readonly kind: "ok" | "error";
    readonly text: string;
  } | null>(null);

  const handleError = useCallback(
    (error: unknown): boolean => {
      if (error instanceof AdminSessionExpiredError) {
        onSessionExpired();
        return true;
      }
      return false;
    },
    [onSessionExpired],
  );

  useEffect(() => {
    let cancelled = false;
    api.list(showArchived).then(
      (items) => {
        if (!cancelled) setSources(items);
      },
      (error: unknown) => {
        if (cancelled || handleError(error)) return;
        setMessage({
          kind: "error",
          text: error instanceof Error ? error.message : "读取失败",
        });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, handleError, showArchived, reloads]);

  const reload = () => setReloads((count) => count + 1);

  const confirm = async (action: NonNullable<Pending>) => {
    setBusy(true);
    try {
      if (action.action === "archive") {
        await api.archive(action.id);
        setMessage({ kind: "ok", text: "已删除（归档）" });
      } else {
        const updated = await api.setEnabled(
          action.id,
          action.action === "enable",
        );
        setMessage({
          kind: "ok",
          text: `已${updated.enabled ? "打开" : "关闭"}「${updated.display_name}」`,
        });
      }
      setPending(null);
      reload();
    } catch (error) {
      if (!handleError(error)) {
        setMessage({
          kind: "error",
          text: error instanceof Error ? error.message : "操作失败",
        });
      }
    } finally {
      setBusy(false);
    }
  };

  const toggleArticles = async (id: string) => {
    if (openArticles?.id === id) {
      setOpenArticles(null);
      return;
    }
    setOpenArticles({ id, items: null });
    try {
      const items = await api.articles(id);
      setOpenArticles((current) =>
        current?.id === id ? { id, items } : current,
      );
    } catch (error) {
      setOpenArticles(null);
      if (!handleError(error)) {
        setMessage({
          kind: "error",
          text: error instanceof Error ? error.message : "读取失败",
        });
      }
    }
  };

  const enabledCount = sources?.filter((source) => source.enabled).length ?? 0;

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">新闻源</h2>
        <button
          type="button"
          className={styles.primary}
          disabled={editing !== null}
          onClick={() => {
            setMessage(null);
            setEditing({ source: null });
          }}
        >
          新增新闻源
        </button>
      </header>
      <p className={styles.lede}>
        每天抓取这些网站的新闻，再由 AI
        选题。「内置」的只能开关；新增的可以修改、删除。
        {sources === null ? null : `现在打开了 ${enabledCount} 个。`}
      </p>
      {message === null ? null : (
        <p
          className={message.kind === "error" ? styles.error : styles.success}
          role={message.kind === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}
      {editing === null ? null : (
        <SourceEditor
          api={api}
          source={editing.source}
          onError={handleError}
          onCancel={() => setEditing(null)}
          onSaved={(saved) => {
            setEditing(null);
            setMessage({
              kind: "ok",
              text:
                editing.source === null
                  ? `已新增「${saved.display_name}」，现在是关闭的，确认后再打开`
                  : `已保存「${saved.display_name}」（第 ${saved.version} 版）`,
            });
            reload();
          }}
        />
      )}
      {sources === null ? (
        message?.kind === "error" ? null : (
          <p role="status">正在读取…</p>
        )
      ) : (
        <table
          className={`${styles.table} ${styles.sourceTable}`}
          data-responsive="cards"
        >
          <thead>
            <tr>
              <th scope="col">名称</th>
              <th scope="col">类型</th>
              <th scope="col">可信度</th>
              <th scope="col">最近一次抓取</th>
              <th className={styles.numeric} scope="col">
                7 天新增
              </th>
              <th scope="col">状态</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <Fragment key={source.id}>
                <tr data-enabled={source.enabled}>
                  <td className={styles.cellTitle} data-label="名称">
                    <a
                      href={source.entry_url}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {source.display_name}
                    </a>
                  </td>
                  <td className={styles.compactCell} data-label="类型">
                    {kindLabel(source)}
                  </td>
                  <td className={styles.compactCell} data-label="可信度">
                    {TIER_LABELS[source.tier]}
                  </td>
                  <td data-label="最近一次抓取">{latestJobLabel(source)}</td>
                  <td
                    className={`${styles.numeric} ${styles.compactCell}`}
                    data-label="7 天新增"
                  >
                    {source.new_last_7_days}
                  </td>
                  <td className={styles.compactCell} data-label="状态">
                    {source.archived_at !== null
                      ? "已删除"
                      : source.enabled
                        ? "打开"
                        : "关闭"}
                  </td>
                  <td data-label="操作">
                    {pending?.id === source.id ? (
                      <span
                        className={styles.confirm}
                        role="group"
                        aria-label="确认操作"
                      >
                        {CONFIRM_TEXT[pending.action]}
                        <button
                          type="button"
                          className={
                            pending.action === "archive"
                              ? styles.danger
                              : styles.primary
                          }
                          disabled={busy}
                          onClick={() => {
                            void confirm(pending);
                          }}
                        >
                          确认
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => setPending(null)}
                        >
                          取消
                        </button>
                      </span>
                    ) : source.archived_at !== null ? null : (
                      <span className={styles.rowActions}>
                        <button
                          type="button"
                          className={styles.secondary}
                          aria-expanded={openArticles?.id === source.id}
                          onClick={() => {
                            void toggleArticles(source.id);
                          }}
                        >
                          最近文章
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setPending({
                              id: source.id,
                              action: source.enabled ? "disable" : "enable",
                            })
                          }
                        >
                          {source.enabled ? "关闭" : "打开"}
                        </button>
                        {source.managed_by === "operator" ? (
                          <>
                            <button
                              type="button"
                              disabled={editing !== null}
                              onClick={() => {
                                setMessage(null);
                                setEditing({ source });
                              }}
                            >
                              修改
                            </button>
                            <button
                              type="button"
                              className={styles.danger}
                              onClick={() =>
                                setPending({ id: source.id, action: "archive" })
                              }
                            >
                              删除
                            </button>
                          </>
                        ) : null}
                      </span>
                    )}
                  </td>
                </tr>
                {openArticles?.id === source.id ? (
                  <tr className={styles.articlesRow}>
                    <td colSpan={7} data-label="最近收录的文章">
                      <ArticleList items={openArticles.items} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
      <label className={styles.toggle}>
        <input
          type="checkbox"
          checked={showArchived}
          onChange={(event) => setShowArchived(event.target.checked)}
        />
        显示已删除的
      </label>
    </section>
  );
}

function ArticleList({
  items,
}: {
  readonly items: readonly SourceArticle[] | null;
}) {
  if (items === null) return <p role="status">正在读取…</p>;
  if (items.length === 0) return <p>还没有收录过文章。</p>;
  return (
    <ol className={styles.articles} aria-label="最近收录的文章">
      {items.map((item) => (
        <li key={item.url}>
          <a href={item.url} target="_blank" rel="noreferrer noopener">
            {item.title}
          </a>
          <span>
            发布 {formatDate(item.published_at)} · 收录{" "}
            {formatTime(item.fetched_at)}
          </span>
        </li>
      ))}
    </ol>
  );
}
