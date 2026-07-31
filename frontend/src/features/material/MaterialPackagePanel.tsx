import { useState } from "react";

import {
  useGenerateMaterialPackage,
  useMaterialPackage,
  useMaterialPackages,
  useReviewMaterialPackage,
} from "./hooks";
import styles from "./MaterialPackagePanel.module.css";

type UnknownRecord = Readonly<Record<string, unknown>>;

export function MaterialPackagePanel() {
  const packages = useMaterialPackages();
  const generate = useGenerateMaterialPackage();
  const review = useReviewMaterialPackage();
  const [runId, setRunId] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [feedback, setFeedback] = useState("");
  const detail = useMaterialPackage(selectedId);

  async function copyCopywriting(text: string) {
    try {
      if (navigator.clipboard === undefined)
        throw new Error("clipboard_unavailable");
      await navigator.clipboard.writeText(text);
      setFeedback("朋友圈文案已复制，可由内部人员手动发布。");
    } catch {
      setFeedback("复制失败，请检查浏览器剪贴板权限后重试。");
    }
  }

  function submitReview(decision: "approved" | "rejected") {
    if (
      selectedId === null ||
      (decision === "rejected" && note.trim().length === 0)
    )
      return;
    review.mutate(
      { packageId: selectedId, decision, note: note.trim() },
      {
        onSuccess: () => {
          setFeedback(
            decision === "approved"
              ? "审核已通过。"
              : "审核已驳回。请按备注处理后重新生成。",
          );
        },
      },
    );
  }

  const detailView =
    selectedId === null ? null : (
      <PackageDetail
        detail={detail}
        note={note}
        onNoteChange={setNote}
        onCopy={copyCopywriting}
        onReview={submitReview}
        reviewPending={review.isPending}
        feedback={feedback}
        onClose={() => setSelectedId(null)}
      />
    );

  return (
    <section
      className={styles.workspace}
      aria-labelledby="material-package-title"
    >
      <div className={styles.header}>
        <div>
          <p>INTERNAL REVIEW / ONE IMAGE</p>
          <h2 id="material-package-title">素材包审核台</h2>
        </div>
        <span>仅供复制与下载 · 不自动发布</span>
      </div>
      <form
        className={styles.toolbar}
        onSubmit={(event) => {
          event.preventDefault();
          const id = runId.trim();
          if (id.length === 0) return;
          generate.mutate(id, {
            onSuccess: (created) => setSelectedId(created.id),
          });
        }}
      >
        <label htmlFor="copy-run-id">已通过审校的文案运行 ID</label>
        <input
          id="copy-run-id"
          value={runId}
          onChange={(event) => setRunId(event.target.value)}
          placeholder="粘贴 copy-generation run UUID"
        />
        <button
          type="submit"
          disabled={generate.isPending || runId.trim().length === 0}
        >
          {generate.isPending ? "已加入生成队列…" : "生成一张图片素材"}
        </button>
      </form>
      {generate.isError ? (
        <p className={styles.status} role="alert">
          图片任务未能加入队列，请检查运行是否已通过文案审校。
        </p>
      ) : null}
      {packages.isPending ? (
        <p className={styles.status} role="status">
          正在读取素材包…
        </p>
      ) : null}
      {packages.isError ? (
        <p className={styles.status} role="alert">
          素材包暂时不可用，请确认服务状态。
        </p>
      ) : null}
      {packages.data?.items.length === 0 ? (
        <p className={styles.status}>还没有可审核的素材包。</p>
      ) : null}
      <section className={styles.grid} aria-label="素材包列表">
        {packages.data?.items.map((item) => (
          <article className={styles.card} key={item.id}>
            <div>
              <div className={styles.meta}>
                <span>{item.business_date}</span>
                <span>
                  {item.status.toUpperCase()} /{" "}
                  {item.review_status.toUpperCase()}
                </span>
              </div>
              <h3>赛先生 · 每日朋友圈素材</h3>
              <p className={styles.copy}>
                生成状态、文案、来源、图片和人工审核都在详情中留痕。
              </p>
              <button type="button" onClick={() => setSelectedId(item.id)}>
                查看素材包详情
              </button>
            </div>
            <div className={styles.preview}>
              <span>打开详情查看图片</span>
            </div>
          </article>
        ))}
      </section>
      {detailView}
    </section>
  );
}

type PackageDetailProps = Readonly<{
  detail: ReturnType<typeof useMaterialPackage>;
  note: string;
  onNoteChange: (value: string) => void;
  onCopy: (text: string) => Promise<void>;
  onReview: (decision: "approved" | "rejected") => void;
  reviewPending: boolean;
  feedback: string;
  onClose: () => void;
}>;

function PackageDetail({
  detail,
  note,
  onNoteChange,
  onCopy,
  onReview,
  reviewPending,
  feedback,
  onClose,
}: PackageDetailProps) {
  if (detail.isPending)
    return (
      <p className={styles.status} role="status">
        正在读取素材包详情…
      </p>
    );
  if (detail.isError || detail.data === undefined) {
    return (
      <div className={styles.detail} role="alert">
        <p>素材包详情读取失败，请稍后重试。</p>
        <button type="button" onClick={onClose}>
          返回列表
        </button>
      </div>
    );
  }
  const materialPackage = detail.data;
  const topic = asRecord(materialPackage.topic);
  const copy = asRecord(materialPackage.copy);
  const audit = asRecord(materialPackage.audit);
  const title = readString(topic, "title") ?? "今日科学话题";
  const copywriting = readString(copy, "copywriting") ?? "";
  const takeaway = readString(copy, "parent_takeaway");
  const interaction = readString(copy, "interaction");
  const sources = materialPackage.sources.filter(isRecord);
  const imageReady = materialPackage.image.status === "succeeded";
  const noTopic = readString(topic, "decision_kind") === "no_topic";
  const failed =
    materialPackage.status === "failed" ||
    materialPackage.image.status === "failed";
  const reviewableFailure = materialPackage.image.status === "review_required";

  return (
    <article className={styles.detail} aria-labelledby="material-detail-title">
      <div className={styles.detailHeader}>
        <div>
          <p>
            PACKAGE V{materialPackage.package_version} /{" "}
            {materialPackage.business_date}
          </p>
          <h3 id="material-detail-title">{title}</h3>
        </div>
        <button type="button" onClick={onClose}>
          返回列表
        </button>
      </div>
      {noTopic ? (
        <p className={styles.stateNoTopic} role="status">
          今日没有达到门槛的选题，未生成素材。
        </p>
      ) : null}
      {failed ? (
        <p className={styles.stateFailed} role="alert">
          图片生成失败：{materialPackage.image.error_code ?? "请检查任务状态"}
        </p>
      ) : null}
      {reviewableFailure ? (
        <p className={styles.stateFailed} role="alert">
          图片需要人工复核后才能继续使用。
        </p>
      ) : null}
      {!noTopic && !failed && !reviewableFailure && !imageReady ? (
        <p className={styles.status} role="status">
          图片正在生成，请稍候；页面会自动更新。
        </p>
      ) : null}
      {copywriting.length > 0 ? (
        <section className={styles.detailSection} aria-labelledby="copy-title">
          <div className={styles.sectionTitle}>
            <h4 id="copy-title">朋友圈文案</h4>
            <button type="button" onClick={() => void onCopy(copywriting)}>
              复制文案
            </button>
          </div>
          <p className={styles.longCopy}>{copywriting}</p>
          {takeaway ? (
            <p>
              <strong>给家长的带走点：</strong>
              {takeaway}
            </p>
          ) : null}
          {interaction ? (
            <p>
              <strong>互动建议：</strong>
              {interaction}
            </p>
          ) : null}
        </section>
      ) : null}
      {imageReady && materialPackage.image.download_url ? (
        <section className={styles.detailSection} aria-labelledby="image-title">
          <h4 id="image-title">一张图片</h4>
          <img
            className={styles.detailImage}
            src={materialPackage.image.download_url}
            alt={`${title}的赛先生科学探索插画`}
          />
          <a
            className={styles.download}
            href={materialPackage.image.download_url}
            download
          >
            下载图片（内部审核后手动使用）
          </a>
        </section>
      ) : null}
      <section className={styles.detailSection} aria-labelledby="sources-title">
        <h4 id="sources-title">来源与证据</h4>
        {sources.length === 0 ? (
          <p>暂无来源绑定。</p>
        ) : (
          <ul className={styles.sources}>
            {sources.map((source, index) => (
              <SourceItem
                key={`${index}-${readString(source, "source_url") ?? "source"}`}
                source={source}
              />
            ))}
          </ul>
        )}
      </section>
      <section className={styles.detailSection} aria-labelledby="audit-title">
        <h4 id="audit-title">验证与审校</h4>
        <p>
          素材包：{materialPackage.status} · 图片：
          {materialPackage.image.status} · 审校：{materialPackage.review_status}
        </p>
        <p>审校版本：{readString(audit, "rule_version") ?? "已绑定"}</p>
      </section>
      {imageReady &&
      (materialPackage.review_status === "pending" ||
        materialPackage.review_status === "approved" ||
        materialPackage.review_status === "rejected") ? (
        <section
          className={styles.detailSection}
          aria-labelledby="review-title"
        >
          <h4 id="review-title">内部审核</h4>
          <label htmlFor="review-note">审核备注</label>
          <textarea
            id="review-note"
            value={note}
            onChange={(event) => onNoteChange(event.target.value)}
            maxLength={500}
          />
          <div className={styles.review}>
            <button
              type="button"
              disabled={reviewPending}
              onClick={() => onReview("approved")}
            >
              审核通过
            </button>
            <button
              type="button"
              disabled={reviewPending || note.trim().length === 0}
              onClick={() => onReview("rejected")}
            >
              驳回（需备注）
            </button>
          </div>
        </section>
      ) : null}
      <p className={styles.status} role="status" aria-live="polite">
        {feedback}
      </p>
    </article>
  );
}

function SourceItem({ source }: Readonly<{ source: UnknownRecord }>) {
  const url = readString(source, "source_url");
  const title =
    readString(source, "claim_text") ??
    readString(source, "exact_quote") ??
    "已绑定证据";
  return (
    <li>
      {url && isSafeHttpUrl(url) ? (
        <a href={url} target="_blank" rel="noreferrer">
          {title}（原文）
        </a>
      ) : (
        <span>{title}</span>
      )}
    </li>
  );
}

function asRecord(value: unknown): UnknownRecord {
  return isRecord(value) ? value : {};
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(value: UnknownRecord, key: string): string | null {
  const item = value[key];
  return typeof item === "string" && item.length > 0 ? item : null;
}

function isSafeHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}
