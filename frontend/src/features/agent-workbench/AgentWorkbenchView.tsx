import { useEffect, useRef } from "react";

import type {
  AgentWorkbenchCitationViewModel,
  AgentWorkbenchRunViewModel,
  AgentWorkbenchScreenState,
  AgentWorkbenchTraceStepViewModel,
} from "./view-model";
import { AGENT_WORKBENCH_QUERY_LIMIT, agentWorkbenchPresets } from "./presets";
import styles from "./AgentWorkbenchPanel.module.css";

export type AgentWorkbenchViewProps = Readonly<{
  state: AgentWorkbenchScreenState;
  query: string;
  onQueryChange: (query: string) => void;
  onRun: () => void;
  onCancel: () => void;
}>;

export function AgentWorkbenchView({
  state,
  query,
  onQueryChange,
  onRun,
  onCancel,
}: AgentWorkbenchViewProps) {
  const resultHeadingRef = useRef<HTMLHeadingElement>(null);
  const isRunning = state.kind === "running";
  const queryLength = Array.from(query).length;
  const isQueryValid =
    query.trim().length > 0 && queryLength <= AGENT_WORKBENCH_QUERY_LIMIT;
  const announcement = getAnnouncement(state);

  useEffect(() => {
    if (
      state.kind === "completed" ||
      state.kind === "refused" ||
      state.kind === "budget-exhausted" ||
      state.kind === "failed"
    ) {
      resultHeadingRef.current?.focus();
    }
  }, [state.kind]);

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isQueryValid && !isRunning) onRun();
  }

  return (
    <section
      className={styles.workspace}
      aria-labelledby="workbench-title"
      aria-busy={isRunning}
    >
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>LOCAL AGENT / READ-ONLY</p>
          <h2 id="workbench-title">Agent 研究工作台</h2>
          <p className={styles.intro}>
            用四个受控只读工具，在最多四次模型步骤内完成证据核验、事件下钻、品牌边界检查与文案验证。
          </p>
        </div>
        <div className={styles.localBadge} role="note">
          <span aria-hidden="true">●</span>
          仅限本地开发
        </div>
      </header>

      <div className={styles.boundaryStrip} aria-label="工作台安全边界">
        <span>≤ 4 MODEL STEPS</span>
        <span>≤ 4 TOOL CALLS</span>
        <span>HTTPS CITATIONS</span>
        <span>ZERO BUSINESS WRITES</span>
      </div>

      <div className={styles.controlGrid}>
        <form
          className={styles.queryPanel}
          aria-label="运行受控 Agent 问题"
          onSubmit={submit}
        >
          <div className={styles.panelCode}>01 / QUESTION</div>
          <label htmlFor="agent-workbench-query">向受控 Agent 提问</label>
          <p id="agent-workbench-query-hint" className={styles.fieldHint}>
            输入只会传给本地工作台；工具不能写数据库、抓取任意网页或触发业务投递。
          </p>
          <textarea
            id="agent-workbench-query"
            value={query}
            maxLength={AGENT_WORKBENCH_QUERY_LIMIT}
            rows={5}
            aria-describedby="agent-workbench-query-hint agent-workbench-query-count"
            disabled={isRunning}
            onChange={(event) => onQueryChange(event.currentTarget.value)}
          />
          <div className={styles.queryFooter}>
            <span id="agent-workbench-query-count" className={styles.counter}>
              {queryLength} / {AGENT_WORKBENCH_QUERY_LIMIT}
            </span>
            <div className={styles.actionRow}>
              {isRunning ? (
                <button
                  className={styles.secondaryButton}
                  type="button"
                  onClick={onCancel}
                >
                  取消本次运行
                </button>
              ) : null}
              <button type="submit" disabled={!isQueryValid || isRunning}>
                {isRunning ? "运行中…" : "运行受控分析"}
              </button>
            </div>
          </div>
        </form>

        <section className={styles.presetPanel} aria-labelledby="preset-title">
          <div className={styles.panelCode}>PRESET / FIXTURE-SAFE</div>
          <h3 id="preset-title">演示问题</h3>
          <p>选择一个脱敏问题，或在左侧输入不超过 500 字的问题。</p>
          <div className={styles.presetList}>
            {agentWorkbenchPresets.map((preset, index) => (
              <button
                key={preset.id}
                type="button"
                disabled={isRunning}
                aria-pressed={query === preset.query}
                onClick={() => onQueryChange(preset.query)}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                {preset.label}
              </button>
            ))}
          </div>
        </section>
      </div>

      <p className={styles.liveRegion} role="status" aria-live="polite">
        {announcement}
      </p>

      <RunStatus state={state} headingRef={resultHeadingRef} />
    </section>
  );
}

function RunStatus({
  state,
  headingRef,
}: Readonly<{
  state: AgentWorkbenchScreenState;
  headingRef: React.RefObject<HTMLHeadingElement | null>;
}>) {
  if (state.kind === "idle") {
    return (
      <div className={styles.idleState}>
        <p className={styles.panelCode}>RUN / IDLE</p>
        <h3>等待一个可验证的问题</h3>
        <p>运行后，这里会按顺序展示安全动作、观察结果、引用声明和预算指标。</p>
      </div>
    );
  }

  if (state.kind === "running") {
    return (
      <div className={styles.runningState} role="status">
        <div className={styles.activityMarker} aria-hidden="true" />
        <div>
          <p className={styles.panelCode}>RUN / IN PROGRESS</p>
          <h3>正在执行有界工具循环</h3>
          <p>等待单次响应完成；不会展示隐藏推理或中间提示词。</p>
        </div>
      </div>
    );
  }

  if (state.kind === "cancelled") {
    return (
      <div className={styles.idleState} data-status="cancelled">
        <p className={styles.panelCode}>RUN / CANCELLED</p>
        <h3>本次本地请求已取消</h3>
        <p>已丢弃未完成响应，你可以调整问题后重新运行。</p>
      </div>
    );
  }

  if (state.kind === "failed") {
    return (
      <div className={styles.errorState} role="alert">
        <p className={styles.panelCode}>RUN / FAILED</p>
        <h3 ref={headingRef} tabIndex={-1}>
          工作台暂时无法完成请求
        </h3>
        <p>{state.message}</p>
        <code>{state.code}</code>
        {state.requestId === null ? null : (
          <p className={styles.requestId}>请求 ID：{state.requestId}</p>
        )}
      </div>
    );
  }

  return (
    <RunResult query={state.query} run={state.run} headingRef={headingRef} />
  );
}

function RunResult({
  query,
  run,
  headingRef,
}: Readonly<{
  query: string;
  run: AgentWorkbenchRunViewModel;
  headingRef: React.RefObject<HTMLHeadingElement | null>;
}>) {
  const citationPositions = new Map(
    run.citations.map((citation, index) => [citation.id, index + 1]),
  );

  return (
    <article className={styles.result} data-status={run.status}>
      <header className={styles.resultHeader}>
        <div>
          <p className={styles.panelCode}>RUN / {run.runId}</p>
          <h3 ref={headingRef} tabIndex={-1}>
            {run.statusLabel}
          </h3>
        </div>
        <span className={styles.statusBadge} data-status={run.status}>
          {run.statusLabel}
        </span>
      </header>

      <ExecutionRail query={query} run={run} />

      <div className={styles.resultGrid}>
        <section className={styles.answerPanel} aria-labelledby="answer-title">
          <div className={styles.sectionHeading}>
            <p className={styles.panelCode}>03 / CITED ANSWER</p>
            <h4 id="answer-title">有界结论</h4>
          </div>
          <p className={styles.summary}>{run.summary}</p>
          {run.claims.length === 0 ? (
            <p className={styles.emptyCopy}>没有可安全陈述的声明。</p>
          ) : (
            <ol className={styles.claimList}>
              {run.claims.map((claim, index) => (
                <li key={claim.id}>
                  <div className={styles.claimTopline}>
                    <span>CLAIM {String(index + 1).padStart(2, "0")}</span>
                    <span>{claim.kindLabel}</span>
                  </div>
                  <p>{claim.text}</p>
                  {claim.citationIds.length === 0 ? (
                    <span className={styles.noCitation}>无需外部事实引用</span>
                  ) : (
                    <ul
                      className={styles.claimCitations}
                      aria-label={`声明 ${index + 1} 的引用`}
                    >
                      {claim.citationIds.map((citationId) => {
                        const position = citationPositions.get(citationId);
                        return (
                          <li key={citationId}>
                            {position === undefined ? (
                              <span>引用未解析</span>
                            ) : (
                              <a href={`#agent-workbench-citation-${position}`}>
                                [{position}]
                              </a>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </li>
              ))}
            </ol>
          )}
        </section>

        <MetricsPanel run={run} />
      </div>

      <CitationCatalog citations={run.citations} />
      <TraceTimeline steps={run.steps} />
    </article>
  );
}

function ExecutionRail({
  query,
  run,
}: Readonly<{ query: string; run: AgentWorkbenchRunViewModel }>) {
  const visibleSteps = run.steps.filter(
    (step) => step.kind === "tool_result" || step.kind === "error",
  );
  return (
    <section className={styles.railSection} aria-labelledby="execution-title">
      <div className={styles.sectionHeading}>
        <p className={styles.panelCode}>02 / BOUNDED EXECUTION</p>
        <h4 id="execution-title">问题 → 工具 → 引用声明</h4>
      </div>
      <ol className={styles.executionRail} aria-label="有界执行路径">
        <li>
          <span className={styles.railMarker}>Q</span>
          <div>
            <strong>受控问题</strong>
            <p>{query}</p>
          </div>
        </li>
        {visibleSteps.map((step) => (
          <li key={step.id} data-status={step.status}>
            <span className={styles.railMarker}>
              {String(step.ordinal).padStart(2, "0")}
            </span>
            <div>
              <strong>{step.displayLabel}</strong>
              <p>{step.statusLabel}</p>
            </div>
          </li>
        ))}
        <li data-status={run.status}>
          <span className={styles.railMarker}>A</span>
          <div>
            <strong>{run.statusLabel}</strong>
            <p>
              {run.claims.length} 条声明 · {run.citations.length} 个已使用引用
            </p>
          </div>
        </li>
      </ol>
    </section>
  );
}

function MetricsPanel({ run }: Readonly<{ run: AgentWorkbenchRunViewModel }>) {
  const metrics = [
    { label: "模型步骤", value: `${run.metrics.modelSteps} / 4` },
    { label: "工具调用", value: `${run.metrics.toolCalls} / 4` },
    {
      label: "成功工具",
      value: `${run.metrics.successfulToolCalls} / ${run.metrics.toolCalls}`,
    },
    { label: "总耗时", value: formatDuration(run.metrics.durationMs) },
    { label: "模型耗时", value: formatDuration(run.metrics.modelLatencyMs) },
    { label: "工具耗时", value: formatDuration(run.metrics.toolLatencyMs) },
    {
      label: "输入 Token",
      value: formatOptionalCount(run.metrics.inputTokens),
    },
    {
      label: "输出 Token",
      value: formatOptionalCount(run.metrics.outputTokens),
    },
    {
      label: "推理 Token",
      value: formatOptionalCount(run.metrics.reasoningTokens),
    },
  ] as const;

  return (
    <section className={styles.metricsPanel} aria-labelledby="metrics-title">
      <div className={styles.sectionHeading}>
        <p className={styles.panelCode}>RUN / TELEMETRY</p>
        <h4 id="metrics-title">预算与指标</h4>
      </div>
      <dl>
        {metrics.map((metric) => (
          <div key={metric.label}>
            <dt>{metric.label}</dt>
            <dd>{metric.value}</dd>
          </div>
        ))}
      </dl>
      <p className={styles.telemetryNote}>
        Token 仅在模型适配器提供类型化用量时显示；缺失不会估算。
      </p>
    </section>
  );
}

function CitationCatalog({
  citations,
}: Readonly<{ citations: readonly AgentWorkbenchCitationViewModel[] }>) {
  return (
    <section className={styles.catalog} aria-labelledby="citations-title">
      <div className={styles.sectionHeading}>
        <p className={styles.panelCode}>CATALOG / CLAIM-USED ONLY</p>
        <h4 id="citations-title">引用目录</h4>
      </div>
      {citations.length === 0 ? (
        <p className={styles.emptyCopy}>本次回答没有使用可展示的引用。</p>
      ) : (
        <ol className={styles.citationList}>
          {citations.map((citation, index) => (
            <li key={citation.id} id={`agent-workbench-citation-${index + 1}`}>
              <div className={styles.citationIndex}>[{index + 1}]</div>
              <div>
                <div className={styles.citationTopline}>
                  <span>{citation.sourceName}</span>
                  <span>
                    {citation.evidenceEligible
                      ? "可用于事实证据"
                      : "仅用于表达，不可证明事实"}
                  </span>
                </div>
                <p>{citation.title}</p>
                <span className={styles.citationKind}>
                  {citation.kindLabel}
                </span>
                {citation.url === null ? (
                  <span className={styles.hiddenLink}>
                    {citation.evidenceEligible
                      ? "外链已隐藏（未通过 HTTPS 校验）"
                      : "无公开事实链接"}
                  </span>
                ) : (
                  <a
                    href={citation.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    查看来源 <span aria-hidden="true">↗</span>
                    <span className={styles.srOnly}>（在新窗口打开）</span>
                  </a>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function TraceTimeline({
  steps,
}: Readonly<{ steps: readonly AgentWorkbenchTraceStepViewModel[] }>) {
  return (
    <section className={styles.trace} aria-labelledby="trace-title">
      <div className={styles.sectionHeading}>
        <p className={styles.panelCode}>TRACE / REDACTED</p>
        <h4 id="trace-title">动作与观察</h4>
      </div>
      <p className={styles.traceNote}>
        只展示受控动作、结果计数和安全错误码；不展示隐藏推理、完整提示词或
        provider 响应体。
      </p>
      <ol className={styles.traceList}>
        {steps.map((step) => (
          <li key={step.id}>
            <div className={styles.traceOrdinal}>
              {String(step.ordinal).padStart(2, "0")}
            </div>
            <div className={styles.traceBody}>
              <div className={styles.traceHeading}>
                <div>
                  <span>{step.kindLabel}</span>
                  <h5>{step.displayLabel}</h5>
                </div>
                <span className={styles.stepStatus} data-status={step.status}>
                  {step.statusLabel}
                </span>
              </div>
              <dl className={styles.traceDetails}>
                {step.toolLabel === null ? null : (
                  <div>
                    <dt>工具</dt>
                    <dd>{step.toolLabel}</dd>
                  </div>
                )}
                {step.durationMs === null ? null : (
                  <div>
                    <dt>耗时</dt>
                    <dd>{formatDuration(step.durationMs)}</dd>
                  </div>
                )}
                {step.details.map((detail) => (
                  <div key={`${detail.label}-${detail.value}`}>
                    <dt>{detail.label}</dt>
                    <dd>{detail.value}</dd>
                  </div>
                ))}
              </dl>
              {step.citationIds.length > 0 ? (
                <p className={styles.traceCitations}>
                  返回引用：{step.citationIds.join("、")}
                </p>
              ) : null}
              {step.code === null ? null : (
                <code className={styles.traceCode}>{step.code}</code>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function getAnnouncement(state: AgentWorkbenchScreenState): string {
  switch (state.kind) {
    case "idle":
      return "";
    case "running":
      return "工作台正在运行有界分析。";
    case "completed":
      return `分析已完成，共 ${state.run.claims.length} 条声明和 ${state.run.citations.length} 个已使用引用。`;
    case "refused":
      return "工作台已安全拒绝本次请求。";
    case "budget-exhausted":
      return "工作台已达到四步预算并停止。";
    case "cancelled":
      return "本次本地请求已取消。";
    case "failed":
      return `工作台运行失败，安全错误码 ${state.code}。`;
  }
}

function formatDuration(durationMs: number): string {
  return durationMs < 1_000
    ? `${durationMs.toLocaleString("zh-CN")} ms`
    : `${(durationMs / 1_000).toFixed(2)} s`;
}

function formatOptionalCount(value: number | null): string {
  return value === null ? "未提供" : value.toLocaleString("zh-CN");
}
