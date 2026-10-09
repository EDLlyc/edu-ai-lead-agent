import { useCallback, useEffect, useState, type FormEvent } from "react";

import styles from "../Admin.module.css";
import { AdminSessionExpiredError } from "../api";
import { splitTerms } from "../keywords/api";
import { formatTime } from "../sources/labels";
import {
  wechatApi as defaultApi,
  type WeChatAccount,
  type WeChatApi,
} from "./api";

/** 运营后台 · 公众号 · 账号 (owner only): bind accounts and their topics. */
export function WeChatAccountsPage({
  api = defaultApi,
  onSessionExpired,
}: {
  readonly api?: WeChatApi;
  readonly onSessionExpired: () => void;
}) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [accounts, setAccounts] = useState<readonly WeChatAccount[] | null>(
    null,
  );
  const [reloads, setReloads] = useState(0);
  const [binding, setBinding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
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
    Promise.all([api.status(), api.accounts()]).then(
      ([status, items]) => {
        if (cancelled) return;
        setConfigured(status.secretKeyConfigured);
        setAccounts(items);
      },
      (error: unknown) => {
        if (!cancelled) fail(error);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, fail, reloads]);

  const reload = () => setReloads((count) => count + 1);

  const act = async (
    id: string,
    run: () => Promise<WeChatAccount>,
    done: string,
  ) => {
    setBusy(id);
    setMessage(null);
    try {
      const account = await run();
      setMessage(
        account.last_verify_error !== null
          ? {
              kind: "error",
              text: `「${account.name}」${account.last_verify_error}`,
            }
          : { kind: "ok", text: `「${account.name}」${done}` },
      );
      reload();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">公众号账号</h2>
        <button
          type="button"
          className={styles.primary}
          disabled={binding || configured === false}
          onClick={() => {
            setMessage(null);
            setBinding(true);
          }}
        >
          绑定公众号
        </button>
      </header>
      <p className={styles.lede}>
        绑定后，就能在「发布」里发布这个公众号的草稿、在「数据」里看阅读数据。AppSecret
        加密保存，页面上只显示末 4 位；可以给每个号设主题，方便分开发不同内容。
      </p>
      {configured === false ? (
        <p className={styles.notice} role="status">
          服务器还没配置加密密钥（ADMIN_SECRET_KEY），暂时不能绑定公众号。请联系开发人员配置后再来。
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
      {!binding ? null : (
        <BindForm
          api={api}
          onCancel={() => setBinding(false)}
          onError={fail}
          onBound={(account) => {
            setBinding(false);
            setMessage({
              kind: "ok",
              text: `已绑定「${account.name}」，验证通过`,
            });
            reload();
          }}
        />
      )}
      {accounts === null ? (
        message?.kind === "error" ? null : (
          <p role="status">正在读取…</p>
        )
      ) : accounts.length === 0 ? (
        <p>还没有绑定公众号。</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">名称</th>
              <th scope="col">AppID</th>
              <th scope="col">AppSecret</th>
              <th scope="col">主题</th>
              <th scope="col">验证</th>
              <th scope="col">状态</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => (
              <tr key={account.id} data-enabled={account.enabled}>
                <td>{account.name}</td>
                <td>
                  <code>{account.app_id}</code>
                </td>
                <td>{account.secret_hint}</td>
                <td>
                  {account.topics.length === 0
                    ? "—"
                    : account.topics.join("、")}
                </td>
                <td>
                  {account.last_verify_error !== null
                    ? `失败：${account.last_verify_error}`
                    : account.last_verified_at === null
                      ? "未验证"
                      : `通过 ${formatTime(account.last_verified_at)}`}
                </td>
                <td>{account.enabled ? "使用中" : "已停用"}</td>
                <td>
                  {editing === account.id ? (
                    <EditForm
                      api={api}
                      account={account}
                      onError={fail}
                      onCancel={() => setEditing(null)}
                      onSaved={(saved) => {
                        setEditing(null);
                        setMessage({
                          kind: "ok",
                          text: `已保存「${saved.name}」`,
                        });
                        reload();
                      }}
                    />
                  ) : (
                    <span className={styles.rowActions}>
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => {
                          void act(
                            account.id,
                            () => api.verify(account.id),
                            "验证通过",
                          );
                        }}
                      >
                        {busy === account.id ? "验证中…" : "验证"}
                      </button>
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => {
                          setMessage(null);
                          setEditing(account.id);
                        }}
                      >
                        修改
                      </button>
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => {
                          void act(
                            account.id,
                            () =>
                              api.update(account.id, {
                                enabled: !account.enabled,
                              }),
                            account.enabled ? "已停用" : "已启用",
                          );
                        }}
                      >
                        {account.enabled ? "停用" : "启用"}
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function BindForm({
  api,
  onBound,
  onCancel,
  onError,
}: {
  readonly api: WeChatApi;
  readonly onBound: (account: WeChatAccount) => void;
  readonly onCancel: () => void;
  readonly onError: (error: unknown) => void;
}) {
  const [name, setName] = useState("");
  const [appId, setAppId] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [topics, setTopics] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    try {
      onBound(
        await api.bind({
          name: name.trim(),
          appId: appId.trim(),
          appSecret: appSecret.trim(),
          topics: splitTerms(topics),
        }),
      );
    } catch (error) {
      onError(error);
      setAppSecret("");
      setBusy(false);
    }
  };

  return (
    <form
      className={styles.editor}
      aria-label="绑定公众号"
      autoComplete="off"
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      <h3>绑定公众号</h3>
      <p className={styles.hint}>
        AppID 和 AppSecret 在公众号后台「设置与开发 →
        基本配置」里。注意：在那里「重置」AppSecret 会让正在用旧密钥的系统失效。
      </p>
      <div className={styles.formGrid}>
        <label className={styles.field}>
          <span>名称</span>
          <input
            value={name}
            required
            maxLength={40}
            placeholder="例如 赛先生科学"
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>AppID</span>
          <input
            value={appId}
            required
            spellCheck={false}
            placeholder="wx 开头"
            onChange={(event) => setAppId(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>AppSecret</span>
          <input
            type="password"
            value={appSecret}
            required
            autoComplete="new-password"
            spellCheck={false}
            onChange={(event) => setAppSecret(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>主题（可选，空格分隔，例如 科学 教育）</span>
          <input
            value={topics}
            onChange={(event) => setTopics(event.target.value)}
          />
        </label>
      </div>
      <div className={styles.actions}>
        <button type="submit" className={styles.primary} disabled={busy}>
          {busy ? "正在和微信验证…" : "验证并绑定"}
        </button>
        <button type="button" onClick={onCancel} disabled={busy}>
          取消
        </button>
      </div>
    </form>
  );
}

function EditForm({
  api,
  account,
  onSaved,
  onCancel,
  onError,
}: {
  readonly api: WeChatApi;
  readonly account: WeChatAccount;
  readonly onSaved: (account: WeChatAccount) => void;
  readonly onCancel: () => void;
  readonly onError: (error: unknown) => void;
}) {
  const [name, setName] = useState(account.name);
  const [topics, setTopics] = useState(account.topics.join(" "));
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      onSaved(
        await api.update(account.id, {
          ...(name.trim() !== account.name ? { name: name.trim() } : {}),
          topics: splitTerms(topics),
          ...(secret.trim() !== "" ? { appSecret: secret.trim() } : {}),
        }),
      );
    } catch (error) {
      onError(error);
      setSecret("");
      setBusy(false);
    }
  };

  return (
    <span
      className={styles.confirm}
      role="group"
      aria-label={`修改 ${account.name}`}
    >
      <input
        aria-label="名称"
        value={name}
        maxLength={40}
        onChange={(event) => setName(event.target.value)}
      />
      <input
        aria-label="主题"
        value={topics}
        placeholder="主题，空格分隔"
        onChange={(event) => setTopics(event.target.value)}
      />
      <input
        aria-label="新的 AppSecret（不换就留空）"
        type="password"
        autoComplete="new-password"
        value={secret}
        placeholder="新 AppSecret，不换留空"
        onChange={(event) => setSecret(event.target.value)}
      />
      <button
        type="button"
        className={styles.primary}
        disabled={busy || name.trim() === ""}
        onClick={() => {
          void save();
        }}
      >
        {busy ? "保存中…" : "保存"}
      </button>
      <button type="button" disabled={busy} onClick={onCancel}>
        取消
      </button>
    </span>
  );
}
