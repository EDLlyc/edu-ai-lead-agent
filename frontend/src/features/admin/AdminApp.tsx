import { useCallback, useEffect, useState } from "react";

import { AdminLoginPage } from "./AdminLoginPage";
import { adminApi, type AdminApi, type AdminMe } from "./api";
import { AccountsPage } from "./accounts/AccountsPage";
import { MyAccountPage } from "./accounts/MyAccountPage";
import {
  accountsApi as defaultAccountsApi,
  type AccountsApi,
} from "./accounts/api";
import { AuditLogPage } from "./AuditLogPage";
import { KeywordsPage } from "./keywords/KeywordsPage";
import {
  keywordsApi as defaultKeywordsApi,
  type KeywordsApi,
} from "./keywords/api";
import { SourcesPage } from "./sources/SourcesPage";
import { WeChatAccountsPage } from "./wechat/WeChatAccountsPage";
import { WeChatPublishPage } from "./wechat/WeChatPublishPage";
import { WeChatStatsPage } from "./wechat/WeChatStatsPage";
import { wechatApi as defaultWeChatApi, type WeChatApi } from "./wechat/api";
import {
  sourcesApi as defaultSourcesApi,
  type SourcesApi,
} from "./sources/api";
import styles from "./Admin.module.css";
import {
  sectionFromPath,
  visibleSections,
  type AdminSection,
  type AdminSectionKey,
} from "./sections";

type Session =
  | { readonly kind: "checking" }
  | { readonly kind: "unreachable"; readonly message: string }
  | { readonly kind: "anonymous"; readonly notice: string | null }
  | { readonly kind: "signed-in"; readonly me: AdminMe };

const ROLE_LABELS = { owner: "管理员", editor: "编辑" } as const;

/** The 运营后台 at /admin: login, the section menu, and one section at a time. */
export function AdminApp({
  api = adminApi,
  sourcesApi = defaultSourcesApi,
  keywordsApi = defaultKeywordsApi,
  accountsApi = defaultAccountsApi,
  wechatApi = defaultWeChatApi,
}: {
  readonly api?: AdminApi;
  readonly sourcesApi?: SourcesApi;
  readonly keywordsApi?: KeywordsApi;
  readonly accountsApi?: AccountsApi;
  readonly wechatApi?: WeChatApi;
}) {
  const [session, setSession] = useState<Session>({ kind: "checking" });
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    let cancelled = false;
    api.me().then(
      (me) => {
        if (cancelled) return;
        setSession(
          me === null
            ? { kind: "anonymous", notice: null }
            : { kind: "signed-in", me },
        );
      },
      (error: unknown) => {
        if (cancelled) return;
        setSession({
          kind: "unreachable",
          message: error instanceof Error ? error.message : "读取登录状态失败",
        });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api]);

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((key: AdminSectionKey) => {
    const next = `/admin/${key}`;
    window.history.pushState(null, "", next);
    setPath(next);
  }, []);

  const expire = useCallback(() => {
    setSession({ kind: "anonymous", notice: "登录已过期，请重新登录" });
  }, []);

  if (session.kind === "checking") {
    return (
      <p className={styles.center} role="status">
        正在检查登录状态…
      </p>
    );
  }
  if (session.kind === "unreachable") {
    return (
      <p className={`${styles.center} ${styles.error}`} role="alert">
        {session.message}
      </p>
    );
  }
  if (session.kind === "anonymous") {
    return (
      <AdminLoginPage
        api={api}
        notice={session.notice}
        onLoggedIn={(me) => setSession({ kind: "signed-in", me })}
      />
    );
  }

  const { me } = session;
  const sections = visibleSections(me.role);
  const requested = sectionFromPath(path);
  const current =
    sections.find((section) => section.key === requested) ?? sections[0];
  const forbidden = requested !== null && requested !== current?.key;

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <p className={styles.brand}>
          <strong>运营后台</strong>
          <span>赛先生 · AI 内容生产</span>
        </p>
        <div className={styles.account}>
          <span>
            {me.display_name}（{ROLE_LABELS[me.role]}）
          </span>
          <button
            type="button"
            onClick={() => {
              // Even if the API is unreachable, leave the page; the cookie expires anyway.
              void api
                .logout()
                .catch(() => undefined)
                .then(() => {
                  setSession({ kind: "anonymous", notice: "已退出" });
                });
            }}
          >
            退出
          </button>
        </div>
      </header>
      <nav className={styles.menu} aria-label="后台菜单">
        {groupSections(sections).map(([group, items]) => (
          <div className={styles.menuGroup} key={group}>
            <p>{group}</p>
            <ul>
              {items.map((section) => (
                <li key={section.key}>
                  <a
                    href={`/admin/${section.key}`}
                    aria-current={
                      section.key === current?.key ? "page" : undefined
                    }
                    onClick={(event) => {
                      if (
                        event.metaKey ||
                        event.ctrlKey ||
                        event.shiftKey ||
                        event.button !== 0
                      ) {
                        return;
                      }
                      event.preventDefault();
                      navigate(section.key);
                    }}
                  >
                    {section.title}
                    {section.plan === null ? null : <small>待上线</small>}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <main className={styles.content} id="admin-content">
        {forbidden ? (
          <p className={styles.notice} role="status">
            当前账号不能打开这个页面，已回到「{current?.title}」。
          </p>
        ) : null}
        {current === undefined ? null : current.key === "audit" ? (
          <AuditLogPage api={api} onSessionExpired={expire} />
        ) : current.key === "sources" ? (
          <SourcesPage api={sourcesApi} onSessionExpired={expire} />
        ) : current.key === "keywords" ? (
          <KeywordsPage api={keywordsApi} onSessionExpired={expire} />
        ) : current.key === "accounts" ? (
          <AccountsPage
            api={accountsApi}
            me={me.username}
            onSessionExpired={expire}
          />
        ) : current.key === "wechat-publish" ? (
          <WeChatPublishPage api={wechatApi} onSessionExpired={expire} />
        ) : current.key === "wechat-stats" ? (
          <WeChatStatsPage api={wechatApi} onSessionExpired={expire} />
        ) : current.key === "wechat-accounts" ? (
          <WeChatAccountsPage api={wechatApi} onSessionExpired={expire} />
        ) : current.key === "account" ? (
          <MyAccountPage api={api} me={me} onSessionExpired={expire} />
        ) : (
          <PlannedSection section={current} />
        )}
      </main>
    </div>
  );
}

function groupSections(
  sections: readonly AdminSection[],
): readonly (readonly [string, readonly AdminSection[]])[] {
  const groups = new Map<string, AdminSection[]>();
  for (const section of sections) {
    const items = groups.get(section.group) ?? [];
    items.push(section);
    groups.set(section.group, items);
  }
  return [...groups.entries()];
}

function PlannedSection({ section }: { readonly section: AdminSection }) {
  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">
          {section.group} · {section.title}
        </h2>
      </header>
      {section.plan === null ? null : (
        <div className={styles.planned}>
          <p className={styles.badge}>
            第 {section.plan.item} 项 · 计划 {section.plan.dates}
          </p>
          <p>{section.plan.summary}</p>
          <p className={styles.hint}>
            这一项还在开发，上线前这里不会改动任何线上设置。
          </p>
        </div>
      )}
    </section>
  );
}
