import { useState, type ReactNode } from "react";

import { downloadJson } from "@/lib/download";

import {
  getPreviewManifestUrl,
  type PreviewBrandBindingViewModel,
  type PreviewCopyViewModel,
  type PreviewFindingViewModel,
  type PreviewImageViewModel,
  type PreviewManifestError,
  type PreviewManifestViewModel,
  type PreviewQualityViewModel,
  type PreviewSourceViewModel,
  type PreviewStageViewModel,
} from "./api";
import { usePreviewManifest } from "./hooks";
import styles from "./PreviewPanel.module.css";

export type PreviewPanelProps = Readonly<{
  manifestUrl?: string;
}>;

export function PreviewPanel({ manifestUrl }: PreviewPanelProps = {}) {
  const resolvedManifestUrl = manifestUrl ?? getPreviewManifestUrl();
  const preview = usePreviewManifest(resolvedManifestUrl);
  const [feedback, setFeedback] = useState("");

  async function copyCopywriting(text: string) {
    try {
      if (navigator.clipboard === undefined) {
        throw new Error("clipboard_unavailable");
      }
      await navigator.clipboard.writeText(text);
      setFeedback("文案已复制，可由内部人员手动使用。");
    } catch {
      setFeedback("复制失败，请检查浏览器剪贴板权限后重试。");
    }
  }

  function downloadImage(image: PreviewImageViewModel) {
    if (image.url === null) return;
    try {
      const link = document.createElement("a");
      link.href = image.url;
      link.download = image.filename;
      link.rel = "noreferrer";
      link.click();
      setFeedback("图片下载已开始，请按人工审核流程使用。");
    } catch {
      setFeedback("图片下载失败，请检查浏览器下载权限后重试。");
    }
  }

  function downloadPackage(packagePreview: PreviewManifestViewModel) {
    try {
      downloadJson(
        `preview-${safeFilenamePart(packagePreview.runId)}.json`,
        packagePreview.downloadPayload,
      );
      setFeedback("预览包清单已下载。");
    } catch {
      setFeedback("预览包下载失败，请稍后重试。");
    }
  }

  const frame = (children: ReactNode) => (
    <section className={styles.workspace} aria-labelledby="preview-title">
      <div className={styles.header}>
        <div>
          <p>REAL PREVIEW / MANIFEST</p>
          <h2 id="preview-title">真实预览</h2>
        </div>
        <span>仅供检查、复制与下载 · 不自动发布</span>
      </div>
      <p className={styles.feedback} aria-live="polite">
        {feedback}
      </p>
      {children}
    </section>
  );

  if (preview.isPending && preview.data === undefined) {
    return frame(<LoadingState />);
  }

  if (preview.isError && preview.data === undefined) {
    return frame(
      <ErrorState
        error={preview.error}
        onRetry={() => void preview.refetch()}
      />,
    );
  }

  if (preview.data === undefined) {
    return frame(<EmptyState />);
  }

  const packagePreview = preview.data;
  if (packagePreview.status === "empty") {
    return frame(
      <EmptyState onDownloadPackage={() => downloadPackage(packagePreview)} />,
    );
  }
  if (packagePreview.status === "loading") {
    return frame(<ManifestLoadingState preview={packagePreview} />);
  }
  if (packagePreview.status === "no_topic") {
    return frame(
      <NoTopicState
        preview={packagePreview}
        onDownloadPackage={() => downloadPackage(packagePreview)}
      />,
    );
  }
  if (
    packagePreview.status === "failed" ||
    packagePreview.status === "cancelled" ||
    packagePreview.status === "unknown"
  ) {
    return frame(
      <TerminalState
        preview={packagePreview}
        onDownloadPackage={() => downloadPackage(packagePreview)}
      />,
    );
  }

  return frame(
    <PreviewContent
      preview={packagePreview}
      onCopy={copyCopywriting}
      onDownloadImage={downloadImage}
      onDownloadPackage={downloadPackage}
    />,
  );
}

function LoadingState() {
  return (
    <div className={styles.state} role="status" aria-live="polite">
      <p className={styles.stateCode}>MANIFEST / LOADING</p>
      <h3>正在读取本地真实预览</h3>
      <p>预览页面会等待脱敏 manifest 完成读取，不会把中间日志当成结果。</p>
    </div>
  );
}

function EmptyState({
  onDownloadPackage,
}: Readonly<{
  onDownloadPackage?: () => void;
}>) {
  return (
    <div className={styles.state} role="status">
      <p className={styles.stateCode}>MANIFEST / EMPTY</p>
      <h3>还没有可展示的真实预览</h3>
      <p>请先运行本地真实链路；页面只读取已导出的脱敏 preview manifest。</p>
      {onDownloadPackage ? (
        <button type="button" onClick={onDownloadPackage}>
          下载当前预览包
        </button>
      ) : null}
    </div>
  );
}

function ManifestLoadingState({
  preview,
}: Readonly<{ preview: PreviewManifestViewModel }>) {
  return (
    <div className={styles.terminalWorkspace}>
      <div className={styles.state} role="status" aria-live="polite">
        <p className={styles.stateCode}>RUN / LOADING</p>
        <h3>真实链路仍在处理中</h3>
        <p>
          manifest
          已生成阶段快照，但后续阶段尚未完成；页面不会把中间结果解释为可用素材。
        </p>
        <p className={styles.errorCode}>运行 ID：{preview.runId}</p>
      </div>
      <StageTimeline stages={preview.stages} />
      {preview.sources.length > 0 ? (
        <SourcesSection sources={preview.sources} />
      ) : null}
    </div>
  );
}

function ErrorState({
  error,
  onRetry,
}: Readonly<{
  error: Error;
  onRetry: () => void;
}>) {
  const errorCode = isPreviewManifestError(error)
    ? error.code
    : "network_error";
  const message =
    errorCode === "not_found"
      ? "本地还没有导出的 manifest。"
      : errorCode === "invalid_manifest"
        ? "manifest 格式或资源地址未通过安全校验。"
        : "manifest 暂时无法读取，请检查本地预览资源。";
  return (
    <div className={styles.state} role="alert">
      <p className={styles.stateCode}>MANIFEST / ERROR</p>
      <h3>真实预览暂时不可用</h3>
      <p>{message}</p>
      <p className={styles.errorCode}>安全错误码：{errorCode}</p>
      <button type="button" onClick={onRetry}>
        重新读取预览
      </button>
    </div>
  );
}

function NoTopicState({
  preview,
  onDownloadPackage,
}: Readonly<{
  preview: PreviewManifestViewModel;
  onDownloadPackage: () => void;
}>) {
  return (
    <div className={styles.terminalWorkspace}>
      <TerminalBanner preview={preview} />
      <div className={styles.terminalGrid}>
        <TopicSection topic={preview.topic} />
        <StageTimeline stages={preview.stages} />
      </div>
      <SourcesSection sources={preview.sources} />
      <div className={styles.actionRow}>
        <button type="button" onClick={onDownloadPackage}>
          下载预览包
        </button>
      </div>
    </div>
  );
}

function TerminalState({
  preview,
  onDownloadPackage,
}: Readonly<{
  preview: PreviewManifestViewModel;
  onDownloadPackage: () => void;
}>) {
  return (
    <div className={styles.terminalWorkspace}>
      <TerminalBanner preview={preview} />
      <div className={styles.terminalGrid}>
        <TopicSection topic={preview.topic} />
        <StageTimeline stages={preview.stages} />
      </div>
      {preview.findings.length > 0 ? (
        <FindingsSection findings={preview.findings} />
      ) : null}
      <div className={styles.actionRow}>
        <button type="button" onClick={onDownloadPackage}>
          下载预览包
        </button>
      </div>
    </div>
  );
}

function TerminalBanner({
  preview,
}: Readonly<{ preview: PreviewManifestViewModel }>) {
  return (
    <div
      className={styles.terminalBanner}
      data-status={preview.status}
      role={preview.status === "failed" ? "alert" : "status"}
    >
      <div>
        <p className={styles.stateCode}>RUN / {preview.status.toUpperCase()}</p>
        <h3>{preview.statusLabel}</h3>
      </div>
      <div>
        <p>{terminalMessage(preview)}</p>
        {preview.errorCode ? (
          <p className={styles.errorCode}>安全错误码：{preview.errorCode}</p>
        ) : null}
        {preview.errorMessage ? <p>{preview.errorMessage}</p> : null}
      </div>
    </div>
  );
}

function PreviewContent({
  preview,
  onCopy,
  onDownloadImage,
  onDownloadPackage,
}: Readonly<{
  preview: PreviewManifestViewModel;
  onCopy: (text: string) => Promise<void>;
  onDownloadImage: (image: PreviewImageViewModel) => void;
  onDownloadPackage: (preview: PreviewManifestViewModel) => void;
}>) {
  return (
    <div className={styles.previewWorkspace}>
      {preview.status === "review_required" ? (
        <TerminalBanner preview={preview} />
      ) : null}
      <div className={styles.runHeader}>
        <div>
          <p className={styles.stateCode}>RUN / {preview.runId}</p>
          <p className={styles.runMeta}>
            {preview.businessDate ?? "业务日期未记录"} · 生成于{" "}
            {preview.generatedAtLabel}
          </p>
        </div>
        <div className={styles.actionRow}>
          <button type="button" onClick={() => onDownloadPackage(preview)}>
            下载预览包
          </button>
        </div>
      </div>
      <StageTimeline stages={preview.stages} />
      <div className={styles.contentGrid}>
        <div className={styles.contentColumn}>
          <TopicSection topic={preview.topic} />
          <CopySection copy={preview.copy} onCopy={onCopy} />
          <SourcesSection sources={preview.sources} />
        </div>
        <div className={styles.contentColumn}>
          <ImageSection image={preview.image} onDownload={onDownloadImage} />
          <BrandBindingsSection bindings={preview.brandBindings} />
          <QualitySection
            copyValidation={preview.validation}
            copyAudit={preview.audit}
            validation={preview.image.validation}
            audit={preview.image.audit}
          />
        </div>
      </div>
      <FindingsSection findings={preview.findings} />
    </div>
  );
}

function StageTimeline({
  stages,
}: Readonly<{ stages: readonly PreviewStageViewModel[] }>) {
  return (
    <section className={styles.section} aria-labelledby="preview-stages-title">
      <div className={styles.sectionTitle}>
        <div>
          <p className={styles.sectionCode}>PIPELINE / DURABLE STATUS</p>
          <h3 id="preview-stages-title">阶段状态</h3>
        </div>
        <span className={styles.mutedLabel}>每一段均来自 manifest 快照</span>
      </div>
      <ol className={styles.stageList} aria-label="真实预览阶段">
        {stages.map((stage, index) => (
          <li
            className={styles.stageItem}
            data-status={stage.status}
            key={stage.id}
          >
            <span className={styles.stageMarker} aria-hidden="true">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div className={styles.stageBody}>
              <div className={styles.stageHeading}>
                <h4>{stage.label}</h4>
                <StatusBadge label={stage.statusLabel} status={stage.status} />
              </div>
              <div className={styles.stageMeta}>
                <span>
                  {stage.startedAtLabel} → {stage.finishedAtLabel}
                </span>
                {stage.version ? <span>版本 {stage.version}</span> : null}
                {stage.runId ? <code>{stage.runId}</code> : null}
              </div>
              {stage.errorCode || stage.errorMessage ? (
                <p className={styles.inlineIssue}>
                  {stage.errorCode ? `错误码 ${stage.errorCode}` : "阶段问题"}
                  {stage.errorMessage ? `：${stage.errorMessage}` : ""}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function TopicSection({
  topic,
}: Readonly<{ topic: PreviewManifestViewModel["topic"] }>) {
  return (
    <section className={styles.section} aria-labelledby="preview-topic-title">
      <div className={styles.sectionTitle}>
        <div>
          <p className={styles.sectionCode}>SELECTION / TOP 1</p>
          <h3 id="preview-topic-title">选题与解释</h3>
        </div>
        <StatusBadge label={topic.decisionLabel} status={topic.decision} />
      </div>
      <h4 className={styles.topicTitle}>{topic.title}</h4>
      {topic.summary ? (
        <p className={styles.topicSummary}>{topic.summary}</p>
      ) : null}
      <p className={styles.explanation}>{topic.explanation}</p>
      <dl className={styles.metadataGrid}>
        <MetadataItem label="内容类别" value={topic.category ?? "未提供"} />
        <MetadataItem
          label="来源可信度"
          value={topic.sourceTrust ?? "未提供"}
        />
        <MetadataItem label="选择分数" value={topic.scoreLabel} />
      </dl>
    </section>
  );
}

function CopySection({
  copy,
  onCopy,
}: Readonly<{
  copy: PreviewCopyViewModel;
  onCopy: (text: string) => Promise<void>;
}>) {
  return (
    <section className={styles.section} aria-labelledby="preview-copy-title">
      <div className={styles.sectionTitle}>
        <div>
          <p className={styles.sectionCode}>COPY / MOMENTS</p>
          <h3 id="preview-copy-title">完整朋友圈文案</h3>
        </div>
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={copy.copywriting.length === 0}
          onClick={() => void onCopy(copy.copywriting)}
        >
          复制文案
        </button>
      </div>
      {copy.copywriting ? (
        <p className={styles.copyText}>{copy.copywriting}</p>
      ) : (
        <p className={styles.emptyValue}>没有返回可复制的朋友圈文案。</p>
      )}
      <div className={styles.tagBlock}>
        <strong>标签</strong>
        {copy.hashtags.length > 0 ? (
          <ul className={styles.tagList} aria-label="朋友圈标签">
            {copy.hashtags.map((tag) => (
              <li key={tag}>{tag}</li>
            ))}
          </ul>
        ) : (
          <p className={styles.emptyValue}>未提供标签。</p>
        )}
      </div>
      <dl className={styles.metadataGrid}>
        <MetadataItem
          label="家长带走一句话"
          value={copy.parentTakeaway || "未提供"}
        />
        <MetadataItem label="互动建议" value={copy.interaction || "未提供"} />
        <MetadataItem label="来源说明" value={copy.sourceNote || "未提供"} />
      </dl>
    </section>
  );
}

function SourcesSection({
  sources,
}: Readonly<{ sources: readonly PreviewSourceViewModel[] }>) {
  return (
    <section className={styles.section} aria-labelledby="preview-sources-title">
      <div className={styles.sectionTitle}>
        <div>
          <p className={styles.sectionCode}>EVIDENCE / EDUCATION NEWS</p>
          <h3 id="preview-sources-title">教育部新闻与来源</h3>
        </div>
        <span className={styles.mutedLabel}>{sources.length} 条候选</span>
      </div>
      {sources.length === 0 ? (
        <p className={styles.emptyValue}>
          manifest 没有返回可展示的教育新闻候选。
        </p>
      ) : (
        <ol className={styles.sourceList}>
          {sources.map((source) => (
            <li className={styles.sourceItem} key={source.id}>
              <div className={styles.sourceHeading}>
                <strong>{source.title}</strong>
                {source.isSelected ? (
                  <span className={styles.selectedLabel}>TOP 1 来源</span>
                ) : null}
              </div>
              <p className={styles.sourceMeta}>
                {source.sourceName ?? "来源名称未记录"} ·{" "}
                {source.sourceTier ?? "层级未记录"} · {source.statusLabel}
              </p>
              {source.summary ? <p>{source.summary}</p> : null}
              <div className={styles.sourceFooter}>
                <span>发布于 {source.publishedAtLabel}</span>
                {source.url ? (
                  <a href={source.url} target="_blank" rel="noreferrer">
                    查看来源（新窗口）
                  </a>
                ) : (
                  <span>未返回安全链接</span>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ImageSection({
  image,
  onDownload,
}: Readonly<{
  image: PreviewImageViewModel;
  onDownload: (image: PreviewImageViewModel) => void;
}>) {
  return (
    <section className={styles.section} aria-labelledby="preview-image-title">
      <div className={styles.sectionTitle}>
        <div>
          <p className={styles.sectionCode}>VISUAL / BRAND IP</p>
          <h3 id="preview-image-title">品牌 IP 图片</h3>
        </div>
        <StatusBadge label={image.statusLabel} status={image.status} />
      </div>
      {image.url ? (
        <img className={styles.previewImage} src={image.url} alt={image.alt} />
      ) : (
        <div className={styles.imagePlaceholder} role="status">
          <strong>{image.statusLabel}</strong>
          <span>没有安全的图片资源地址可供展示。</span>
        </div>
      )}
      <div className={styles.imageActions}>
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={image.url === null}
          onClick={() => onDownload(image)}
        >
          下载图片
        </button>
      </div>
      <dl className={styles.metadataGrid}>
        <MetadataItem label="文件名" value={image.filename} />
        <MetadataItem
          label="尺寸"
          value={
            image.width !== null && image.height !== null
              ? `${image.width} × ${image.height}`
              : "未记录"
          }
        />
        <MetadataItem label="媒体类型" value={image.mediaType ?? "未记录"} />
      </dl>
    </section>
  );
}

function BrandBindingsSection({
  bindings,
}: Readonly<{ bindings: readonly PreviewBrandBindingViewModel[] }>) {
  return (
    <section className={styles.section} aria-labelledby="preview-brand-title">
      <div className={styles.sectionTitle}>
        <div>
          <p className={styles.sectionCode}>BRAND / VISUAL BINDING</p>
          <h3 id="preview-brand-title">品牌绑定</h3>
        </div>
        <span className={styles.mutedLabel}>{bindings.length} 条</span>
      </div>
      {bindings.length === 0 ? (
        <p className={styles.emptyValue}>没有返回可展示的品牌资料绑定。</p>
      ) : (
        <ul className={styles.bindingList}>
          {bindings.map((binding) => (
            <li key={binding.id}>
              <strong>{binding.title}</strong>
              {binding.role ? <span>{binding.role}</span> : null}
              {binding.reason ? <p>{binding.reason}</p> : null}
              {binding.tags.length > 0 ? (
                <div className={styles.bindingTags}>
                  {binding.tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function QualitySection({
  copyValidation,
  copyAudit,
  validation,
  audit,
}: Readonly<{
  copyValidation: PreviewQualityViewModel;
  copyAudit: PreviewQualityViewModel;
  validation: PreviewQualityViewModel;
  audit: PreviewQualityViewModel;
}>) {
  return (
    <section className={styles.section} aria-labelledby="preview-quality-title">
      <div className={styles.sectionTitle}>
        <div>
          <p className={styles.sectionCode}>QUALITY / GATE</p>
          <h3 id="preview-quality-title">验证与审计</h3>
        </div>
        <span className={styles.mutedLabel}>状态不以颜色单独表达</span>
      </div>
      <div className={styles.qualityGrid}>
        <QualityBlock label="文案验证" quality={copyValidation} />
        <QualityBlock label="文案审计" quality={copyAudit} />
        <QualityBlock label="图片验证" quality={validation} />
        <QualityBlock label="图片审计" quality={audit} />
      </div>
    </section>
  );
}

function QualityBlock({
  label,
  quality,
}: Readonly<{
  label: string;
  quality: PreviewQualityViewModel;
}>) {
  return (
    <div className={styles.qualityBlock} data-status={quality.status}>
      <div className={styles.qualityHeading}>
        <strong>{label}</strong>
        <StatusBadge label={quality.statusLabel} status={quality.status} />
      </div>
      <p>
        {quality.version ? `规则版本 ${quality.version}` : "未记录规则版本"}
      </p>
      {quality.issueCodes.length > 0 ? (
        <ul className={styles.issueCodeList}>
          {quality.issueCodes.map((code) => (
            <li key={code}>{code}</li>
          ))}
        </ul>
      ) : (
        <p>未返回问题代码。</p>
      )}
    </div>
  );
}

function FindingsSection({
  findings,
}: Readonly<{ findings: readonly PreviewFindingViewModel[] }>) {
  return (
    <section
      className={styles.section}
      aria-labelledby="preview-findings-title"
    >
      <div className={styles.sectionTitle}>
        <div>
          <p className={styles.sectionCode}>AUDIT / TRACE</p>
          <h3 id="preview-findings-title">验证与审计问题</h3>
        </div>
        <span className={styles.mutedLabel}>{findings.length} 条记录</span>
      </div>
      {findings.length === 0 ? (
        <p className={styles.emptyValue}>没有返回需展示的验证或审计问题。</p>
      ) : (
        <ul className={styles.findingList}>
          {findings.map((finding) => (
            <li key={finding.id} data-severity={finding.severity}>
              <div className={styles.findingHeading}>
                <strong>{finding.message}</strong>
                <StatusBadge
                  label={finding.severity}
                  status={finding.severity}
                />
              </div>
              <p>
                {finding.stage} · <code>{finding.code}</code>
                {finding.field ? ` · ${finding.field}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function StatusBadge({
  label,
  status,
}: Readonly<{
  label: string;
  status: string;
}>) {
  return (
    <span className={styles.statusBadge} data-status={status}>
      {label}
    </span>
  );
}

function MetadataItem({
  label,
  value,
}: Readonly<{
  label: string;
  value: string;
}>) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function terminalMessage(preview: PreviewManifestViewModel): string {
  if (preview.status === "no_topic") {
    return "采集和治理结果已保留，但今天没有达到 Top 1 门槛，因此没有生成可用文案或图片。";
  }
  if (preview.status === "cancelled") {
    return "本次预览已取消，未将未完成阶段解释为成功。";
  }
  if (preview.status === "failed") {
    return "链路在一个阶段终止；请根据阶段状态和安全错误码定位阻塞点。";
  }
  if (preview.status === "unknown") {
    return "manifest 没有给出可确认的终态；请先核对阶段快照和运行状态。";
  }
  return "文案或图片仍需人工复核，当前结果不等同于可发布状态。";
}

function isPreviewManifestError(error: Error): error is PreviewManifestError {
  return error.name === "PreviewManifestError";
}

function safeFilenamePart(value: string): string {
  const safe = value.replace(/[^a-zA-Z0-9._-]+/g, "-");
  return safe.length > 0 ? safe : "latest";
}
