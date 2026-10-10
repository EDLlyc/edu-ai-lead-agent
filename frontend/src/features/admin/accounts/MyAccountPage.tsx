import { useState, type FormEvent } from "react";

import styles from "../Admin.module.css";
import { useUnsavedChanges } from "../unsaved/context";
import { AdminSessionExpiredError, type AdminApi, type AdminMe } from "../api";
import { formatTime } from "../sources/labels";

const ROLE_LABELS = { owner: "管理员", editor: "编辑" } as const;

/** 运营后台 · 我的账号: who I am and changing my own password. */
export function MyAccountPage({
  api,
  me,
  onSessionExpired,
}: {
  readonly api: AdminApi;
  readonly me: AdminMe;
  readonly onSessionExpired: () => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{
    readonly kind: "ok" | "error";
    readonly text: string;
  } | null>(null);

  useUnsavedChanges(current !== "" || next !== "" || again !== "", () => {
    setCurrent("");
    setNext("");
    setAgain("");
  });

  const mismatch = again !== "" && next !== again;
  const tooShort = next !== "" && next.length < 10;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (mismatch || tooShort) return;
    setBusy(true);
    setMessage(null);
    try {
      const ended = await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setAgain("");
      setMessage({
        kind: "ok",
        text:
          ended > 0
            ? `密码已修改，其他 ${ended} 处登录已退出`
            : "密码已修改，下次登录用新密码",
      });
    } catch (error) {
      if (error instanceof AdminSessionExpiredError) {
        onSessionExpired();
        return;
      }
      setMessage({
        kind: "error",
        text: error instanceof Error ? error.message : "修改失败",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">我的账号</h2>
      </header>
      <dl className={styles.facts}>
        <dt>用户名</dt>
        <dd>{me.username}</dd>
        <dt>显示名</dt>
        <dd>{me.display_name}</dd>
        <dt>角色</dt>
        <dd>{ROLE_LABELS[me.role]}</dd>
        <dt>本次登录有效到</dt>
        <dd>{formatTime(me.expires_at)}</dd>
      </dl>
      <form
        className={styles.editor}
        aria-label="修改密码"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <h3>修改密码</h3>
        <input
          disabled={busy}
          type="text"
          name="username"
          autoComplete="username"
          value={me.username}
          readOnly
          hidden
        />
        <div className={styles.formGrid}>
          <label className={styles.field}>
            <span>当前密码</span>
            <input
              disabled={busy}
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          </label>
          <label className={styles.field}>
            <span>新密码（至少 10 位）</span>
            <input
              disabled={busy}
              type="password"
              autoComplete="new-password"
              required
              minLength={10}
              maxLength={128}
              value={next}
              onChange={(event) => setNext(event.target.value)}
            />
          </label>
          <label className={styles.field}>
            <span>再输一次新密码</span>
            <input
              disabled={busy}
              type="password"
              autoComplete="new-password"
              required
              value={again}
              onChange={(event) => setAgain(event.target.value)}
            />
          </label>
        </div>
        {tooShort ? <p className={styles.hint}>新密码至少 10 位。</p> : null}
        {mismatch ? (
          <p className={styles.error}>两次输入的新密码不一样。</p>
        ) : null}
        {message === null ? null : (
          <p
            className={message.kind === "error" ? styles.error : styles.success}
            role={message.kind === "error" ? "alert" : "status"}
          >
            {message.text}
          </p>
        )}
        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.primary}
            disabled={
              busy || mismatch || tooShort || current === "" || again === ""
            }
          >
            {busy ? "正在修改…" : "修改密码"}
          </button>
        </div>
        <p className={styles.hint}>
          改完后，你在其他电脑或浏览器上的登录会自动退出，这里保持登录。
        </p>
      </form>
    </section>
  );
}
