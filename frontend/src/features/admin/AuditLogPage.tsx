import { useEffect, useState } from "react";

import {
  AUDIT_PAGE_SIZE,
  AdminSessionExpiredError,
  type AdminApi,
  type AdminAuditEvent,
  type AuditKind,
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
  "user.updated": "修改账号",
  "user.password_changed": "修改自己的密码",
  "user.password_change_failed": "改密码时当前密码不对",
  "source.previewed": "预览新闻源",
  "source.created": "新增新闻源",
  "source.updated": "修改新闻源",
  "source.enabled": "打开新闻源",
  "source.disabled": "关闭新闻源",
  "source.archived": "删除新闻源",
  "keywords.saved": "保存关键词",
};

const LIST_LABELS: Readonly<Record<string, string>> = {
  focus: "关注词",
  block: "屏蔽词",
  copy_banned: "文案禁用词",
};

const FIELD_LABELS: Readonly<Record<string, string>> = {
  display_name: "名称",
  organization_type: "机构类型",
  entry_url: "网址",
  tier: "可信度",
  connector_config: "抓取设置",
  fetch_settings: "抓取设置",
};

const ROLE_NAMES: Readonly<Record<string, string>> = {
  owner: "管理员",
  editor: "编辑",
};

const KINDS: readonly {
  readonly kind: AuditKind | null;
  readonly label: string;
}[] = [
  { kind: null, label: "全部" },
  { kind: "auth", label: "登录" },
  { kind: "user", label: "账号" },
  { kind: "source", label: "新闻源" },
  { kind: "keywords", label: "关键词" },
];

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
  if (typeof detail.display_name === "string") {
    parts.push(`「${detail.display_name}」`);
  } else if (typeof detail.entry_url === "string") {
    parts.push(detail.entry_url);
  } else if (event.target_id !== null) {
    parts.push(`对象：${event.target_id}`);
  }
  if (Array.isArray(detail.changed)) {
    const fields = detail.changed
      .map((field) => FIELD_LABELS[String(field)] ?? String(field))
      .filter((field, index, all) => all.indexOf(field) === index);
    parts.push(`改了：${fields.join("、")}`);
  }
  if (typeof detail.version === "number") parts.push(`第 ${detail.version} 版`);
  if (
    event.action === "user.updated" &&
    detail.changes !== null &&
    typeof detail.changes === "object"
  ) {
    const changes = detail.changes as Record<
      string,
      { from?: unknown; to?: unknown }
    >;
    if (changes.display_name !== undefined) {
      parts.push(
        `显示名：${String(changes.display_name.from)} → ${String(changes.display_name.to)}`,
      );
    }
    if (changes.role !== undefined) {
      const from = String(changes.role.from);
      const to = String(changes.role.to);
      parts.push(`角色：${ROLE_NAMES[from] ?? from} → ${ROLE_NAMES[to] ?? to}`);
    }
  } else if (detail.changes !== null && typeof detail.changes === "object") {
    for (const [list, change] of Object.entries(
      detail.changes as Record<string, { added?: unknown; removed?: unknown }>,
    )) {
      const label = LIST_LABELS[list] ?? list;
      const added = Array.isArray(change.added) ? change.added.map(String) : [];
      const removed = Array.isArray(change.removed)
        ? change.removed.map(String)
        : [];
      if (added.length > 0) parts.push(`${label}加：${added.join("、")}`);
      if (removed.length > 0) parts.push(`${label}减：${removed.join("、")}`);
    }
  }
  if (typeof detail.note === "string" && detail.note !== "") {
    parts.push(`备注：${detail.note}`);
  }
  if (typeof detail.ok === "boolean") {
    parts.push(detail.ok ? "能抓到文章" : "抓不到文章");
  }
  if (typeof detail.sessions_ended === "number" && detail.sessions_ended > 0) {
    parts.push(`结束 ${detail.sessions_ended} 个在线会话`);
  }
  if (typeof detail.role === "string") {
    parts.push(`角色：${ROLE_NAMES[detail.role] ?? detail.role}`);
  }
  if (detail.locked === true) parts.push("连续输错，已锁定 15 分钟");
  return parts.join("；");
}

type State =
  | { readonly kind: "loading" }
  | { readonly kind: "error"; readonly message: string }
  | {
      readonly kind: "ready";
      readonly events: readonly AdminAuditEvent[];
      readonly more: boolean;
    };

export function AuditLogPage({
  api,
  onSessionExpired,
}: {
  readonly api: AdminApi;
  readonly onSessionExpired: () => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [filter, setFilter] = useState<AuditKind | null>(null);
  const [reloads, setReloads] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

  const handle = (error: unknown) => {
    if (error instanceof AdminSessionExpiredError) {
      onSessionExpired();
      return;
    }
    setState({
      kind: "error",
      message: error instanceof Error ? error.message : "读取失败",
    });
  };

  useEffect(() => {
    let cancelled = false;
    api.auditEvents(filter === null ? {} : { kind: filter }).then(
      (events) => {
        if (!cancelled) {
          setState({
            kind: "ready",
            events,
            more: events.length === AUDIT_PAGE_SIZE,
          });
        }
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
  }, [api, onSessionExpired, filter, reloads]);

  const loadMore = async () => {
    if (state.kind !== "ready" || state.events.length === 0) return;
    setLoadingMore(true);
    try {
      const oldest = state.events[state.events.length - 1]!;
      const older = await api.auditEvents({
        ...(filter === null ? {} : { kind: filter }),
        before: oldest.occurred_at,
      });
      setState({
        kind: "ready",
        events: [...state.events, ...older],
        more: older.length === AUDIT_PAGE_SIZE,
      });
    } catch (error) {
      handle(error);
    } finally {
      setLoadingMore(false);
    }
  };

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
        谁在什么时候登录、改了什么。密码和密钥不会出现在这里。
      </p>
      <div className={styles.filters} role="group" aria-label="按类型筛选">
        {KINDS.map((item) => (
          <button
            key={item.label}
            type="button"
            aria-pressed={filter === item.kind}
            onClick={() => {
              if (filter === item.kind) return;
              setState({ kind: "loading" });
              setFilter(item.kind);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      {state.kind === "loading" ? (
        <p role="status">正在读取…</p>
      ) : state.kind === "error" ? (
        <p className={styles.error} role="alert">
          {state.message}
        </p>
      ) : state.events.length === 0 ? (
        <p>还没有记录。</p>
      ) : (
        <>
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
          {state.more ? (
            <button
              type="button"
              className={styles.more}
              disabled={loadingMore}
              onClick={() => {
                void loadMore();
              }}
            >
              {loadingMore ? "正在加载…" : "加载更早的记录"}
            </button>
          ) : (
            <p className={styles.hint}>没有更早的记录了。</p>
          )}
        </>
      )}
    </section>
  );
}
