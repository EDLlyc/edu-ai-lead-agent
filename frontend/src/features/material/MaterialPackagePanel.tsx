import { useState } from "react";

import { downloadJson } from "@/lib/download";

import { MaterialPackageDetail } from "./MaterialPackageDetail";
import {
  downloadMaterialPackage,
  type MaterialPackageViewModel,
  type MaterialPackageSummaryViewModel,
} from "./api";
import {
  useGenerateMaterialPackage,
  useMaterialPackage,
  useMaterialPackages,
  useReviewMaterialPackage,
} from "./hooks";
import styles from "./MaterialPackagePanel.module.css";

export function MaterialPackagePanel() {
  const packages = useMaterialPackages();
  const generate = useGenerateMaterialPackage();
  const review = useReviewMaterialPackage();
  const [runId, setRunId] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [feedback, setFeedback] = useState("");
  const detail = useMaterialPackage(selectedId);

  function selectPackage(packageId: string) {
    setSelectedId(packageId);
    setNote("");
    setFeedback("");
  }

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

  function downloadImage() {
    setFeedback("图片下载已开始，请按人工审核流程使用。");
  }

  async function downloadPackage(materialPackage: MaterialPackageViewModel) {
    try {
      const packageDownload = await downloadMaterialPackage(materialPackage.id);
      downloadJson(
        `sai-xiansheng-material-package-${materialPackage.businessDate}.json`,
        packageDownload,
      );
      setFeedback("素材包清单已下载。");
    } catch {
      setFeedback("素材包下载失败，请稍后重试。");
    }
  }

  function submitReview(decision: "approved" | "rejected") {
    if (
      selectedId === null ||
      (decision === "rejected" && note.trim().length === 0)
    ) {
      return;
    }
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
        onError: () => setFeedback("审核操作失败，请检查服务状态后重试。"),
      },
    );
  }

  const detailView =
    selectedId === null ? null : (
      <PackageDetailState
        detail={detail}
        note={note}
        onNoteChange={setNote}
        onCopy={copyCopywriting}
        onDownloadImage={downloadImage}
        onDownloadPackage={downloadPackage}
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
            onSuccess: (created) => selectPackage(created.id),
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
          <PackageSummaryCard
            key={item.id}
            item={item}
            onSelect={() => selectPackage(item.id)}
          />
        ))}
      </section>
      {detailView}
    </section>
  );
}

function PackageSummaryCard({
  item,
  onSelect,
}: Readonly<{
  item: MaterialPackageSummaryViewModel;
  onSelect: () => void;
}>) {
  return (
    <article className={styles.card}>
      <div>
        <div className={styles.meta}>
          <span>{item.businessDate}</span>
          <span>
            {item.statusLabel} / {item.reviewStatusLabel}
          </span>
        </div>
        <h3>赛先生 · 每日朋友圈素材</h3>
        <p className={styles.copy}>
          生成状态、文案、来源、品牌绑定、验证审计和人工审核都在详情中留痕。
        </p>
        <p className={styles.cardMeta}>创建于 {item.createdAtLabel}</p>
        <button type="button" onClick={onSelect}>
          查看素材包详情
        </button>
      </div>
      <div className={styles.preview} aria-label="素材包状态摘要">
        <span>PACKAGE STATUS</span>
        <strong>{item.statusLabel}</strong>
        <span>REVIEW</span>
        <strong>{item.reviewStatusLabel}</strong>
      </div>
    </article>
  );
}

type PackageDetailStateProps = Readonly<{
  detail: ReturnType<typeof useMaterialPackage>;
  note: string;
  onNoteChange: (value: string) => void;
  onCopy: (text: string) => Promise<void>;
  onDownloadImage: () => void;
  onDownloadPackage: (
    materialPackage: MaterialPackageViewModel,
  ) => Promise<void>;
  onReview: (decision: "approved" | "rejected") => void;
  reviewPending: boolean;
  feedback: string;
  onClose: () => void;
}>;

function PackageDetailState({
  detail,
  note,
  onNoteChange,
  onCopy,
  onDownloadImage,
  onDownloadPackage,
  onReview,
  reviewPending,
  feedback,
  onClose,
}: PackageDetailStateProps) {
  if (detail.isPending && detail.data === undefined) {
    return (
      <p className={styles.status} role="status">
        正在读取素材包详情…
      </p>
    );
  }
  if (detail.isError && detail.data === undefined) {
    return (
      <div className={styles.detail} role="alert">
        <p>素材包详情读取失败，请稍后重试。</p>
        <button type="button" onClick={onClose}>
          返回列表
        </button>
      </div>
    );
  }
  if (detail.data === undefined) return null;
  const materialPackage = detail.data;

  return (
    <MaterialPackageDetail
      materialPackage={materialPackage}
      note={note}
      onNoteChange={onNoteChange}
      onCopy={onCopy}
      onDownloadImage={onDownloadImage}
      onDownloadPackage={() => onDownloadPackage(materialPackage)}
      onReview={onReview}
      reviewPending={reviewPending}
      feedback={feedback}
      onClose={onClose}
    />
  );
}
