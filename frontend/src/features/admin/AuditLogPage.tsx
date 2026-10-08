import { useEffect, useState } from "react";

import {
  AdminSessionExpiredError,
  type AdminApi,
  type AdminAuditEvent,
} from "./api";
import styles from "./Admin.module.css";

const ACTION_LABELS: Readonly<Record<string, string>> = {
  "auth.login": "登录",
  "auth.login_failed": "登录失败",
  "auth.logout": "退出",
  "user.created": "新建账号",
  "user.password_set": "重设密码",
  "user.disabled": "停用账号",
  "user.enabled": "启用账号",
};

const REASON_LABELS: Readonly<Record<string, string>> = {
  wrong_password: "密码不对",
  wrong_password_locked: "密码不对，已连续 5 次，锁定 15 分钟",
  locked: "账号锁定中",
  unknown_user: "没有这个账号",
  disabled: "账号已停用",
};

const timeFormat = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function describe(event: AdminAuditEvent): string {
  const detail = event.detail;
  const parts: string[] = [];
  if (typeof detail.reason === "string") {
    parts.push(REASON_LABELS[detail.reason] ?? detail.reason);
  }
  if (event.target_id !== null) parts.push(`对象：${event.target_id}`);
  if (typeof detail.sessions_ended === "number" && detail.sessions_ended > 0) {
    parts.push(`结束 ${detail.sessions_ended} 个在线会话`);
  }
  if (typeof detail.role === "string") parts.push(`角色：${detail.role}`);
  return parts.join("；");
}

type State =
  | { readonly kind: "loading" }
  | { readonly kind: "error"; readonly message: string }
  | { readonly kind: "ready"; readonly events: readonly AdminAuditEvent[] };

export function AuditLogPage({
  api,
  onSessionExpired,
}: {
  readonly api: AdminApi;
  readonly onSessionExpired: () => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.auditEvents().then(
      (events) => {
        if (!cancelled) setState({ kind: "ready", events });
      },
      (error: unknown) => {
        if (cancelled) return;
        if (error instanceof AdminSessionExpiredError) {
          onSessionExpired();
          return;
        }
        setState({
          kind: "error",
          message: error instanceof Error ? error.message : "读取失败",
        });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, onSessionExpired, reloads]);

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">操作记录</h2>
        <button
          type="button"
          onClick={() => {
            setState({ kind: "loading" });
            setReloads((count) => count + 1);
          }}
          disabled={state.kind === "loading"}
        >
          刷新
        </button>
      </header>
      <p className={styles.lede}>
        最近 100 条：谁在什么时候登录、改了什么。密码和密钥不会出现在这里。
      </p>
      {state.kind === "loading" ? (
        <p role="status">正在读取…</p>
      ) : state.kind === "error" ? (
        <p className={styles.error} role="alert">
          {state.message}
        </p>
      ) : state.events.length === 0 ? (
        <p>还没有记录。</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">时间</th>
              <th scope="col">账号</th>
              <th scope="col">操作</th>
              <th scope="col">说明</th>
            </tr>
          </thead>
          <tbody>
            {state.events.map((event) => (
              <tr key={event.id} data-action={event.action}>
                <td>{timeFormat.format(new Date(event.occurred_at))}</td>
                <td>{event.username}</td>
                <td>{ACTION_LABELS[event.action] ?? event.action}</td>
                <td>{describe(event)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
