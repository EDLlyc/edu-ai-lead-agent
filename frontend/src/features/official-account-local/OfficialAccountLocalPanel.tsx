import { useState } from "react";

import {
  type OfficialAccountManualReviewDecision,
  type OfficialAccountManualReviewViewModel,
  type OfficialAccountRunDetailViewModel,
  type OfficialAccountRunSummaryViewModel,
  type OfficialAccountStage,
} from "./api";
import {
  useCreateFixtureArticleRun,
  useCreateLiveArticleRun,
  useOfficialAccountCapabilities,
  useOfficialAccountManualReview,
  useOfficialAccountRun,
  useOfficialAccountRuns,
  useRetryOfficialAccountRun,
} from "./hooks";

import styles from "./OfficialAccountLocalPanel.module.css";

const processingStages: readonly Readonly<{
  stage: OfficialAccountStage;
  label: string;
}>[] = [
  { stage: "generating", label: "结构化长文" },
  { stage: "validating", label: "规则校验" },
  { stage: "auditing", label: "模型审校" },
  { stage: "rendering", label: "兼容排版" },
  { stage: "generating_body_visuals", label: "正文块原创配图" },
  { stage: "staging_body_media", label: "正文图片" },
  { stage: "staging_cover", label: "封面" },
  { stage: "creating_local_draft", label: "模拟草稿" },
];

export function OfficialAccountLocalPanel() {
  const capabilities = useOfficialAccountCapabilities();
  const runs = useOfficialAccountRuns();
  const fixtureMutation = useCreateFixtureArticleRun();
  const liveMutation = useCreateLiveArticleRun();
  const retryMutation = useRetryOfficialAccountRun();
  const manualReviewMutation = useOfficialAccountManualReview();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [materialPackageId, setMaterialPackageId] = useState("");
  const effectiveMaterialPackageId =
    materialPackageId || capabilities.data?.eligibleMaterials[0]?.id || "";
  const effectiveSelectedRunId = selectedRunId ?? runs.data?.[0]?.id ?? null;
  const detail = useOfficialAccountRun(effectiveSelectedRunId);

  const busy = fixtureMutation.isPending || liveMutation.isPending;
  const mutationError =
    fixtureMutation.error ?? liveMutation.error ?? retryMutation.error;

  return (
    <section
      className={styles.workbench}
      aria-labelledby="official-account-title"
    >
      <header className={styles.header}>
        <div>
          <p className={styles.kicker}>LOCAL ARTICLE / SIMULATION 01</p>
          <h2 id="official-account-title">公众号本地草稿台</h2>
          <p className={styles.intro}>
            从受治理素材生成结构化长文，在本地完成审校、排版、正文图片、封面和草稿模拟。
          </p>
        </div>
        <div className={styles.boundary} role="note">
          <span>SAFETY INTERLOCK</span>
          <strong>本地模拟，未同步公众号</strong>
          <p>不登录账号，不读取公众号凭据，不执行网络侧草稿或群发操作。</p>
        </div>
      </header>

      {capabilities.isLoading ? (
        <p role="status">正在读取本地草稿能力…</p>
      ) : null}
      {capabilities.isError ? (
        <p className={styles.error} role="alert">
          能力信息读取失败，请确认本地 API 已启动。
        </p>
      ) : null}
      {capabilities.data !== undefined && !capabilities.data.enabled ? (
        <p className={styles.error} role="alert">
          服务器尚未开启公众号本地草稿功能。
        </p>
      ) : null}

      {capabilities.data?.enabled === true ? (
        <div className={styles.controlGrid}>
          <form
            className={styles.liveControl}
            aria-label="真实模型长文生成"
            onSubmit={(event) => {
              event.preventDefault();
              if (effectiveMaterialPackageId.length === 0) return;
              liveMutation.mutate(effectiveMaterialPackageId, {
                onSuccess: (run) => setSelectedRunId(run.id),
              });
            }}
          >
            <span className={styles.controlIndex}>01 / LIVE</span>
            <label htmlFor="official-account-material">合格素材包</label>
            <select
              id="official-account-material"
              value={effectiveMaterialPackageId}
              onChange={(event) => setMaterialPackageId(event.target.value)}
            >
              {capabilities.data.eligibleMaterials.length === 0 ? (
                <option value="">暂无合格素材包</option>
              ) : null}
              {capabilities.data.eligibleMaterials.map((material) => (
                <option key={material.id} value={material.id}>
                  {material.title}
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={
                busy ||
                effectiveMaterialPackageId.length === 0 ||
                !capabilities.data.liveAvailable
              }
            >
              调用模型生成长文
            </button>
            {!capabilities.data.liveAvailable ? (
              <small>{capabilities.data.liveUnavailableReason}</small>
            ) : (
              <small>每个新指纹最多触发一次生成和一次审校调用。</small>
            )}
            <small>
              正文选图：
              {capabilities.data.visualSemanticEnabled
                ? "多模态语义匹配（完整索引预检后）"
                : "确定性标签回退（默认）"}
            </small>
            <small>
              原创正文配图：
              {capabilities.data.generatedVisualsEnabled
                ? "已启用（仅 live；调用前持久化意图）"
                : "未启用（继续使用批准图库原图）"}
            </small>
          </form>

          <div className={styles.fixtureControl}>
            <span className={styles.controlIndex}>02 / FIXTURE</span>
            <h3>离线脱敏演示</h3>
            <p>使用确定性文章、审校和仓库内图片；不创建任何模型客户端。</p>
            <button
              type="button"
              disabled={busy || !capabilities.data.fixtureAvailable}
              onClick={() =>
                fixtureMutation.mutate(undefined, {
                  onSuccess: (run) => setSelectedRunId(run.id),
                })
              }
            >
              创建离线演示草稿
            </button>
          </div>
        </div>
      ) : null}

      {mutationError !== null ? (
        <p className={styles.error} role="alert">
          操作未完成：{mutationError.message}
        </p>
      ) : null}

      <div className={styles.workspaceGrid}>
        <RunRail
          runs={runs.data ?? []}
          selectedRunId={effectiveSelectedRunId}
          loading={runs.isLoading}
          onSelect={setSelectedRunId}
        />
        <div className={styles.detailPane}>
          {effectiveSelectedRunId === null ? (
            <p className={styles.empty}>
              创建或选择一条运行以查看文章与模拟草稿。
            </p>
          ) : detail.isLoading ? (
            <p role="status">正在读取运行详情…</p>
          ) : detail.isError || detail.data === undefined ? (
            <p className={styles.error} role="alert">
              运行详情读取失败。
            </p>
          ) : (
            <RunDetail
              detail={detail.data}
              retrying={retryMutation.isPending}
              onRetry={() => retryMutation.mutate(detail.data.summary.id)}
              reviewResult={
                manualReviewMutation.variables?.runId === detail.data.summary.id
                  ? manualReviewMutation.data
                  : undefined
              }
              reviewError={
                manualReviewMutation.variables?.runId === detail.data.summary.id
                  ? manualReviewMutation.error
                  : null
              }
              reviewing={manualReviewMutation.isPending}
              onReview={(decision, reviewerLabel, note) =>
                manualReviewMutation.mutate({
                  runId: detail.data.summary.id,
                  decision,
                  reviewerLabel,
                  note,
                })
              }
            />
          )}
        </div>
      </div>
    </section>
  );
}

function RunRail({
  runs,
  selectedRunId,
  loading,
  onSelect,
}: Readonly<{
  runs: readonly OfficialAccountRunSummaryViewModel[];
  selectedRunId: string | null;
  loading: boolean;
  onSelect: (runId: string) => void;
}>) {
  return (
    <div
      className={styles.runRail}
      aria-labelledby="official-account-runs-title"
    >
      <div className={styles.railHeading}>
        <h3 id="official-account-runs-title">运行记录</h3>
        <span>{runs.length.toString().padStart(2, "0")}</span>
      </div>
      {loading ? <p role="status">正在读取运行列表…</p> : null}
      {!loading && runs.length === 0 ? <p>尚无本地文章运行。</p> : null}
      <ol>
        {runs.map((run) => (
          <li key={run.id}>
            <button
              type="button"
              className={
                run.id === selectedRunId ? styles.activeRun : undefined
              }
              aria-current={run.id === selectedRunId ? "true" : undefined}
              onClick={() => onSelect(run.id)}
            >
              <span>{run.modeLabel}</span>
              <strong>{run.statusLabel}</strong>
              <small>{run.stageLabel}</small>
              <code>{run.id.slice(0, 8)}</code>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function RunDetail({
  detail,
  retrying,
  onRetry,
  reviewResult,
  reviewError,
  reviewing,
  onReview,
}: Readonly<{
  detail: OfficialAccountRunDetailViewModel;
  retrying: boolean;
  onRetry: () => void;
  reviewResult: OfficialAccountManualReviewViewModel | undefined;
  reviewError: Error | null;
  reviewing: boolean;
  onReview: (
    decision: OfficialAccountManualReviewDecision,
    reviewerLabel: string,
    note: string | null,
  ) => void;
}>) {
  const { summary, article } = detail;
  return (
    <article aria-labelledby="official-account-detail-title">
      <header className={styles.detailHeader}>
        <div>
          <p>{summary.modeLabel}</p>
          <h3 id="official-account-detail-title">
            {article?.title ?? summary.statusLabel}
          </h3>
          <span>{summary.sourceLabel}</span>
        </div>
        <div className={styles.statusStack}>
          <strong>{summary.statusLabel}</strong>
          <span>{summary.stageLabel}</span>
        </div>
      </header>

      <StageTimeline
        currentStage={summary.stage}
        status={summary.status}
        generatedVisualProgress={detail.generatedVisualProgress}
      />

      {summary.errorCode !== null ? (
        <div className={styles.error} role="alert">
          错误代码：{summary.errorCode}
          {summary.status === "result_unknown" ? (
            <p>草稿创建结果未知，系统不会自动重做。</p>
          ) : null}
          {summary.status === "failed" && summary.errorRetryable ? (
            <button type="button" disabled={retrying} onClick={onRetry}>
              从最近成功阶段重试
            </button>
          ) : null}
        </div>
      ) : null}

      {article === null ? (
        <p className={styles.empty}>
          文章尚未生成，页面会在运行结束前持续轮询。
        </p>
      ) : (
        <>
          <section
            className={styles.articleLead}
            aria-labelledby="article-summary-title"
          >
            <span>AUTHOR / {article.author}</span>
            <h4 id="article-summary-title">摘要与导语</h4>
            <strong>{article.digest}</strong>
            <p>{article.lead}</p>
          </section>
          <section
            className={styles.articleBody}
            aria-labelledby="article-body-title"
          >
            <h4 id="article-body-title">文章结构</h4>
            {article.sections.map((section, sectionIndex) => (
              <div
                key={`${section.heading}-${sectionIndex}`}
                className={styles.articleSection}
              >
                <span>{String(sectionIndex + 1).padStart(2, "0")}</span>
                <div>
                  <h5>{section.heading}</h5>
                  {section.blocks.map((block, blockIndex) => {
                    const key = `${sectionIndex}-${blockIndex}`;
                    if (block.kind === "bullet_list") {
                      return (
                        <ul key={key}>
                          {block.items.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      );
                    }
                    if (block.kind === "image") {
                      return (
                        <p key={key} className={styles.mediaSlot}>
                          IMAGE SLOT / {block.alt_text}
                        </p>
                      );
                    }
                    if (block.kind === "quote" || block.kind === "callout") {
                      return <blockquote key={key}>{block.text}</blockquote>;
                    }
                    return <p key={key}>{block.text}</p>;
                  })}
                </div>
              </div>
            ))}
            <p className={styles.conclusion}>{article.conclusion}</p>
          </section>
          <Provenance detail={detail} />
          <ManualReviewRail
            detail={detail}
            result={reviewResult}
            error={reviewError}
            reviewing={reviewing}
            onReview={onReview}
          />
          <MediaAndPreview detail={detail} />
        </>
      )}
    </article>
  );
}

function ManualReviewRail({
  detail,
  result,
  error,
  reviewing,
  onReview,
}: Readonly<{
  detail: OfficialAccountRunDetailViewModel;
  result: OfficialAccountManualReviewViewModel | undefined;
  error: Error | null;
  reviewing: boolean;
  onReview: (
    decision: OfficialAccountManualReviewDecision,
    reviewerLabel: string,
    note: string | null,
  ) => void;
}>) {
  const [reviewerLabel, setReviewerLabel] = useState("");
  const [note, setNote] = useState("");
  const [pendingDecision, setPendingDecision] =
    useState<OfficialAccountManualReviewDecision | null>(null);
  const review = result ?? detail.manualReview;
  const final = review.status !== "pending";
  const ready =
    detail.summary.status === "ready" && detail.draft?.state === "ready";
  const canChoose = ready && !final && reviewerLabel.trim().length > 0;

  return (
    <section
      className={styles.reviewRail}
      aria-labelledby="official-account-manual-review-title"
      data-status={review.status}
    >
      <div className={styles.reviewHeading}>
        <div>
          <span>03 / HUMAN CHECKPOINT</span>
          <h4 id="official-account-manual-review-title">最终人工审稿</h4>
        </div>
        <strong>{review.statusLabel}</strong>
      </div>
      <p>
        模型审校与素材审核不会自动批准文稿。这里记录一次不可更改的人工决定，且不会连接公众号。
      </p>

      {final ? (
        <dl className={styles.reviewRecord} aria-label="最终人工审稿记录">
          <div>
            <dt>审稿标识</dt>
            <dd>{review.reviewerLabel}</dd>
          </div>
          <div>
            <dt>记录时间</dt>
            <dd>{review.reviewedAtLabel}</dd>
          </div>
          {review.note !== null ? (
            <div>
              <dt>审稿备注</dt>
              <dd>{review.note}</dd>
            </div>
          ) : null}
          <div>
            <dt>记录指纹</dt>
            <dd>{review.requestFingerprint?.slice(0, 16)}</dd>
          </div>
        </dl>
      ) : (
        <form
          className={styles.reviewForm}
          onSubmit={(event) => event.preventDefault()}
        >
          <label htmlFor="official-account-reviewer-label">审稿标识</label>
          <input
            id="official-account-reviewer-label"
            value={reviewerLabel}
            maxLength={80}
            required
            autoComplete="off"
            placeholder="例如：内容审核"
            onChange={(event) => setReviewerLabel(event.target.value)}
          />
          <label htmlFor="official-account-review-note">审稿备注（可选）</label>
          <textarea
            id="official-account-review-note"
            value={note}
            maxLength={2000}
            rows={3}
            placeholder="记录事实、标题、摘要与配图核对结果"
            onChange={(event) => setNote(event.target.value)}
          />
          {!ready ? (
            <p className={styles.reviewNotice} role="status">
              只有本地草稿就绪后才能提交最终人工审稿。
            </p>
          ) : null}
          <div className={styles.reviewActions}>
            <button
              type="button"
              className={styles.approveAction}
              disabled={!canChoose || reviewing}
              onClick={() => setPendingDecision("approved")}
            >
              批准文稿
            </button>
            <button
              type="button"
              className={styles.rejectAction}
              disabled={!canChoose || reviewing}
              onClick={() => setPendingDecision("rejected")}
            >
              退回文稿
            </button>
          </div>
          {pendingDecision !== null ? (
            <div className={styles.reviewConfirmation} role="status">
              <strong>
                {pendingDecision === "approved"
                  ? "确认批准这份文稿？"
                  : "确认退回这份文稿？"}
              </strong>
              <p>提交后不能改成另一项决定，也不会触发上传或发送。</p>
              <div>
                <button
                  type="button"
                  disabled={reviewing}
                  onClick={() => {
                    onReview(
                      pendingDecision,
                      reviewerLabel.trim(),
                      note.trim().length === 0 ? null : note.trim(),
                    );
                    setPendingDecision(null);
                  }}
                >
                  {reviewing ? "正在记录…" : "确认记录"}
                </button>
                <button
                  type="button"
                  className={styles.cancelAction}
                  disabled={reviewing}
                  onClick={() => setPendingDecision(null)}
                >
                  取消
                </button>
              </div>
            </div>
          ) : null}
        </form>
      )}
      <p className={styles.reviewStatus} aria-live="polite">
        {result === undefined
          ? `当前状态：${review.statusLabel}`
          : result.idempotentReplay
            ? `已确认原审稿记录：${result.statusLabel}`
            : `审稿记录已保存：${result.statusLabel}`}
      </p>
      {error !== null ? (
        <p className={styles.error} role="alert">
          人工审稿未保存：{error.message}
        </p>
      ) : null}
    </section>
  );
}

function StageTimeline({
  currentStage,
  status,
  generatedVisualProgress,
}: Readonly<{
  currentStage: OfficialAccountStage;
  status: OfficialAccountRunSummaryViewModel["status"];
  generatedVisualProgress: OfficialAccountRunDetailViewModel["generatedVisualProgress"];
}>) {
  const currentIndex = processingStages.findIndex(
    (item) => item.stage === currentStage,
  );
  return (
    <section
      className={styles.timeline}
      aria-labelledby="official-account-timeline-title"
    >
      <h4 id="official-account-timeline-title">处理阶段</h4>
      <ol>
        {processingStages.map((item, index) => {
          const state =
            status === "ready" || (currentIndex >= 0 && index < currentIndex)
              ? "完成"
              : item.stage === currentStage
                ? "当前"
                : "等待";
          return (
            <li key={item.stage} data-state={state}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>
                {item.stage === "generating_body_visuals"
                  ? `${item.label} ${generatedVisualProgress.ready}/${generatedVisualProgress.total}`
                  : item.label}
              </strong>
              <small>{state}</small>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Provenance({
  detail,
}: Readonly<{ detail: OfficialAccountRunDetailViewModel }>) {
  const article = detail.article;
  if (article === null) return null;
  return (
    <div className={styles.provenanceGrid}>
      <section aria-labelledby="article-claims-title">
        <h4 id="article-claims-title">Claim 绑定</h4>
        <ul className={styles.claimList}>
          {article.claims.map((claim) => (
            <li key={claim.id}>
              <span>{claim.kind}</span>
              <strong>{claim.text}</strong>
              <small>
                E {claim.evidence_ids.length} / B {claim.brand_chunk_ids.length}
              </small>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="article-sources-title">
        <h4 id="article-sources-title">来源与质量</h4>
        <ol className={styles.sourceList}>
          {article.sources.map((source) => (
            <li key={source.evidence_id}>
              <a
                href={source.source_url}
                target="_blank"
                rel="noreferrer noopener"
              >
                {source.source_name}（新窗口）
              </a>
              <code>{source.evidence_id.slice(0, 8)}</code>
            </li>
          ))}
        </ol>
        <dl className={styles.metrics}>
          <div>
            <dt>确定性校验</dt>
            <dd>
              {detail.validation?.passed === true ? "通过" : "未通过或未完成"}
            </dd>
          </div>
          <div>
            <dt>模型审校</dt>
            <dd>
              {detail.audit?.accepted === true ? "接受" : "未接受或未完成"}
            </dd>
          </div>
          <div>
            <dt>模型身份</dt>
            <dd>{detail.summary.providerModel}</dd>
          </div>
          <div>
            <dt>Token 用量</dt>
            <dd>
              {detail.usage === null
                ? "—"
                : `${detail.usage.prompt_tokens} / ${detail.usage.completion_tokens}`}
            </dd>
          </div>
          <div>
            <dt>规则版本</dt>
            <dd>{article.versions.rule_version}</dd>
          </div>
          <div>
            <dt>内容指纹</dt>
            <dd>{article.content_fingerprint.slice(0, 16)}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

function MediaAndPreview({
  detail,
}: Readonly<{ detail: OfficialAccountRunDetailViewModel }>) {
  return (
    <section
      className={styles.outputGrid}
      aria-labelledby="official-account-output-title"
    >
      <div>
        <h4 id="official-account-output-title">本地媒体</h4>
        <div className={styles.mediaSelection} role="note">
          <strong>
            自动选图：{detail.mediaSelection.bodyImageCount} 张正文图
            {detail.mediaSelection.safelyDegraded ? "（安全降级）" : ""}
          </strong>
          <span>
            {detail.mediaSelection.modeLabel} · 目标
            {detail.mediaSelection.targetLabel}
          </span>
          {detail.mediaSelection.closedReasonLabel !== null ? (
            <span>关闭原因：{detail.mediaSelection.closedReasonLabel}</span>
          ) : null}
          {detail.mediaSelection.embeddingIdentity !== null ? (
            <span>
              {detail.mediaSelection.embeddingIdentity.provider} /{" "}
              {detail.mediaSelection.embeddingIdentity.model} /{" "}
              {detail.mediaSelection.embeddingIdentity.dimensions} 维
            </span>
          ) : null}
          <ol>
            {detail.mediaSelection.explanation.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
          <small>
            相似度只用于合格图片排序，不代表内容或配图已经通过人工审稿。
          </small>
          <code>{detail.mediaSelection.policyVersion}</code>
          {detail.mediaSelection.visualSelectorVersion !== null ? (
            <code>{detail.mediaSelection.visualSelectorVersion}</code>
          ) : null}
        </div>
        {detail.generatedVisuals.length > 0 ? (
          <div className={styles.mediaSelection} role="note">
            <strong>
              按正文块原创配图结果 · 已就绪{" "}
              {detail.generatedVisualProgress.ready}/
              {detail.generatedVisualProgress.total}
            </strong>
            <small>
              图片没有独立人工审核动作；文章仍遵守最终审稿与本地模拟边界。
            </small>
            <ol>
              {detail.generatedVisuals.map((visual) => (
                <li key={`${visual.ordinal}-${visual.referenceAssetRef}`}>
                  第 {visual.sectionIndex + 1} 节
                  {visual.blockIndex === null
                    ? ""
                    : ` / 文本块 ${visual.blockIndex + 1}`}
                  {visual.blockKind === null ? "" : ` / ${visual.blockKind}`} ·
                  {visual.statusLabel} · 参考项{" "}
                  <code>{visual.referenceAssetRef}</code>
                  {visual.dimensionsLabel === null
                    ? ""
                    : ` · ${visual.dimensionsLabel}`}
                </li>
              ))}
            </ol>
          </div>
        ) : null}
        <div className={styles.contextStatus} role="status">
          <strong>新闻原图</strong>
          <span>
            {detail.contextMediaStatus === "ready"
              ? "已从入选新闻的持久化快照加入 2 张上下文图片。"
              : detail.contextMediaStatus === "partial"
                ? "已从入选新闻的持久化快照加入 1 张上下文图片。"
                : "本次素材包没有可用的新闻原图，正文继续使用公司 IP 图。"}
          </span>
        </div>
        <div className={styles.mediaGrid} aria-label="新闻原图、公司 IP 图与封面画廊">
          {detail.media.map((media) => (
            <figure
              key={media.id}
              data-role={media.role}
              data-primary={
                media.id === detail.primaryBodyImageId ? "true" : undefined
              }
            >
              {media.url === null ? (
                <p>媒体地址不可用</p>
              ) : (
                <img
                  src={media.url}
                  alt={
                    media.altText ??
                    media.semanticLabel ??
                    `${media.roleLabel}预览`
                  }
                />
              )}
              <figcaption>
                <strong>
                  {media.roleLabel}
                  {media.id === detail.primaryBodyImageId ? " · 兼容主图" : ""}
                </strong>
                {media.semanticLabel !== null ? (
                  <span>
                    {media.semanticLabel}
                    {media.assignedSectionIndex === null
                      ? ""
                      : ` · 第 ${media.assignedSectionIndex + 1} 节`}
                  </span>
                ) : null}
                {media.selectionMethodLabel !== null ? (
                  <span>
                    {media.selectionMethodLabel}
                    {media.similarityBandLabel === null
                      ? ""
                      : ` · ${media.similarityBandLabel}`}
                  </span>
                ) : null}
                {media.caption !== null ? <span>{media.caption}</span> : null}
                {media.credit !== null ? <small>图片署名：{media.credit}</small> : null}
                {media.role === "context" ? (
                  <strong className={styles.rightsWarning} role="note">
                    发布权限未验证 · 仅作上下文参考，不是事实证据
                  </strong>
                ) : null}
                {media.sourcePageUrl !== null ? (
                  <a
                    href={media.sourcePageUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    referrerPolicy="no-referrer"
                  >
                    查看新闻原文（新窗口）
                  </a>
                ) : null}
                <code>{media.id}</code>
                <small>SHA {media.sha256.slice(0, 12)}</small>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
      <div className={styles.previewFrame}>
        <div>
          <span>MOBILE / SANDBOX</span>
          <strong>本地模拟，未同步公众号</strong>
          <code>{detail.draft?.id ?? "等待草稿"}</code>
        </div>
        {detail.draft?.previewUrl === null || detail.draft === null ? (
          <p>草稿就绪后显示移动宽度 HTML 预览。</p>
        ) : (
          <iframe
            title="公众号本地模拟草稿预览"
            src={detail.draft.previewUrl}
            sandbox=""
            referrerPolicy="no-referrer"
          />
        )}
      </div>
    </section>
  );
}
