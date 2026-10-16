import { AdminLoginPage } from "./AdminLoginPage";
import { AdminNavigation } from "./AdminNavigation";
import { adminApi, type AdminApi } from "./api";
import { ExhibitEntryLink } from "./ExhibitEntryLink";
import { useAdminSession } from "./useAdminSession";
import { AccountsPage } from "./accounts/AccountsPage";
import { MyAccountPage } from "./accounts/MyAccountPage";
import {
  accountsApi as defaultAccountsApi,
  type AccountsApi,
} from "./accounts/api";
import { AuditLogPage } from "./AuditLogPage";
import { KeywordsPage } from "./keywords/KeywordsPage";
import {
  newsReviewsApi as defaultNewsReviewsApi,
  type NewsReviewsApi,
} from "./newsreviews/api";
import { NewsReviewPage } from "./newsreviews/NewsReviewPage";
import { LayoutTemplatesPage } from "./layout/LayoutTemplatesPage";
import { ModelsPage } from "./models/ModelsPage";
import { modelsApi as defaultModelsApi, type ModelsApi } from "./models/api";
import { layoutApi as defaultLayoutApi, type LayoutApi } from "./layout/api";
import {
  keywordsApi as defaultKeywordsApi,
  type KeywordsApi,
} from "./keywords/api";
import {
  builtinPhrasesApi as defaultBuiltinPhrasesApi,
  type BuiltinPhrasesApi,
} from "./keywords/builtinApi";
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

const ROLE_LABELS = { owner: "管理员", editor: "编辑" } as const;

/** The 运营后台 at /admin: login, the section menu, and one section at a time. */
type AdminAppProps = {
  readonly api?: AdminApi;
  readonly sourcesApi?: SourcesApi;
  readonly keywordsApi?: KeywordsApi;
  readonly builtinPhrasesApi?: BuiltinPhrasesApi;
  readonly newsReviewsApi?: NewsReviewsApi;
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
  builtinPhrasesApi = defaultBuiltinPhrasesApi,
  newsReviewsApi = defaultNewsReviewsApi,
  accountsApi = defaultAccountsApi,
  wechatApi = defaultWeChatApi,
  layoutApi = defaultLayoutApi,
  modelsApi = defaultModelsApi,
}: AdminAppProps) {
  const { session, check, login, logout, expire } = useAdminSession(api);
  const { path, navigate } = useAdminHistory();
  const { requestNavigation } = useUnsavedNavigation();

  if (session.kind === "checking") {
    return (
      <p className={styles.center} role="status">
        正在检查登录状态…
      </p>
    );
  }
  if (session.kind === "unreachable") {
    return (
      <div className={styles.center}>
        <p className={styles.error} role="alert">
          连不上后台服务，当前登录状态未确认，请重试。
        </p>
        <button type="button" className={styles.primary} onClick={check}>
          重新检查登录状态
        </button>
        <ExhibitEntryLink />
      </div>
    );
  }
  if (session.kind === "anonymous") {
    return (
      <AdminLoginPage
        notice={session.notice}
        onLogin={login}
        sessionCheckFailed={session.status === "check-failed"}
        onRetrySessionCheck={check}
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
    <div className={styles.shell} key={`${me.username}:${me.role}`}>
      <header className={styles.topbar}>
        <p className={styles.brand}>
          <strong>运营后台</strong>
          <span>赛先生 · AI 内容生产</span>
        </p>
        <div className={styles.account}>
          <ExhibitEntryLink />
          <span>
            {me.display_name}（{ROLE_LABELS[me.role]}）
          </span>
          <button
            type="button"
            disabled={session.status === "logging-out"}
            onClick={() => {
              requestNavigation(() => {
                void logout();
              });
            }}
          >
            {session.status === "logging-out" ? "正在退出…" : "退出"}
          </button>
        </div>
        {session.status === "rechecking" ? (
          <p className={styles.sessionNotice} role="status">
            正在重新检查登录状态…
          </p>
        ) : session.status === "check-failed" ? (
          <div
            className={`${styles.sessionNotice} ${styles.notice}`}
            role="alert"
          >
            <span>
              登录状态检查失败，当前登录状态未确认。保留上次账号和未保存内容。
            </span>
            <button type="button" onClick={check}>
              重新检查登录状态
            </button>
          </div>
        ) : session.status === "logout-failed" ? (
          <p className={`${styles.sessionNotice} ${styles.error}`} role="alert">
            退出未确认，服务器会话可能仍有效。请再次点击「退出」重试。
          </p>
        ) : null}
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
          <KeywordsPage
            api={keywordsApi}
            builtinApi={builtinPhrasesApi}
            onSessionExpired={expire}
          />
        ) : current.key === "news-review" ? (
          <NewsReviewPage api={newsReviewsApi} onSessionExpired={expire} />
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
