import { useCallback, useEffect, useState, type FormEvent } from "react";

import styles from "../Admin.module.css";
import { AdminSessionExpiredError } from "../api";
import { formatTime } from "../sources/labels";
import {
  accountsApi as defaultApi,
  type AccountRole,
  type AccountsApi,
  type AccountWithPassword,
  type AdminAccount,
} from "./api";

const ROLE_LABELS: Readonly<Record<AccountRole, string>> = {
  owner: "管理员",
  editor: "编辑",
};

type Pending = {
  readonly username: string;
  readonly action: "reset" | "disable" | "enable";
} | null;

const CONFIRM_TEXT = {
  reset: "确认重设密码？旧密码立即失效，这个账号的登录全部退出。",
  disable: "确认停用？这个账号会立即退出，不能再登录，操作记录保留。",
  enable: "确认启用？",
} as const;

/** 运营后台 · 账号管理 (owner only). */
export function AccountsPage({
  api = defaultApi,
  me,
  onSessionExpired,
}: {
  readonly api?: AccountsApi;
  readonly me: string;
  readonly onSessionExpired: () => void;
}) {
  const [accounts, setAccounts] = useState<readonly AdminAccount[] | null>(
    null,
  );
  const [reloads, setReloads] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [issued, setIssued] = useState<
    (AccountWithPassword & { readonly reason: "created" | "reset" }) | null
  >(null);
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
        text: error instanceof Error ? error.message : "操作失败",
      });
    },
    [onSessionExpired],
  );

  useEffect(() => {
    let cancelled = false;
    api.list().then(
      (items) => {
        if (!cancelled) setAccounts(items);
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

  const run = async (action: NonNullable<Pending>) => {
    setBusy(true);
    setMessage(null);
    try {
      if (action.action === "reset") {
        setIssued({
          ...(await api.resetPassword(action.username)),
          reason: "reset",
        });
      } else {
        const updated = await api.setActive(
          action.username,
          action.action === "enable",
        );
        setMessage({
          kind: "ok",
          text: `已${updated.active ? "启用" : "停用"}「${updated.display_name}」`,
        });
      }
      setPending(null);
      reload();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">账号管理</h2>
        <button
          type="button"
          className={styles.primary}
          disabled={creating}
          onClick={() => {
            setMessage(null);
            setIssued(null);
            setCreating(true);
          }}
        >
          新建账号
        </button>
      </header>
      <p className={styles.lede}>
        管理员什么都能改；编辑能管新闻源和关键词，看不到操作记录和账号。新建或重设时系统生成初始密码，只显示这一次。
      </p>
      {message === null ? null : (
        <p
          className={message.kind === "error" ? styles.error : styles.success}
          role={message.kind === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}
      {issued === null ? null : (
        <IssuedPassword issued={issued} onDone={() => setIssued(null)} />
      )}
      {!creating ? null : (
        <CreateAccountForm
          api={api}
          onCancel={() => setCreating(false)}
          onError={fail}
          onCreated={(created) => {
            setCreating(false);
            setIssued({ ...created, reason: "created" });
            reload();
          }}
        />
      )}
      {accounts === null ? (
        message?.kind === "error" ? null : (
          <p role="status">正在读取…</p>
        )
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">用户名</th>
              <th scope="col">显示名</th>
              <th scope="col">角色</th>
              <th scope="col">状态</th>
              <th scope="col">最近登录</th>
              <th scope="col">在线</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => {
              const self = account.username === me;
              return (
                <tr key={account.username} data-enabled={account.active}>
                  <td>
                    {account.username}
                    {self ? "（我）" : ""}
                  </td>
                  <td>{account.display_name}</td>
                  <td>{ROLE_LABELS[account.role]}</td>
                  <td>
                    {!account.active
                      ? "停用"
                      : account.locked
                        ? "锁定中"
                        : "正常"}
                  </td>
                  <td>
                    {account.last_login_at === null
                      ? "从未登录"
                      : formatTime(account.last_login_at)}
                  </td>
                  <td>{account.live_sessions}</td>
                  <td>
                    {editing === account.username ? (
                      <EditAccountForm
                        api={api}
                        account={account}
                        self={self}
                        onError={fail}
                        onCancel={() => setEditing(null)}
                        onSaved={(saved) => {
                          setEditing(null);
                          setMessage({
                            kind: "ok",
                            text: `已保存「${saved.display_name}」`,
                          });
                          reload();
                        }}
                      />
                    ) : pending?.username === account.username ? (
                      <span
                        className={styles.confirm}
                        role="group"
                        aria-label="确认操作"
                      >
                        {CONFIRM_TEXT[pending.action]}
                        <button
                          type="button"
                          className={styles.primary}
                          disabled={busy}
                          onClick={() => {
                            void run(pending);
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
                    ) : (
                      <span className={styles.rowActions}>
                        <button
                          type="button"
                          onClick={() => {
                            setMessage(null);
                            setEditing(account.username);
                          }}
                        >
                          修改
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setPending({
                              username: account.username,
                              action: "reset",
                            })
                          }
                        >
                          重设密码
                        </button>
                        {self ? null : (
                          <button
                            type="button"
                            onClick={() =>
                              setPending({
                                username: account.username,
                                action: account.active ? "disable" : "enable",
                              })
                            }
                          >
                            {account.active ? "停用" : "启用"}
                          </button>
                        )}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function IssuedPassword({
  issued,
  onDone,
}: {
  readonly issued: AccountWithPassword & {
    readonly reason: "created" | "reset";
  };
  readonly onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className={styles.issued} role="alertdialog" aria-label="初始密码">
      <p>
        <strong>
          {issued.reason === "created" ? "已新建" : "已重设"}「
          {issued.account.display_name}」（
          {issued.account.username}）的密码：
        </strong>
      </p>
      <p className={styles.password}>
        <code>{issued.initialPassword}</code>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(issued.initialPassword).then(
              () => setCopied(true),
              () => setCopied(false),
            );
          }}
        >
          {copied ? "已复制" : "复制"}
        </button>
      </p>
      <p className={styles.hint}>
        这个密码只显示这一次，请转交本人，并提醒对方登录后在「我的账号」里改成自己的密码。
      </p>
      <button type="button" className={styles.primary} onClick={onDone}>
        我已记下
      </button>
    </div>
  );
}

function CreateAccountForm({
  api,
  onCreated,
  onCancel,
  onError,
}: {
  readonly api: AccountsApi;
  readonly onCreated: (created: AccountWithPassword) => void;
  readonly onCancel: () => void;
  readonly onError: (error: unknown) => void;
}) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<AccountRole>("editor");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    try {
      onCreated(
        await api.create({
          username: username.trim(),
          displayName: displayName.trim(),
          role,
        }),
      );
    } catch (error) {
      onError(error);
      setBusy(false);
    }
  };

  return (
    <form
      className={styles.editor}
      aria-label="新建账号"
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      <h3>新建账号</h3>
      <div className={styles.formGrid}>
        <label className={styles.field}>
          <span>用户名（登录用，小写字母开头，可含数字 _ . -）</span>
          <input
            value={username}
            required
            maxLength={40}
            autoCapitalize="none"
            spellCheck={false}
            placeholder="例如 wang"
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>显示名</span>
          <input
            value={displayName}
            required
            maxLength={40}
            placeholder="例如 王老师"
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>角色</span>
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as AccountRole)}
          >
            <option value="editor">编辑（管新闻源、关键词）</option>
            <option value="owner">管理员（全部权限）</option>
          </select>
        </label>
      </div>
      <div className={styles.actions}>
        <button type="submit" className={styles.primary} disabled={busy}>
          {busy ? "正在新建…" : "新建并生成密码"}
        </button>
        <button type="button" onClick={onCancel} disabled={busy}>
          取消
        </button>
      </div>
    </form>
  );
}

function EditAccountForm({
  api,
  account,
  self,
  onSaved,
  onCancel,
  onError,
}: {
  readonly api: AccountsApi;
  readonly account: AdminAccount;
  readonly self: boolean;
  readonly onSaved: (saved: AdminAccount) => void;
  readonly onCancel: () => void;
  readonly onError: (error: unknown) => void;
}) {
  const [displayName, setDisplayName] = useState(account.display_name);
  const [role, setRole] = useState<AccountRole>(account.role);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      onSaved(
        await api.update(account.username, {
          ...(displayName.trim() !== account.display_name
            ? { displayName: displayName.trim() }
            : {}),
          ...(role !== account.role ? { role } : {}),
        }),
      );
    } catch (error) {
      onError(error);
      setBusy(false);
    }
  };

  return (
    <span
      className={styles.confirm}
      role="group"
      aria-label={`修改 ${account.username}`}
    >
      <input
        aria-label="显示名"
        value={displayName}
        maxLength={40}
        onChange={(event) => setDisplayName(event.target.value)}
      />
      <select
        aria-label="角色"
        value={role}
        disabled={self}
        title={self ? "不能修改自己的角色" : undefined}
        onChange={(event) => setRole(event.target.value as AccountRole)}
      >
        <option value="editor">编辑</option>
        <option value="owner">管理员</option>
      </select>
      <button
        type="button"
        className={styles.primary}
        disabled={busy || displayName.trim() === ""}
        onClick={() => {
          void save();
        }}
      >
        保存
      </button>
      <button type="button" disabled={busy} onClick={onCancel}>
        取消
      </button>
    </span>
  );
}
