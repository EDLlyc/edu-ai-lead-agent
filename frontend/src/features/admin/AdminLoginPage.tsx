import { useState, type FormEvent } from "react";

import { ExhibitEntryLink } from "./ExhibitEntryLink";
import styles from "./Admin.module.css";

export function AdminLoginPage({
  notice,
  onLogin,
  sessionCheckFailed,
  onRetrySessionCheck,
}: {
  readonly notice: string | null;
  readonly onLogin: (username: string, password: string) => Promise<void>;
  readonly sessionCheckFailed: boolean;
  readonly onRetrySessionCheck: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onLogin(username.trim(), password);
    } catch (failure) {
      setPassword("");
      setError(failure instanceof Error ? failure.message : "登录失败");
      setBusy(false);
    }
  };

  return (
    <section className={styles.login} aria-labelledby="admin-login-title">
      <form
        className={styles.loginCard}
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <p className={styles.eyebrow}>赛先生 · 运营后台</p>
        <h1 id="admin-login-title">登录</h1>
        {notice === null ? null : (
          <p className={styles.notice} role="status">
            {notice}
          </p>
        )}
        {sessionCheckFailed ? (
          <div className={styles.notice} role="alert">
            <p>登录状态检查失败，当前登录状态未确认。保留已填写内容。</p>
            <button type="button" disabled={busy} onClick={onRetrySessionCheck}>
              重新检查登录状态
            </button>
          </div>
        ) : null}
        <label className={styles.field}>
          <span>用户名</span>
          <input
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>密码</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error === null ? null : (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        <button className={styles.primary} type="submit" disabled={busy}>
          {busy ? "正在登录…" : "登录"}
        </button>
        <p className={styles.hint}>账号由管理员在服务器上开通。</p>
        <ExhibitEntryLink />
      </form>
    </section>
  );
}
