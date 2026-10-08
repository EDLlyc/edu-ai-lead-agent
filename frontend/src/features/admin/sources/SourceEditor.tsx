import { useState, type FormEvent } from "react";

import styles from "../Admin.module.css";
import type {
  AdminSource,
  SourceConfig,
  SourceDraft,
  SourcePreview,
  SourcesApi,
} from "./api";
import {
  ORGANIZATION_LABELS,
  TIER_LABELS,
  formatDate,
  sampleVerdict,
} from "./labels";

type Kind = SourceConfig["kind"];

function words(value: string): string[] {
  return value.split(/\s+/).filter((word) => word !== "");
}

function selectors(value: string): string[] {
  return value
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter((item) => item !== "");
}

/** Add or edit an operator source. Saving needs a successful preview of the same settings. */
export function SourceEditor({
  api,
  source,
  onSaved,
  onCancel,
  onError,
}: {
  readonly api: SourcesApi;
  readonly source: AdminSource | null;
  readonly onSaved: (source: AdminSource) => void;
  readonly onCancel: () => void;
  readonly onError: (error: unknown) => boolean;
}) {
  const config = source?.config ?? null;
  const [name, setName] = useState(source?.display_name ?? "");
  const [entryUrl, setEntryUrl] = useState(source?.entry_url ?? "https://");
  const [kind, setKind] = useState<Kind>(config?.kind ?? "html");
  const [organization, setOrganization] = useState<
    SourceDraft["organization_type"]
  >(
    (source?.organization_type as SourceDraft["organization_type"]) ??
      "authoritative_media",
  );
  const [tier, setTier] = useState<SourceDraft["tier"]>(source?.tier ?? "B");
  const [linkContains, setLinkContains] = useState(
    (config?.link_contains ?? []).join(" "),
  );
  const [listSelectors, setListSelectors] = useState(
    (config?.list_selectors ?? []).join(", "),
  );
  const [contentSelectors, setContentSelectors] = useState(
    (config?.content_selectors ?? []).join(", "),
  );
  const [preview, setPreview] = useState<{
    readonly key: string;
    readonly result: SourcePreview;
  } | null>(null);
  const [busy, setBusy] = useState<"preview" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const currentConfig: SourceConfig = {
    kind,
    link_contains: kind === "html" ? words(linkContains) : [],
    list_selectors: kind === "html" ? selectors(listSelectors) : [],
    content_selectors: selectors(contentSelectors),
  };
  const fetchKey = JSON.stringify([entryUrl.trim(), currentConfig]);
  const previewed = preview !== null && preview.key === fetchKey;
  const canSave = previewed && preview.result.ok && name.trim().length >= 2;

  const fail = (failure: unknown) => {
    if (onError(failure)) return;
    setError(failure instanceof Error ? failure.message : "操作失败");
  };

  const runPreview = async () => {
    setBusy("preview");
    setError(null);
    try {
      const result = await api.preview(entryUrl.trim(), currentConfig);
      setPreview({ key: fetchKey, result });
    } catch (failure) {
      fail(failure);
    } finally {
      setBusy(null);
    }
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSave) return;
    setBusy("save");
    setError(null);
    const draft: SourceDraft = {
      display_name: name.trim(),
      entry_url: entryUrl.trim(),
      organization_type: organization,
      tier,
      config: currentConfig,
    };
    try {
      onSaved(
        source === null
          ? await api.create(draft)
          : await api.update(source.id, draft),
      );
    } catch (failure) {
      fail(failure);
      setBusy(null);
    }
  };

  return (
    <form
      className={styles.editor}
      aria-label={source === null ? "新增新闻源" : "修改新闻源"}
      onSubmit={(event) => {
        void save(event);
      }}
    >
      <h3>
        {source === null ? "新增新闻源" : `修改「${source.display_name}」`}
      </h3>
      <div className={styles.formGrid}>
        <label className={styles.field}>
          <span>名称</span>
          <input
            value={name}
            maxLength={60}
            required
            placeholder="例如：中国教育新闻网"
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>网址（列表页或 RSS 地址）</span>
          <input
            value={entryUrl}
            type="url"
            required
            inputMode="url"
            spellCheck={false}
            onChange={(event) => setEntryUrl(event.target.value)}
          />
        </label>
        <fieldset className={styles.choice}>
          <legend>类型</legend>
          <label>
            <input
              type="radio"
              name="source-kind"
              checked={kind === "html"}
              onChange={() => setKind("html")}
            />
            网页列表
          </label>
          <label>
            <input
              type="radio"
              name="source-kind"
              checked={kind === "rss"}
              onChange={() => setKind("rss")}
            />
            RSS
          </label>
        </fieldset>
        <label className={styles.field}>
          <span>机构类型</span>
          <select
            value={organization}
            onChange={(event) =>
              setOrganization(
                event.target.value as SourceDraft["organization_type"],
              )
            }
          >
            {Object.entries(ORGANIZATION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>可信度</span>
          <select
            value={tier}
            onChange={(event) =>
              setTier(event.target.value as SourceDraft["tier"])
            }
          >
            <option value="B">{TIER_LABELS.B}（媒体、一般网站）</option>
            <option value="A">
              {TIER_LABELS.A}（政府、高校、科研院所官网）
            </option>
          </select>
        </label>
      </div>
      <details className={styles.advanced} open={config !== null}>
        <summary>高级设置（预览抓错了再填）</summary>
        {kind === "html" ? (
          <>
            <label className={styles.field}>
              <span>文章链接包含（空格分隔，例如 content_ /article/）</span>
              <input
                value={linkContains}
                spellCheck={false}
                onChange={(event) => setLinkContains(event.target.value)}
              />
            </label>
            <label className={styles.field}>
              <span>列表位置（CSS 选择器，例如 .news-list）</span>
              <input
                value={listSelectors}
                spellCheck={false}
                onChange={(event) => setListSelectors(event.target.value)}
              />
            </label>
          </>
        ) : null}
        <label className={styles.field}>
          <span>正文位置（CSS 选择器，例如 .article-content）</span>
          <input
            value={contentSelectors}
            spellCheck={false}
            onChange={(event) => setContentSelectors(event.target.value)}
          />
        </label>
      </details>

      {preview === null ? null : (
        <PreviewResult result={preview.result} stale={!previewed} />
      )}
      {error === null ? null : (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <div className={styles.actions}>
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => {
            void runPreview();
          }}
        >
          {busy === "preview" ? "正在抓取预览…" : "预览"}
        </button>
        <button
          type="submit"
          className={styles.primary}
          disabled={!canSave || busy !== null}
          title={canSave ? undefined : "先预览，能抓到文章才能保存"}
        >
          {busy === "save" ? "正在保存…" : "保存"}
        </button>
        <button type="button" onClick={onCancel} disabled={busy === "save"}>
          取消
        </button>
      </div>
      <p className={styles.hint}>
        {source === null
          ? "新增的新闻源默认是关闭的，确认没问题后在列表里打开。"
          : "修改会生成新版本，下一轮抓取开始用新设置。"}
      </p>
    </form>
  );
}

function PreviewResult({
  result,
  stale,
}: {
  readonly result: SourcePreview;
  readonly stale: boolean;
}) {
  const kept = result.samples.filter(
    (sample) => sampleVerdict(sample).kept,
  ).length;
  return (
    <section className={styles.preview} aria-label="预览结果">
      {stale ? <p className={styles.notice}>设置改过了，请重新预览。</p> : null}
      {result.problem !== null ? (
        <p className={styles.error}>{result.problem}</p>
      ) : (
        <p>
          找到 {result.links.length} 篇文章，抽查前 {result.samples.length} 篇：
          {kept} 篇会收录。
          {result.robots === "no_robots_file" ? "（网站没有 robots.txt）" : ""}
        </p>
      )}
      {result.samples.length === 0 ? null : (
        <ul className={styles.samples}>
          {result.samples.map((sample) => {
            const verdict = sampleVerdict(sample);
            return (
              <li key={sample.url} data-kept={verdict.kept}>
                <strong>{sample.title ?? sample.url}</strong>
                <span>
                  {formatDate(sample.published_at)} · 正文 {sample.characters}{" "}
                  字 · {verdict.text}
                </span>
                {sample.excerpt === "" ? null : (
                  <small>{sample.excerpt}…</small>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {result.links.length > result.samples.length ? (
        <details>
          <summary>全部 {result.links.length} 个链接</summary>
          <ol>
            {result.links.map((link) => (
              <li key={link.url}>{link.title ?? link.url}</li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  );
}
