import type {
  AuditViewModel,
  BrandBindingViewModel,
  EvidenceViewModel,
  ImageViewModel,
  MaterialIssueViewModel,
  MaterialPackageViewModel,
  TopicViewModel,
  ValidationViewModel,
} from "./api";
import styles from "./MaterialPackagePanel.module.css";

export type MaterialPackageDetailProps = Readonly<{
  materialPackage: MaterialPackageViewModel;
  note: string;
  onNoteChange: (value: string) => void;
  onCopy: (text: string) => Promise<void>;
  onDownloadImage: () => void;
  onDownloadPackage: () => Promise<void>;
  onReview: (decision: "approved" | "rejected") => void;
  reviewPending: boolean;
  feedback: string;
  onClose: () => void;
}>;

export function MaterialPackageDetail({
  materialPackage,
  note,
  onNoteChange,
  onCopy,
  onDownloadImage,
  onDownloadPackage,
  onReview,
  reviewPending,
  feedback,
  onClose,
}: MaterialPackageDetailProps) {
  const imageReady =
    materialPackage.image.status === "succeeded" &&
    materialPackage.image.downloadUrl !== null;
  const canReview =
    imageReady &&
    ["ready", "awaiting_manual_use", "completed", "rejected"].includes(
      materialPackage.status,
    );

  return (
    <article className={styles.detail} aria-labelledby="material-detail-title">
      <div className={styles.detailHeader}>
        <div>
          <p>
            PACKAGE V{materialPackage.packageVersion} /{" "}
            {materialPackage.businessDate}
          </p>
          <h3 id="material-detail-title">{materialPackage.topic.title}</h3>
          <p className={styles.detailSubline}>
            生成于 {materialPackage.createdAtLabel} · 运行{" "}
            {materialPackage.copyGenerationRunId}
          </p>
        </div>
        <div className={styles.detailActions}>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => void onDownloadPackage()}
          >
            下载素材包
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onClose}
          >
            返回列表
          </button>
        </div>
      </div>

      <PackageStatusSection materialPackage={materialPackage} />

      {materialPackage.topic.decisionKind === "no_topic" ? (
        <p className={styles.stateNoTopic} role="status">
          今日没有达到门槛的选题，未生成可用素材。
        </p>
      ) : null}
      {materialPackage.status === "failed" ||
      materialPackage.image.status === "failed" ? (
        <p className={styles.stateFailed} role="alert">
          素材包或图片生成失败：
          {materialPackage.image.errorCode ?? "请检查验证与审计结果"}
        </p>
      ) : null}
      {materialPackage.image.status === "review_required" ? (
        <p className={styles.stateFailed} role="alert">
          图片需要人工复核后才能继续使用。
        </p>
      ) : null}
      {materialPackage.image.status !== "succeeded" &&
      materialPackage.status !== "failed" &&
      materialPackage.image.status !== "failed" &&
      materialPackage.image.status !== "review_required" ? (
        <p className={styles.status} role="status">
          图片正在生成，请稍候；页面会自动更新。
        </p>
      ) : null}

      <TopicSummary topic={materialPackage.topic} />
      <CopywritingSection copy={materialPackage.copy} onCopy={onCopy} />
      <ImageSection
        image={materialPackage.image}
        title={materialPackage.topic.title}
        onDownload={onDownloadImage}
      />
      <EvidenceList evidence={materialPackage.evidence} />
      <BrandBindingList bindings={materialPackage.brandBindings} />
      <QualitySection
        validation={materialPackage.validation}
        audit={materialPackage.audit}
      />

      {canReview ? (
        <ReviewSection
          note={note}
          onNoteChange={onNoteChange}
          onReview={onReview}
          reviewPending={reviewPending}
          reviewStatus={materialPackage.review}
        />
      ) : null}
      {materialPackage.review.note && !canReview ? (
        <section
          className={styles.detailSection}
          aria-labelledby="review-note-title"
        >
          <h4 id="review-note-title">审核记录</h4>
          <p>{materialPackage.review.note}</p>
        </section>
      ) : null}
      <p className={styles.status} role="status" aria-live="polite">
        {feedback}
      </p>
    </article>
  );
}

function PackageStatusSection({
  materialPackage,
}: Readonly<{ materialPackage: MaterialPackageViewModel }>) {
  return (
    <section
      className={styles.statusSection}
      aria-labelledby="package-status-title"
    >
      <div className={styles.sectionTitle}>
        <h4 id="package-status-title">当前状态</h4>
        <span className={styles.statusBadge}>
          {materialPackage.statusLabel}
        </span>
      </div>
      <dl className={styles.statusGrid}>
        <div>
          <dt>素材包</dt>
          <dd>{materialPackage.statusLabel}</dd>
        </div>
        <div>
          <dt>图片</dt>
          <dd>{materialPackage.image.statusLabel}</dd>
        </div>
        <div>
          <dt>人工审核</dt>
          <dd>{materialPackage.reviewStatusLabel}</dd>
        </div>
        <div>
          <dt>版本</dt>
          <dd>V{materialPackage.packageVersion}</dd>
        </div>
      </dl>
    </section>
  );
}

function TopicSummary({ topic }: Readonly<{ topic: TopicViewModel }>) {
  return (
    <section className={styles.detailSection} aria-labelledby="topic-title">
      <div className={styles.sectionTitle}>
        <h4 id="topic-title">选题与解释</h4>
        <span className={styles.statusBadge}>{topic.decisionLabel}</span>
      </div>
      {topic.summary ? (
        <p className={styles.topicSummary}>{topic.summary}</p>
      ) : null}
      <p className={styles.explanation}>{topic.explanation}</p>
      <dl className={styles.metadataGrid}>
        <MetadataItem label="业务日期" value={topic.businessDate} />
        <MetadataItem label="分类" value={topic.category ?? "未提供"} />
        <MetadataItem
          label="来源可信度"
          value={topic.sourceTrust ?? "未提供"}
        />
        <MetadataItem label="选题得分" value={formatScore(topic.score)} />
        <MetadataItem label="时区" value={topic.timezone ?? "未提供"} />
      </dl>
      {topic.scoreBreakdown.length > 0 ? (
        <div className={styles.metricList}>
          <strong>得分解释</strong>
          <ul>
            {topic.scoreBreakdown.map((metric) => (
              <li key={`${metric.label}-${metric.value}`}>
                <span>{metric.label}</span>
                <span>{metric.value}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <dl className={styles.identifierGrid}>
        <MetadataItem
          label="选题事件 ID"
          value={topic.selectedEventId ?? "未提供"}
          code
        />
        <MetadataItem
          label="选题版本 ID"
          value={topic.selectedEventVersionId ?? "未提供"}
          code
        />
      </dl>
    </section>
  );
}

function CopywritingSection({
  copy,
  onCopy,
}: Readonly<{
  copy: MaterialPackageViewModel["copy"];
  onCopy: (text: string) => Promise<void>;
}>) {
  return (
    <section className={styles.detailSection} aria-labelledby="copy-title">
      <div className={styles.sectionTitle}>
        <h4 id="copy-title">文案</h4>
        <button
          className={styles.actionButton}
          type="button"
          disabled={copy.copywriting.length === 0}
          onClick={() => void onCopy(copy.copywriting)}
        >
          复制文案
        </button>
      </div>
      {copy.copywriting ? (
        <p className={styles.longCopy}>{copy.copywriting}</p>
      ) : (
        <p className={styles.emptyValue}>暂无可展示文案。</p>
      )}
      <dl className={styles.copyFields}>
        <MetadataItem
          label="给家长的带走点"
          value={copy.parentTakeaway || "未提供"}
        />
        <MetadataItem label="互动建议" value={copy.interaction || "未提供"} />
        <MetadataItem label="来源说明" value={copy.sourceNote || "未提供"} />
      </dl>
      {copy.claims.length > 0 ? (
        <div className={styles.claimList}>
          <strong>文案主张绑定</strong>
          <ul>
            {copy.claims.map((claim) => (
              <li key={claim.id}>
                <span>{claim.text}</span>
                <small>
                  {claim.kind} · 事实证据 {claim.evidenceIds.length} 条 ·
                  品牌绑定 {claim.brandChunkIds.length} 条
                </small>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function ImageSection({
  image,
  title,
  onDownload,
}: Readonly<{
  image: ImageViewModel;
  title: string;
  onDownload: () => void;
}>) {
  return (
    <section className={styles.detailSection} aria-labelledby="image-title">
      <div className={styles.sectionTitle}>
        <h4 id="image-title">图片</h4>
        <span className={styles.statusBadge}>{image.statusLabel}</span>
      </div>
      {image.status === "succeeded" && image.downloadUrl ? (
        <>
          <img
            className={styles.detailImage}
            src={image.downloadUrl}
            alt={`${title}的赛先生科学探索插画`}
          />
          <a
            className={styles.download}
            href={image.downloadUrl}
            download
            onClick={onDownload}
          >
            下载图片（内部审核后手动使用）
          </a>
        </>
      ) : (
        <p className={styles.emptyValue}>
          {image.errorCode
            ? `图片暂不可用：${image.errorCode}`
            : "图片尚未就绪，详情会随任务状态更新。"}
        </p>
      )}
      <dl className={styles.metadataGrid}>
        <MetadataItem label="图片提供方" value={image.provider} />
        <MetadataItem label="图片模型" value={image.model} />
        <MetadataItem
          label="尺寸"
          value={formatDimensions(image.width, image.height)}
        />
        <MetadataItem label="媒体类型" value={image.mediaType ?? "未提供"} />
      </dl>
      <ImageRecoverySummary fallback={image.fallback} />
      <ImageQualitySummary image={image} />
      <VisualIntent image={image} />
    </section>
  );
}

function ImageRecoverySummary({
  fallback,
}: Readonly<{ fallback: ImageViewModel["fallback"] }>) {
  if (fallback.state === "not_used") return null;
  const label =
    fallback.state === "neutralized_retry"
      ? "供应商拒绝后已使用中性化提示词重试"
      : "供应商重试未完成，已使用匹配的品牌素材交付";
  return (
    <div className={styles.imageQuality} aria-labelledby="image-recovery-title">
      <div className={styles.visualIntentHeader}>
        <h5 id="image-recovery-title">图片恢复记录</h5>
        <span className={styles.evidenceMeta}>{label}</span>
      </div>
      {fallback.asset ? (
        <dl className={styles.metadataGrid}>
          <MetadataItem label="兜底素材" value={fallback.asset.filename} />
          <MetadataItem label="素材角色" value={fallback.asset.roleLabel} />
          <MetadataItem
            label="选择理由"
            value={fallback.asset.selectionReason}
          />
        </dl>
      ) : null}
    </div>
  );
}

function ImageQualitySummary({ image }: Readonly<{ image: ImageViewModel }>) {
  return (
    <div className={styles.imageQuality} aria-labelledby="image-quality-title">
      <div className={styles.visualIntentHeader}>
        <h5 id="image-quality-title">图片质量状态</h5>
        <span className={styles.evidenceMeta}>
          {image.repairCount === 0
            ? "未触发自动修复"
            : `已自动修复 ${image.repairCount} 次`}
        </span>
      </div>
      <dl className={styles.metadataGrid}>
        <MetadataItem
          label="确定性验证"
          value={imageValidationStatusLabel(image.validation.passed)}
        />
        <MetadataItem
          label="视觉审计"
          value={imageAuditStatusLabel(image.audit)}
        />
        <MetadataItem label="验证版本" value={image.validation.version} />
        <MetadataItem label="审计版本" value={image.audit.version} />
      </dl>
      {image.validation.issueCodes.length > 0 ? (
        <p className={styles.evidenceMeta}>
          验证问题：{image.validation.issueCodes.join("、")}
        </p>
      ) : null}
      {image.audit.issueCodes.length > 0 ? (
        <p className={styles.evidenceMeta}>
          审计问题：{image.audit.issueCodes.join("、")}
        </p>
      ) : null}
    </div>
  );
}

function VisualIntent({ image }: Readonly<{ image: ImageViewModel }>) {
  if (image.visualBrief === null && image.references.length === 0) return null;
  return (
    <div className={styles.visualIntent}>
      <div className={styles.visualIntentHeader}>
        <h5>视觉 brief</h5>
        <span className={styles.evidenceMeta}>
          {formatReferenceMode(image.referenceMode)}
        </span>
      </div>
      {image.visualBrief ? (
        <>
          <dl className={styles.metadataGrid}>
            <MetadataItem label="视觉主题" value={image.visualBrief.category} />
            <MetadataItem
              label="学习目标"
              value={image.visualBrief.learningGoal}
            />
            <MetadataItem label="场景" value={image.visualBrief.scene} />
            <MetadataItem
              label="主要动作"
              value={image.visualBrief.mainAction}
            />
            <MetadataItem
              label="文字模式"
              value={formatRenderTextMode(image.visualBrief.renderTextMode)}
            />
          </dl>
          <p className={styles.evidenceMeta}>
            图片文字层：{image.visualBrief.textLayer.title} ·{" "}
            {image.visualBrief.textLayer.learningLine || "无学习提示"}
          </p>
          <p className={styles.evidenceMeta}>
            关键词：{image.visualBrief.textLayer.keywords.join("、") || "无"}
            {image.visualBrief.textLayer.brandValues.length > 0
              ? " · 品牌理念：" +
                image.visualBrief.textLayer.brandValues.join("、")
              : ""}
          </p>
        </>
      ) : null}
      {image.references.length > 0 ? (
        <>
          <h5>使用的品牌素材</h5>
          <ul className={styles.visualReferenceList}>
            {image.references.map((reference) => (
              <li key={reference.role + "-" + reference.assetId}>
                <div className={styles.evidenceHeader}>
                  <strong>{reference.filename}</strong>
                  <span className={styles.statusBadge}>
                    {reference.roleLabel}
                  </span>
                </div>
                <p className={styles.evidenceMeta}>
                  {reference.selectionReason}
                  {reference.fallback ? " · 已记录回退" : ""}
                </p>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

function EvidenceList({
  evidence,
}: Readonly<{ evidence: readonly EvidenceViewModel[] }>) {
  return (
    <section className={styles.detailSection} aria-labelledby="sources-title">
      <div className={styles.sectionTitle}>
        <h4 id="sources-title">来源与证据</h4>
        <span className={styles.countLabel}>{evidence.length} 条绑定</span>
      </div>
      {evidence.length === 0 ? (
        <p className={styles.emptyValue}>
          暂无来源绑定；没有绑定的内容不能作为外部事实依据。
        </p>
      ) : (
        <ul className={styles.evidenceList}>
          {evidence.map((item) => (
            <EvidenceItem key={item.id} evidence={item} />
          ))}
        </ul>
      )}
    </section>
  );
}

function EvidenceItem({ evidence }: Readonly<{ evidence: EvidenceViewModel }>) {
  return (
    <li className={styles.evidenceItem}>
      <div className={styles.evidenceHeader}>
        <strong>{evidence.label}</strong>
        {evidence.sourceUrl ? (
          <a href={evidence.sourceUrl} target="_blank" rel="noreferrer">
            打开原文
          </a>
        ) : (
          <span className={styles.mutedLabel}>原文链接不可用</span>
        )}
      </div>
      <p className={styles.evidenceMeta}>
        主张 {evidence.claimId ?? "未标识"} · 层级{" "}
        {evidence.sourceTier ?? "未提供"}
        {evidence.publishedAt ? ` · 发布于 ${evidence.publishedAt}` : ""}
      </p>
      {evidence.claimText ? <p>支持主张：{evidence.claimText}</p> : null}
      {evidence.exactQuote ? (
        <blockquote>{evidence.exactQuote}</blockquote>
      ) : null}
    </li>
  );
}

function BrandBindingList({
  bindings,
}: Readonly<{ bindings: readonly BrandBindingViewModel[] }>) {
  return (
    <section
      className={styles.detailSection}
      aria-labelledby="brand-binding-title"
    >
      <div className={styles.sectionTitle}>
        <h4 id="brand-binding-title">品牌绑定</h4>
        <span className={styles.countLabel}>{bindings.length} 条绑定</span>
      </div>
      <p className={styles.boundaryCopy}>
        品牌资料只约束表达、语气、安全和视觉方向，不能替代来源证据。
      </p>
      {bindings.length === 0 ? (
        <p className={styles.emptyValue}>
          该素材包没有返回可展示的品牌片段绑定。
        </p>
      ) : (
        <ul className={styles.bindingList}>
          {bindings.map((binding) => (
            <li key={binding.id}>
              <div className={styles.evidenceHeader}>
                <strong>{binding.documentTitle ?? "品牌知识片段"}</strong>
                <code>{binding.brandChunkId}</code>
              </div>
              <p className={styles.evidenceMeta}>
                主张 {binding.claimId ?? "素材包级"} · 受众{" "}
                {binding.audience ?? "未提供"}
              </p>
              {binding.text ? <p>{binding.text}</p> : null}
              {binding.toneTags.length > 0 || binding.safetyTags.length > 0 ? (
                <p className={styles.evidenceMeta}>
                  {binding.toneTags.length > 0
                    ? `语气：${binding.toneTags.join("、")}`
                    : ""}
                  {binding.safetyTags.length > 0
                    ? ` ${binding.toneTags.length > 0 ? "· " : ""}安全：${binding.safetyTags.join("、")}`
                    : ""}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function QualitySection({
  validation,
  audit,
}: Readonly<{
  validation: ValidationViewModel;
  audit: AuditViewModel;
}>) {
  return (
    <section className={styles.detailSection} aria-labelledby="audit-title">
      <div className={styles.sectionTitle}>
        <h4 id="audit-title">验证与审计</h4>
        <span className={styles.statusBadge}>{auditStatusLabel(audit)}</span>
      </div>
      <div className={styles.qualityGrid}>
        <QualityResult
          title="确定性验证"
          passed={validation.passed}
          ruleVersion={validation.ruleVersion}
          issues={validation.issues}
        />
        <QualityResult
          title="模型审计"
          passed={audit.accepted}
          ruleVersion={audit.ruleVersion}
          issues={audit.issues}
        />
      </div>
      {audit.diagnostic ? (
        <p className={styles.auditDiagnostic}>审计诊断：{audit.diagnostic}</p>
      ) : null}
      <dl className={styles.metadataGrid}>
        <MetadataItem label="审计 ID" value={audit.auditId ?? "未提供"} code />
        <MetadataItem
          label="提示版本"
          value={audit.promptVersion ?? "未提供"}
        />
        <MetadataItem
          label="Schema 版本"
          value={audit.schemaVersion ?? "未提供"}
        />
      </dl>
    </section>
  );
}

function QualityResult({
  title,
  passed,
  ruleVersion,
  issues,
}: Readonly<{
  title: string;
  passed: boolean | null;
  ruleVersion: string | null;
  issues: readonly MaterialIssueViewModel[];
}>) {
  return (
    <div className={styles.qualityResult}>
      <div className={styles.qualityHeading}>
        <strong>{title}</strong>
        <span>{qualityStatusLabel(passed)}</span>
      </div>
      <p className={styles.evidenceMeta}>规则版本：{ruleVersion ?? "未提供"}</p>
      <IssueList issues={issues} />
    </div>
  );
}

function IssueList({
  issues,
}: Readonly<{ issues: readonly MaterialIssueViewModel[] }>) {
  if (issues.length === 0) {
    return <p className={styles.emptyValue}>没有记录问题。</p>;
  }
  return (
    <ul className={styles.issueList}>
      {issues.map((issue) => (
        <li key={issue.id}>
          <span className={styles.issueSeverity}>
            {severityLabel(issue.severity)}
          </span>
          <span>{issue.message}</span>
          <small>
            {issue.code}
            {issue.field ? ` · 字段 ${issue.field}` : ""}
            {issue.claimId ? ` · 主张 ${issue.claimId}` : ""}
          </small>
        </li>
      ))}
    </ul>
  );
}

function ReviewSection({
  note,
  onNoteChange,
  onReview,
  reviewPending,
  reviewStatus,
}: Readonly<{
  note: string;
  onNoteChange: (value: string) => void;
  onReview: (decision: "approved" | "rejected") => void;
  reviewPending: boolean;
  reviewStatus: MaterialPackageViewModel["review"];
}>) {
  return (
    <section className={styles.detailSection} aria-labelledby="review-title">
      <div className={styles.sectionTitle}>
        <h4 id="review-title">人工审核</h4>
        <span className={styles.statusBadge}>{reviewStatus.statusLabel}</span>
      </div>
      {reviewStatus.note ? (
        <p className={styles.reviewNote}>上次备注：{reviewStatus.note}</p>
      ) : null}
      <label htmlFor="review-note">审核备注</label>
      <textarea
        id="review-note"
        value={note}
        onChange={(event) => onNoteChange(event.target.value)}
        maxLength={500}
      />
      <div className={styles.review}>
        <button
          className={styles.actionButton}
          type="button"
          disabled={reviewPending}
          onClick={() => onReview("approved")}
        >
          审核通过
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={reviewPending || note.trim().length === 0}
          onClick={() => onReview("rejected")}
        >
          驳回（需备注）
        </button>
      </div>
    </section>
  );
}

function MetadataItem({
  label,
  value,
  code = false,
}: Readonly<{
  label: string;
  value: string;
  code?: boolean;
}>) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className={code ? styles.codeValue : undefined}>{value}</dd>
    </div>
  );
}

function formatScore(score: number | null): string {
  if (score === null) return "未提供";
  return Number.isInteger(score) ? String(score) : score.toFixed(3);
}

function formatDimensions(width: number | null, height: number | null): string {
  return width !== null && height !== null ? `${width} × ${height}` : "未提供";
}

function formatReferenceMode(mode: ImageViewModel["referenceMode"]): string {
  return {
    legacy_single: "兼容单图",
    single_reference: "单个品牌素材",
    single_fallback: "供应商单图回退",
    budgeted_multi_reference: "预算内多图",
    multi_reference: "多图参考",
  }[mode];
}

function formatRenderTextMode(mode: string): string {
  return mode === "editorial_keywords_and_brand_values"
    ? "短标题、关键词和品牌理念"
    : mode;
}

function imageValidationStatusLabel(passed: boolean | null): string {
  return passed === true
    ? "确定性验证通过"
    : passed === false
      ? "确定性验证失败"
      : "确定性验证未完成";
}

function imageAuditStatusLabel(audit: ImageViewModel["audit"]): string {
  if (audit.status === "accepted") return "视觉审计通过";
  if (audit.status === "rejected") return "视觉审计未通过";
  if (audit.status === "not_applicable") return "视觉审计不适用";
  if (audit.status === "not_configured") return "视觉审计未配置";
  return "视觉审计未完成";
}

function qualityStatusLabel(passed: boolean | null): string {
  return passed === true ? "通过" : passed === false ? "未通过" : "未提供";
}

function auditStatusLabel(audit: AuditViewModel): string {
  return audit.status === "accepted"
    ? "审计通过"
    : audit.status === "rejected"
      ? "审计未通过"
      : audit.status === "pending"
        ? "审计中"
        : "审计状态未提供";
}

function severityLabel(severity: MaterialIssueViewModel["severity"]): string {
  return severity === "error"
    ? "错误"
    : severity === "warning"
      ? "警告"
      : "提示";
}
