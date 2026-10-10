import { useCallback, useEffect, useState } from "react";

import styles from "../Admin.module.css";
import { AdminSessionExpiredError } from "../api";
import { formatDate } from "../sources/labels";
import {
  wechatApi as defaultApi,
  type WeChatAccountOption,
  type WeChatApi,
  type WeChatStats,
} from "./api";
import {
  shiftDate,
  statsDays,
  statsSummary,
  statsTotal,
  type StatsDay,
} from "./statsView";

const DAYS = 30;
// Single-series magnitude bars; validated (lightness, chroma, contrast) on the white surface.
const BAR = "#0d9488";

function shortDate(iso: string): string {
  return iso.slice(5).replace("-", "/");
}

function percent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 1000) / 10}%`;
}

/** 运营后台 · 公众号 · 数据: reading numbers synced from WeChat once a day. */
export function WeChatStatsPage({
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
  const [stats, setStats] = useState<WeChatStats | null>(null);
  const [reloads, setReloads] = useState(0);
  const [syncing, setSyncing] = useState(false);
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
        text: error instanceof Error ? error.message : "读取失败",
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
    api.stats(accountId, DAYS).then(
      (loaded) => {
        if (!cancelled) setStats(loaded);
      },
      (error: unknown) => {
        if (!cancelled) fail(error);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, accountId, reloads, fail]);

  const sync = async () => {
    if (accountId === null) return;
    setSyncing(true);
    setMessage(null);
    try {
      const report = await api.syncStats(accountId);
      setMessage({
        kind: "ok",
        text: `已同步：${report.articles} 篇文章、${report.days} 天的有效公众号数据`,
      });
      setReloads((count) => count + 1);
    } catch (error) {
      fail(error);
    } finally {
      setSyncing(false);
    }
  };

  if (accounts !== null && accounts.length === 0) {
    return (
      <section aria-labelledby="admin-section-title">
        <header className={styles.sectionHeader}>
          <h2 id="admin-section-title">公众号 · 数据</h2>
        </header>
        <p className={styles.notice}>
          还没有可用的公众号。请管理员先在「公众号 · 账号」里绑定。
        </p>
      </section>
    );
  }

  const daily = stats === null ? [] : statsDays(stats);
  const lastWeek =
    stats === null
      ? []
      : daily.filter((day) => day.date >= shiftDate(stats.range_end, -6));

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">公众号 · 数据</h2>
        <span className={styles.rowActions}>
          {accounts === null || accounts.length < 2 ? null : (
            <select
              aria-label="公众号"
              value={accountId ?? ""}
              disabled={syncing}
              onChange={(event) => {
                setAccountId(event.target.value);
                setStats(null);
                setMessage(null);
              }}
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            disabled={syncing || accountId === null}
            onClick={() => {
              void sync();
            }}
          >
            {syncing ? "正在同步…" : "立即同步"}
          </button>
        </span>
      </header>
      <p className={styles.lede}>
        每天上午 10 点后自动同步，并补查最近 30 天内缺失的数据。
        {stats?.synced_on
          ? `最近同步：${formatDate(stats.synced_on)}。`
          : "还没同步过。"}
        微信只统计群发的文章，阅读很少时部分数字不显示。每日人数相加，未按整个区间去重。
      </p>
      {stats?.sync_error ? (
        <p className={styles.error} role="alert">
          上次同步失败：{stats.sync_error}
        </p>
      ) : null}
      {message === null ? null : (
        <p
          className={message.kind === "error" ? styles.error : styles.success}
          role={message.kind === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}

      {stats === null ? (
        <p role="status">正在读取…</p>
      ) : (
        <>
          <p className={styles.notice}>
            统计日期：{formatDate(stats.range_start)} 至{" "}
            {formatDate(stats.range_end)}。 已有{" "}
            {daily.filter((day) => day.values !== null).length}/{daily.length}{" "}
            天数据， 缺少 {daily.filter((day) => day.values === null).length}{" "}
            天。 缺失不计为 0，部分数据的合计仅显示已知值。
          </p>
          <div className={styles.tiles} aria-label="近 7 天">
            {(
              [
                ["阅读人数之和", "read_user"],
                ["分享人数之和", "share_user"],
                ["点赞人数之和", "like_user"],
                ["在看人数之和", "zaikan_user"],
                ["收藏人数之和", "collection_user"],
              ] as const
            ).map(([label, key]) => {
              const { total, missing } = statsSummary(lastWeek, key);
              return (
                <div key={key} className={styles.tile}>
                  <span>近 7 天{label}</span>
                  <strong>{total ?? "—"}</strong>
                  <span
                    className={styles.statusBadge}
                    data-status={
                      total === null
                        ? "missing"
                        : missing > 0
                          ? "partial"
                          : "complete"
                    }
                  >
                    {total === null
                      ? "暂无数据"
                      : missing > 0
                        ? `已知值 · 缺 ${missing} 天`
                        : "7 天完整数据"}
                  </span>
                  <small>近 30 天 {statsTotal(daily, key)}</small>
                </div>
              );
            })}
          </div>
          <DailyReadsChart key={accountId} rows={daily} />
          <h3 className={styles.subheading}>文章（近 30 天发布）</h3>
          {stats.articles.length === 0 ? (
            <p>近 30 天还没有群发文章的数据。</p>
          ) : (
            <div
              className={styles.tableScroll}
              tabIndex={0}
              role="region"
              aria-label="文章数据表，可横向滚动"
            >
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">文章</th>
                    <th scope="col">发布日期</th>
                    <th scope="col">阅读人数</th>
                    <th scope="col">分享</th>
                    <th scope="col">收藏</th>
                    <th scope="col">送达阅读率</th>
                    <th scope="col">主要来源</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.articles.map((article) => (
                    <tr key={article.msgid}>
                      <td>
                        {article.url === null ? (
                          article.title
                        ) : (
                          <a
                            href={article.url}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            {article.title}
                          </a>
                        )}
                      </td>
                      <td>{formatDate(article.publish_date)}</td>
                      <td>{article.read_user}</td>
                      <td>{article.share_user}</td>
                      <td>{article.collection_user}</td>
                      <td>{percent(article.read_delivery_rate)}</td>
                      <td>{topSources(article.read_sources)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function topSources(sources: Readonly<Record<string, number>>): string {
  const ranked = Object.entries(sources)
    .filter(([scene, count]) => scene !== "全部" && count > 0)
    .sort((left, right) => right[1] - left[1])
    .slice(0, 2);
  return ranked.length === 0
    ? "—"
    : ranked.map(([scene, count]) => `${scene} ${count}`).join("、");
}

const CHART_HEIGHT = 140;
const BAR_GAP = 2;

/** Daily account-wide readers as thin bars; hover or focus a bar for that day's numbers. */
function DailyReadsChart({ rows }: { readonly rows: readonly StatsDay[] }) {
  const [active, setActive] = useState<number | null>(null);
  if (!rows.some((row) => row.values !== null)) {
    return (
      <p className={styles.hint}>
        还没有每日数据，同步后这里显示近 30 天的阅读走势。
      </p>
    );
  }
  const max = Math.max(0, ...rows.map((row) => row.values?.read_user ?? 0));
  const width = 720;
  const slot = width / rows.length;
  const barWidth = Math.max(2, slot - BAR_GAP);
  const shown = active === null ? null : rows[active];
  return (
    <figure className={styles.chart}>
      <figcaption>
        每日阅读人数（公众号整体，近 {rows.length} 天，最高 {max}；断点为缺失）
      </figcaption>
      <div className={styles.chartBody}>
        <svg
          viewBox={`0 0 ${width} ${CHART_HEIGHT + 20}`}
          role="img"
          aria-label={`每日阅读人数，近 ${rows.length} 天合计 ${statsTotal(rows, "read_user")}，最高 ${max}`}
          onMouseLeave={() => setActive(null)}
        >
          <line
            x1={0}
            x2={width}
            y1={CHART_HEIGHT}
            y2={CHART_HEIGHT}
            stroke="#c4cfcb"
            strokeWidth={1}
          />
          {rows.map((row, index) => {
            const height =
              ((row.values?.read_user ?? 0) / Math.max(1, max)) *
              (CHART_HEIGHT - 8);
            const x = index * slot + BAR_GAP / 2;
            const radius = Math.min(4, barWidth / 2, height);
            const top = CHART_HEIGHT - height;
            return (
              <g key={row.date}>
                {row.values === null ? (
                  <text
                    x={x + barWidth / 2}
                    y={CHART_HEIGHT - 4}
                    textAnchor="middle"
                    className={styles.axisText}
                  >
                    ×
                  </text>
                ) : null}
                {height > 0 ? (
                  <path
                    d={`M${x},${CHART_HEIGHT} V${top + radius} Q${x},${top} ${x + radius},${top} H${x + barWidth - radius} Q${x + barWidth},${top} ${x + barWidth},${top + radius} V${CHART_HEIGHT} Z`}
                    fill={BAR}
                    opacity={active === null || active === index ? 1 : 0.45}
                  />
                ) : null}
                {/* Hit target taller and wider than the bar; the table below carries the values. */}
                <rect
                  x={index * slot}
                  y={0}
                  width={slot}
                  height={CHART_HEIGHT}
                  fill="transparent"
                  data-day={row.date}
                  onMouseEnter={() => setActive(index)}
                />
              </g>
            );
          })}
          <text x={0} y={CHART_HEIGHT + 16} className={styles.axisText}>
            {shortDate(rows[0]!.date)}
          </text>
          <text
            x={width}
            y={CHART_HEIGHT + 16}
            textAnchor="end"
            className={styles.axisText}
          >
            {shortDate(rows[rows.length - 1]!.date)}
          </text>
        </svg>
        {shown === null || shown === undefined ? null : (
          <div className={styles.tooltip} role="status">
            <strong>{shortDate(shown.date)}</strong>{" "}
            {shown.values === null
              ? "缺少数据"
              : `阅读 ${shown.values.read_user} · 分享 ${shown.values.share_user} · 点赞 ${shown.values.like_user} · 在看 ${shown.values.zaikan_user}`}
          </div>
        )}
      </div>
      <details>
        <summary>看表格</summary>
        <div
          className={styles.tableScroll}
          tabIndex={0}
          role="region"
          aria-label="每日数据表，可横向滚动"
        >
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">日期</th>
                <th scope="col">阅读</th>
                <th scope="col">分享</th>
                <th scope="col">点赞</th>
                <th scope="col">在看</th>
                <th scope="col">评论</th>
              </tr>
            </thead>
            <tbody>
              {[...rows].reverse().map((row) => (
                <tr key={row.date}>
                  <td>{shortDate(row.date)}</td>
                  {row.values === null ? (
                    <td colSpan={5}>缺少数据</td>
                  ) : (
                    <>
                      <td>{row.values.read_user}</td>
                      <td>{row.values.share_user}</td>
                      <td>{row.values.like_user}</td>
                      <td>{row.values.zaikan_user}</td>
                      <td>{row.values.comment_count}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
