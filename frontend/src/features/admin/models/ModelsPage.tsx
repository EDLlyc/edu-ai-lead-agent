import { useCallback, useEffect, useState, type FormEvent } from "react";

import styles from "../Admin.module.css";
import { AdminSessionExpiredError } from "../api";
import { formatTime } from "../sources/labels";
import {
  modelsApi as defaultApi,
  type ModelKeyConsumer,
  type ModelKeyTest,
  type ModelKeyVersion,
  type ModelProvider,
  type ModelsApi,
} from "./api";

/** While a saved key waits for the services to restart, look again this often. */
const PENDING_POLL_MS = 30_000;

type Message = { readonly kind: "ok" | "error"; readonly text: string };

function sourceText(provider: ModelProvider): string {
  if (provider.source === "console")
    return `后台保存的第 ${provider.version} 版`;
  if (provider.source === "env") return "服务器配置的 key";
  return "未配置";
}

/** The version a service loaded for this provider; null = its environment key. */
function loadedVersion(
  consumer: ModelKeyConsumer,
  providerId: string,
): number | null {
  return consumer.versions?.[providerId] ?? null;
}

function loadState(
  consumer: ModelKeyConsumer,
  provider: ModelProvider,
): "loaded" | "waiting" | "failed" | "unknown" {
  if (!consumer.reporting || consumer.load_errors == null) return "unknown";
  if (consumer.load_errors[provider.id] !== undefined) return "failed";
  if (consumer.versions === null) return "unknown";
  return loadedVersion(consumer, provider.id) === provider.version
    ? "loaded"
    : "waiting";
}

function waitingServices(
  provider: ModelProvider,
  consumers: readonly ModelKeyConsumer[],
): readonly ModelKeyConsumer[] {
  return consumers.filter(
    (consumer) =>
      consumer.reporting && loadState(consumer, provider) === "waiting",
  );
}

function effectText(
  provider: ModelProvider,
  consumers: readonly ModelKeyConsumer[],
): string {
  if (provider.source === "none") return "—";
  const reporting = consumers.filter((consumer) => consumer.reporting);
  const waiting = waitingServices(provider, consumers).length;
  const loaded = reporting.filter(
    (consumer) => loadState(consumer, provider) === "loaded",
  ).length;
  const failed = reporting.filter(
    (consumer) => loadState(consumer, provider) === "failed",
  ).length;
  const unknown = reporting.length - loaded - waiting - failed;
  const absent = consumers.length - reporting.length;
  const parts = [
    reporting.length === 0
      ? "尚未收到服务加载状态"
      : provider.version === null && loaded === reporting.length
        ? "使用中"
        : `已在 ${loaded}/${reporting.length} 个服务生效`,
  ];
  if (waiting > 0) parts.push(`${waiting} 个等待重启（约 2 分钟）`);
  if (failed > 0) parts.push(`${failed} 个加载失败，保留服务器配置`);
  if (unknown > 0) parts.push(`${unknown} 个未报告加载状态，尚无法确认`);
  if (absent > 0) parts.push(`${absent} 个服务未接入，仍用服务器配置的 key`);
  return parts.join("；");
}

/** 运营后台 · 系统 · 模型配置 (owner only): rotate model keys, tested first. */
export function ModelsPage({
  api = defaultApi,
  onSessionExpired,
}: {
  readonly api?: ModelsApi;
  readonly onSessionExpired: () => void;
}) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [providers, setProviders] = useState<readonly ModelProvider[] | null>(
    null,
  );
  const [consumers, setConsumers] = useState<readonly ModelKeyConsumer[]>([]);
  const [reloads, setReloads] = useState(0);
  const [message, setMessage] = useState<Message | null>(null);

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
      (loaded) => {
        if (cancelled) return;
        setConfigured(loaded.secretKeyConfigured);
        setProviders(loaded.providers);
        setConsumers(loaded.consumers);
      },
      (error: unknown) => {
        if (!cancelled) fail(error);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, fail, reloads]);

  // The services restart about two minutes after a change; refresh until they report it.
  const waiting =
    providers?.some(
      (provider) => waitingServices(provider, consumers).length > 0,
    ) ?? false;
  const absent = consumers.filter((consumer) => !consumer.reporting);
  useEffect(() => {
    if (!waiting) return;
    const timer = window.setInterval(() => {
      setReloads((count) => count + 1);
    }, PENDING_POLL_MS);
    return () => window.clearInterval(timer);
  }, [waiting]);

  const changed = (saved: ModelProvider, text: string) => {
    setProviders(
      (items) =>
        items?.map((item) => (item.id === saved.id ? saved : item)) ?? null,
    );
    setMessage({ kind: "ok", text });
  };

  return (
    <section aria-labelledby="admin-section-title">
      <header className={styles.sectionHeader}>
        <h2 id="admin-section-title">模型配置</h2>
        <button type="button" onClick={() => setReloads((count) => count + 1)}>
          刷新状态
        </button>
      </header>
      <p className={styles.lede}>
        这里只换 API
        key。接口地址和模型名固定在代码里（文案、审核和图片向量都依赖它们），要换需要发版。换
        key 前会先用新 key
        发一个很小的请求，通过才保存；保存后，相关服务做完手头的任务会自动重启，大约
        2
        分钟开始加载。是否已生效以各服务的加载状态为准；加载失败时保留服务器配置。
      </p>
      {configured === false ? (
        <p className={styles.notice} role="status">
          服务器还没配置加密密钥（MODEL_SECRET_KEY），现在只能查看。请联系开发人员配置后再来换
          key。
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
      {providers === null || absent.length === 0 ? null : (
        <p className={styles.notice}>
          有 {absent.length} 个服务还没接入（还在旧版本上）：
          {absent.map((consumer) => consumer.label).join("、")}
          。它们一直用服务器配置的 key，所以服务器上原来的 key 先别作废。
        </p>
      )}
      {providers === null ? (
        message?.kind === "error" ? null : (
          <p role="status">正在读取…</p>
        )
      ) : (
        <>
          <ul className={styles.cards}>
            {providers.map((provider) => (
              <ProviderCard
                key={provider.id}
                api={api}
                provider={provider}
                effect={effectText(provider, consumers)}
                canChange={configured === true}
                onChanged={changed}
                onError={fail}
                onClear={() => setMessage(null)}
              />
            ))}
          </ul>
          <ConsumerTable providers={providers} consumers={consumers} />
        </>
      )}
    </section>
  );
}

function ConsumerTable({
  providers,
  consumers,
}: {
  readonly providers: readonly ModelProvider[];
  readonly consumers: readonly ModelKeyConsumer[];
}) {
  const cell = (consumer: ModelKeyConsumer, provider: ModelProvider) => {
    const state = loadState(consumer, provider);
    if (state === "unknown") return "未报告加载状态，尚无法确认";
    if (state === "failed") {
      const error = consumer.load_errors?.[provider.id];
      const reason =
        error === "key_unreadable"
          ? "已保存的 key 无法解密"
          : error === "encryption_key_invalid"
            ? "服务的加密配置无效"
            : error === "configuration_unavailable"
              ? "未能读取后台配置"
              : "未能加载后台配置";
      return `加载失败：${reason}，保留服务器配置；请联系管理员检查`;
    }
    const version = loadedVersion(consumer, provider.id);
    const text = version === null ? "服务器配置" : `第 ${version} 版`;
    return state === "loaded" ? text : `${text}（等待重启）`;
  };
  return (
    <table className={styles.table}>
      <caption className={styles.hint}>
        各服务正在用的 key（每分钟报到一次）
      </caption>
      <thead>
        <tr>
          <th scope="col">服务</th>
          {providers.map((provider) => (
            <th key={provider.id} scope="col">
              {provider.name}
            </th>
          ))}
          <th scope="col">最近报到</th>
        </tr>
      </thead>
      <tbody>
        {consumers.map((consumer) => (
          <tr key={consumer.service}>
            <th scope="row">{consumer.label}</th>
            {consumer.reporting ? (
              providers.map((provider) => (
                <td key={provider.id}>{cell(consumer, provider)}</td>
              ))
            ) : (
              <td colSpan={providers.length}>
                未接入：还在旧版本上，用服务器配置的 key
              </td>
            )}
            <td>
              {consumer.seen_at === null ? "—" : formatTime(consumer.seen_at)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ProviderCard({
  api,
  provider,
  effect,
  canChange,
  onChanged,
  onError,
  onClear,
}: {
  readonly api: ModelsApi;
  readonly provider: ModelProvider;
  readonly effect: string;
  readonly canChange: boolean;
  readonly onChanged: (saved: ModelProvider, text: string) => void;
  readonly onError: (error: unknown) => void;
  readonly onClear: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [history, setHistory] = useState<readonly ModelKeyVersion[] | null>(
    null,
  );
  const [showHistory, setShowHistory] = useState(false);
  const [confirming, setConfirming] = useState<number | "env" | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!showHistory) return;
    let cancelled = false;
    api.history(provider.id).then(
      (items) => {
        if (!cancelled) setHistory(items);
      },
      (error: unknown) => {
        if (!cancelled) onError(error);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, provider.id, provider.version, showHistory, onError]);

  const run = async (action: () => Promise<ModelProvider>, text: string) => {
    setBusy(true);
    onClear();
    try {
      const saved = await action();
      setConfirming(null);
      onChanged(saved, text.replace("{version}", String(saved.version)));
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  };

  const titleId = `model-provider-${provider.id}`;
  return (
    <li aria-labelledby={titleId}>
      <h3 id={titleId} className={styles.subheading}>
        {provider.name}
        <small>（{provider.used_for}）</small>
      </h3>
      <dl className={styles.facts}>
        <dt>已保存的 key</dt>
        <dd>
          {provider.key_hint ?? "—"} · {sourceText(provider)}
          {provider.updated_at === null || provider.updated_by === null
            ? null
            : `，${provider.updated_by} 于 ${formatTime(provider.updated_at)} 设置`}
        </dd>
        <dt>生效情况</dt>
        <dd>{effect}</dd>
        <dt>接口地址</dt>
        <dd>
          <code>{provider.base_url ?? "未配置"}</code>（固定）
        </dd>
        <dt>模型</dt>
        <dd>{provider.models.join("、")}（固定）</dd>
      </dl>
      {editing ? (
        <KeyForm
          api={api}
          provider={provider}
          onCancel={() => setEditing(false)}
          onError={onError}
          onSaved={(saved) => {
            setEditing(false);
            onChanged(
              saved,
              `「${provider.name}」已保存第 ${saved.version} 版 key。相关服务做完手头的任务后会自动重启，请查看各服务的加载状态确认生效。`,
            );
          }}
        />
      ) : (
        <span className={styles.rowActions}>
          <button
            type="button"
            disabled={!canChange || busy}
            onClick={() => {
              onClear();
              setEditing(true);
            }}
          >
            更换 key
          </button>
          <button
            type="button"
            aria-expanded={showHistory}
            onClick={() => setShowHistory((open) => !open)}
          >
            {showHistory ? "收起历史" : "历史版本"}
          </button>
          {provider.source === "console" ? (
            confirming === "env" ? (
              <span
                className={styles.confirm}
                role="group"
                aria-label="确认改回"
              >
                会先测试服务器配置的 key，通过才改回。
                <button
                  type="button"
                  className={styles.primary}
                  disabled={busy}
                  onClick={() => {
                    void run(
                      () => api.useEnv(provider.id),
                      `「${provider.name}」已改回服务器配置的 key（第 {version} 版），请查看各服务的加载状态确认生效。`,
                    );
                  }}
                >
                  {busy ? "正在测试…" : "确定改回"}
                </button>
                <button type="button" onClick={() => setConfirming(null)}>
                  取消
                </button>
              </span>
            ) : (
              <button
                type="button"
                disabled={!canChange || busy}
                onClick={() => setConfirming("env")}
              >
                改回服务器配置的 key
              </button>
            )
          ) : null}
        </span>
      )}
      {!showHistory ? null : history === null ? (
        <p role="status">正在读取历史…</p>
      ) : history.length === 0 ? (
        <p className={styles.hint}>还没在后台换过 key。</p>
      ) : (
        <table className={styles.table}>
          <caption className={styles.hint}>
            最近 {history.length} 版（恢复也会先测试那个 key）
          </caption>
          <thead>
            <tr>
              <th scope="col">版本</th>
              <th scope="col">key</th>
              <th scope="col">说明</th>
              <th scope="col">操作人</th>
              <th scope="col">时间</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {history.map((item) => (
              <tr key={item.version}>
                <td>
                  第 {item.version} 版{item.current ? "（当前）" : ""}
                </td>
                <td>
                  {item.source === "env"
                    ? "服务器配置"
                    : (item.key_hint ?? "—")}
                </td>
                <td>{item.note ?? "—"}</td>
                <td>{item.created_by}</td>
                <td>{formatTime(item.created_at)}</td>
                <td>
                  {item.current ? null : confirming === item.version ? (
                    <span
                      className={styles.confirm}
                      role="group"
                      aria-label={`确认恢复第 ${item.version} 版`}
                    >
                      <button
                        type="button"
                        className={styles.primary}
                        disabled={busy}
                        onClick={() => {
                          void run(
                            () => api.restore(provider.id, item.version),
                            `「${provider.name}」已恢复第 ${item.version} 版（存为第 {version} 版），请查看各服务的加载状态确认生效。`,
                          );
                        }}
                      >
                        {busy ? "正在测试…" : "确定恢复"}
                      </button>
                      <button type="button" onClick={() => setConfirming(null)}>
                        取消
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      disabled={!canChange || busy}
                      onClick={() => setConfirming(item.version)}
                    >
                      恢复这一版
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </li>
  );
}

function KeyForm({
  api,
  provider,
  onSaved,
  onCancel,
  onError,
}: {
  readonly api: ModelsApi;
  readonly provider: ModelProvider;
  readonly onSaved: (saved: ModelProvider) => void;
  readonly onCancel: () => void;
  readonly onError: (error: unknown) => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [note, setNote] = useState("");
  const [tested, setTested] = useState<{
    readonly key: string;
    readonly result: ModelKeyTest;
  } | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const candidate = apiKey.trim();
  const passed = tested?.key === candidate && tested.result.ok;

  const test = async () => {
    setBusy("test");
    try {
      setTested({
        key: candidate,
        result: await api.test(provider.id, candidate),
      });
    } catch (error) {
      onError(error);
    } finally {
      setBusy(null);
    }
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!passed) return;
    setBusy("save");
    try {
      onSaved(await api.save(provider.id, candidate, note.trim()));
    } catch (error) {
      onError(error);
      setBusy(null);
    }
  };

  return (
    <form
      className={styles.editor}
      aria-label={`更换${provider.name}的 key`}
      autoComplete="off"
      onSubmit={(event) => {
        void save(event);
      }}
    >
      <div className={styles.formGrid}>
        <label className={styles.field}>
          <span>新的 API key</span>
          <input
            type="password"
            value={apiKey}
            required
            autoComplete="new-password"
            spellCheck={false}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>说明（可选，例如 换成学校账号）</span>
          <input
            value={note}
            maxLength={200}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
      </div>
      {tested === null || tested.key !== candidate ? (
        <p className={styles.hint}>先测试连接，通过后才能保存。</p>
      ) : (
        <p
          className={tested.result.ok ? styles.success : styles.error}
          role={tested.result.ok ? "status" : "alert"}
        >
          {tested.result.ok
            ? `连接成功，用时 ${tested.result.latency_ms} 毫秒`
            : `没通过：${tested.result.message}`}
        </p>
      )}
      <div className={styles.actions}>
        <button
          type="button"
          disabled={busy !== null || candidate === ""}
          onClick={() => {
            void test();
          }}
        >
          {busy === "test" ? "正在测试…" : "测试连接"}
        </button>
        <button
          type="submit"
          className={styles.primary}
          disabled={busy !== null || !passed}
        >
          {busy === "save" ? "正在保存…" : "保存并启用"}
        </button>
        <button type="button" disabled={busy !== null} onClick={onCancel}>
          取消
        </button>
      </div>
    </form>
  );
}
