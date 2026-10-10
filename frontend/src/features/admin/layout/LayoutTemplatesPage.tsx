import { useCallback, useEffect, useState } from "react";

import styles from "../Admin.module.css";
import { AdminSessionExpiredError } from "../api";
import {
  layoutApi as defaultApi,
  type LayoutAccount,
  type LayoutApi,
  type LayoutTemplate,
} from "./api";

// The preview frame gets no scripts and no access to the console; only our sample is shown.
function previewDocument(body: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;padding:12px;background:#fff;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}img{max-width:100%}</style></head><body>${body}</body></html>`;
}

/** 运营后台 · 公众号 · 排版模板: preview a colour scheme, then use it for an account. */
export function LayoutTemplatesPage({
  api = defaultApi,
  onSessionExpired,
}: {
  readonly api?: LayoutApi;
  readonly onSessionExpired: () => void;
}) {
  const [templates, setTemplates] = useState<readonly LayoutTemplate[] | null>(
    null,
  );
  const [accounts, setAccounts] = useState<readonly LayoutAccount[]>([]);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [preview, setPreview] = useState<{
    readonly id: string;
    readonly html: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
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
    api.list().then(
      (loaded) => {
        if (cancelled) return;
        setTemplates(loaded.templates);
        setAccounts(loaded.accounts);
        const first = loaded.accounts[0];
        setAccountId(first?.id ?? null);
        setSelected(
          first?.layout_template_id ??
            loaded.templates.find((template) => template.is_default)?.id ??
            null,
        );
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
    if (selected === null) return;
    let cancelled = false;
    api.preview(selected).then(
      (html) => {
        if (!cancelled) setPreview({ id: selected, html });
      },
      (error: unknown) => {
        if (!cancelled) fail(error);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, selected, fail]);

  const account = accounts.find((item) => item.id === accountId) ?? null;
  const nameOf = (id: string) =>
    templates?.find((template) => template.id === id)?.name ?? id;

  const choose = async () => {
    if (account === null || selected === null) return;
    setBusy(true);
    setMessage(null);
    try {
      const saved = await api.choose(account.id, selected);
      setAccounts((items) =>
        items.map((item) => (item.id === saved.id ? saved : item)),
      );
      setMessage({
        kind: "ok",
        text: `「${saved.name}」的模板已保存为「${nameOf(saved.layout_template_id)}」`,
      });
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">公众号 · 排版模板</h2>
        {accounts.length < 2 ? null : (
          <select
            aria-label="公众号"
            value={accountId ?? ""}
            onChange={(event) => {
              const next = accounts.find(
                (item) => item.id === event.target.value,
              );
              setAccountId(event.target.value);
              if (next !== undefined) setSelected(next.layout_template_id);
              setMessage(null);
            }}
          >
            {accounts.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        )}
      </header>
      <p className={styles.lede}>
        预览配色，再为公众号保存模板。版式、文字、图片和首尾横幅保持原样。
      </p>
      <details className={styles.guidance}>
        <summary>使用说明：新草稿、重试与已有草稿</summary>
        <p>
          支持模板的自动单篇草稿流程会在新草稿首次上传时读取这里的选择；重试沿用首次选择，已有草稿不变。
        </p>
      </details>
      <p className={styles.notice}>
        本页显示已保存的配置，未检测草稿服务的实时运行状态；生成后请在草稿箱核对效果。
      </p>
      {account === null && templates !== null ? (
        <p className={styles.notice} role="status">
          还没有可用的公众号，可以先预览；请管理员在「公众号 ·
          账号」里绑定后再保存选择。
        </p>
      ) : account === null ? null : (
        <p>
          「{account.name}」已保存的模板：
          <strong>{nameOf(account.layout_template_id)}</strong>
        </p>
      )}
      {message === null ? null : (
        <p
          className={message.kind === "error" ? styles.error : styles.success}
          role={message.kind === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}
      {templates === null ? (
        message?.kind === "error" ? null : (
          <p role="status">正在读取…</p>
        )
      ) : (
        <div className={styles.layoutGrid}>
          <fieldset className={styles.layoutChoices}>
            <legend>选一个模板预览</legend>
            {templates.map((template) => (
              <label
                key={template.id}
                className={styles.layoutChoice}
                data-selected={template.id === selected}
              >
                <input
                  type="radio"
                  name="layout-template"
                  value={template.id}
                  checked={template.id === selected}
                  onChange={() => {
                    setSelected(template.id);
                    setMessage(null);
                  }}
                />
                <span className={styles.layoutChoiceText}>
                  <strong>
                    {template.name}
                    {account?.layout_template_id === template.id ? (
                      <span className={styles.badge}>已保存</span>
                    ) : null}
                  </strong>
                  <span className={styles.swatches} aria-hidden="true">
                    {template.swatches.map((colour) => (
                      <span key={colour} style={{ background: colour }} />
                    ))}
                  </span>
                  <small>{template.description}</small>
                </span>
              </label>
            ))}
            {account === null || selected === null ? null : (
              <button
                type="button"
                className={styles.primary}
                disabled={busy || account.layout_template_id === selected}
                onClick={() => {
                  void choose();
                }}
              >
                {busy
                  ? "正在保存…"
                  : account.layout_template_id === selected
                    ? "已保存这个模板"
                    : `给「${account.name}」保存「${nameOf(selected)}」`}
              </button>
            )}
          </fieldset>
          <figure className={styles.layoutPreview}>
            <figcaption>
              预览{selected === null ? "" : `：${nameOf(selected)}`}
              <small>（示例文章，图片用灰色占位）</small>
            </figcaption>
            {preview === null || preview.id !== selected ? (
              <p role="status">正在生成预览…</p>
            ) : (
              <iframe
                title={`排版预览：${nameOf(preview.id)}`}
                sandbox=""
                srcDoc={previewDocument(preview.html)}
              />
            )}
          </figure>
        </div>
      )}
    </section>
  );
}
