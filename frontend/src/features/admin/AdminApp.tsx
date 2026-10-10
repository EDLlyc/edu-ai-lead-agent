import { useCallback, useEffect, useState } from "react";

import { AdminLoginPage } from "./AdminLoginPage";
import { AdminNavigation } from "./AdminNavigation";
import { adminApi, type AdminApi, type AdminMe } from "./api";
import { AccountsPage } from "./accounts/AccountsPage";
import { MyAccountPage } from "./accounts/MyAccountPage";
import {
  accountsApi as defaultAccountsApi,
  type AccountsApi,
} from "./accounts/api";
import { AuditLogPage } from "./AuditLogPage";
import { KeywordsPage } from "./keywords/KeywordsPage";
import { LayoutTemplatesPage } from "./layout/LayoutTemplatesPage";
import { ModelsPage } from "./models/ModelsPage";
import { modelsApi as defaultModelsApi, type ModelsApi } from "./models/api";
import { layoutApi as defaultLayoutApi, type LayoutApi } from "./layout/api";
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
import { adminDataMode, ADMIN_ENVIRONMENT_LABELS } from "./environment";
import { UnsavedChangesProvider } from "./unsaved/UnsavedChanges";
import { useUnsavedNavigation } from "./unsaved/context";
import { useAdminHistory } from "./unsaved/useAdminHistory";
import {
  sectionFromPath,
  visibleSections,
  type AdminSection,
} from "./sections";

type Session =
  | { readonly kind: "checking" }
  | { readonly kind: "unreachable"; readonly message: string }
  | { readonly kind: "anonymous"; readonly notice: string | null }
  | { readonly kind: "signed-in"; readonly me: AdminMe };

const ROLE_LABELS = { owner: "管理员", editor: "编辑" } as const;

/** The 运营后台 at /admin: login, the section menu, and one section at a time. */
type AdminAppProps = {
  readonly api?: AdminApi;
  readonly sourcesApi?: SourcesApi;
  readonly keywordsApi?: KeywordsApi;
  readonly accountsApi?: AccountsApi;
  readonly wechatApi?: WeChatApi;
  readonly layoutApi?: LayoutApi;
  readonly modelsApi?: ModelsApi;
};

export function AdminApp(props: AdminAppProps) {
  const mode = adminDataMode(import.meta.env.VITE_ADMIN_DATA_MODE);
  return (
    <div className={styles.admin}>
      <UnsavedChangesProvider>
        <div
          className={styles.environmentBadge}
          data-mode={mode}
          aria-label="数据环境"
        >
          {ADMIN_ENVIRONMENT_LABELS[mode]}
        </div>
        <AdminSession {...props} />
      </UnsavedChangesProvider>
    </div>
  );
}

function AdminSession({
  api = adminApi,
  sourcesApi = defaultSourcesApi,
  keywordsApi = defaultKeywordsApi,
  accountsApi = defaultAccountsApi,
  wechatApi = defaultWeChatApi,
  layoutApi = defaultLayoutApi,
  modelsApi = defaultModelsApi,
}: AdminAppProps) {
  const [session, setSession] = useState<Session>({ kind: "checking" });
  const { path, navigate } = useAdminHistory();
  const { requestNavigation, clearAll } = useUnsavedNavigation();

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

  const expire = useCallback(() => {
    clearAll();
    setSession({ kind: "anonymous", notice: "登录已过期，请重新登录" });
  }, [clearAll]);

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
              requestNavigation(() => {
                // Even if the API is unreachable, leave the page; the cookie expires anyway.
                void api
                  .logout()
                  .catch(() => undefined)
                  .then(() => {
                    clearAll();
                    setSession({ kind: "anonymous", notice: "已退出" });
                  });
              });
            }}
          >
            退出
          </button>
        </div>
      </header>
      <AdminNavigation
        sections={sections}
        current={current}
        path={path}
        navigate={navigate}
      />
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
          <WeChatPublishPage
            api={wechatApi}
            onSessionExpired={expire}
            canReconcile={me.role === "owner"}
          />
        ) : current.key === "wechat-stats" ? (
          <WeChatStatsPage api={wechatApi} onSessionExpired={expire} />
        ) : current.key === "wechat-accounts" ? (
          <WeChatAccountsPage api={wechatApi} onSessionExpired={expire} />
        ) : current.key === "layout-templates" ? (
          <LayoutTemplatesPage api={layoutApi} onSessionExpired={expire} />
        ) : current.key === "models" ? (
          <ModelsPage api={modelsApi} onSessionExpired={expire} />
        ) : current.key === "account" ? (
          <MyAccountPage api={api} me={me} onSessionExpired={expire} />
        ) : (
          <PlannedSection section={current} />
        )}
      </main>
    </div>
  );
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
