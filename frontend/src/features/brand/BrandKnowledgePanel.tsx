import { type FormEvent, useState } from "react";

import type { BrandDocumentKind } from "./api";
import {
  useActivateBrandVersion,
  useBrandDocuments,
  useDeactivateBrandDocument,
  useRetrieveBrandContext,
  useUploadBrandDocument,
} from "./hooks";
import styles from "./BrandKnowledgePanel.module.css";

const kindOptions: readonly Readonly<{
  value: BrandDocumentKind;
  label: string;
}>[] = [
  { value: "positioning", label: "品牌定位" },
  { value: "tone", label: "表达语气" },
  { value: "approved_example", label: "优秀示例" },
  { value: "prohibited_language", label: "禁用表达" },
  { value: "safety_rule", label: "安全规则" },
  { value: "visual_guidance", label: "视觉规范" },
  { value: "other", label: "其他" },
] as const;

export function BrandKnowledgePanel() {
  const documents = useBrandDocuments();
  const upload = useUploadBrandDocument();
  const activate = useActivateBrandVersion();
  const deactivate = useDeactivateBrandDocument();
  const retrieval = useRetrieveBrandContext();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [documentKind, setDocumentKind] = useState<BrandDocumentKind>("tone");
  const [toneTags, setToneTags] = useState("准确, 克制, 温暖");
  const [safetyTags, setSafetyTags] = useState("不制造焦虑, 不作效果承诺");
  const [query, setQuery] = useState(
    "面向家长介绍人工智能时，如何保持准确和克制？",
  );

  function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (file === null || title.trim().length === 0) return;
    upload.mutate({
      file,
      title: title.trim(),
      documentKind,
      toneTags,
      safetyTags,
    });
  }

  function handleRetrieval(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (query.trim().length === 0) return;
    retrieval.mutate(query.trim());
  }

  const announcement = upload.isSuccess
    ? `已进入处理队列：${upload.data.ingestion_job_id}`
    : upload.isError
      ? "上传失败，请检查服务状态与文件格式。"
      : activate.isSuccess
        ? "品牌版本已激活。"
        : deactivate.isSuccess
          ? "品牌文档已停用。"
          : "";

  return (
    <section
      className={styles.workspace}
      aria-labelledby="brand-workspace-title"
    >
      <div className={styles.sectionHeader}>
        <div>
          <p>PRIVATE CORPUS / BRAND ONLY</p>
          <h2 id="brand-workspace-title">品牌知识装载台</h2>
        </div>
        <span>不会作为外部事实证据</span>
      </div>

      <div className={styles.railGrid}>
        <form
          className={styles.uploadRail}
          aria-label="上传品牌资料"
          onSubmit={handleUpload}
        >
          <div className={styles.railMarker} aria-hidden="true">
            01 / INGEST
          </div>
          <label>
            <span>文档标题</span>
            <input
              required
              maxLength={200}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="例如：赛先生家长沟通规范"
            />
          </label>
          <label>
            <span>资料类型</span>
            <select
              value={documentKind}
              onChange={(event) => {
                if (isBrandDocumentKind(event.target.value)) {
                  setDocumentKind(event.target.value);
                }
              }}
            >
              {kindOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>语气标签</span>
            <input
              value={toneTags}
              onChange={(event) => setToneTags(event.target.value)}
            />
          </label>
          <label>
            <span>安全标签</span>
            <input
              value={safetyTags}
              onChange={(event) => setSafetyTags(event.target.value)}
            />
          </label>
          <label className={styles.fileField}>
            <span>原始文件</span>
            <input
              required
              type="file"
              accept=".pdf,.docx,.txt,.md,.markdown"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <small>PDF / DOCX / UTF-8 TXT / Markdown · 最大 25 MiB</small>
          </label>
          <button type="submit" disabled={upload.isPending || file === null}>
            {upload.isPending ? "正在装载…" : "上传并建立新版本"}
          </button>
          <p className={styles.manualNote}>
            原件写入私有对象存储，解析和向量化由内容 Worker 异步完成。
          </p>
        </form>

        <div className={styles.statusRail}>
          <div className={styles.railMarker} aria-hidden="true">
            02 / STATUS
          </div>
          {documents.isPending ? (
            <p role="status">正在读取品牌资料状态…</p>
          ) : documents.isError ? (
            <p role="alert">
              暂时无法读取品牌资料，请确认 API 与数据库已启动。
            </p>
          ) : documents.data.items.length === 0 ? (
            <div className={styles.emptyState}>
              <strong>等待第一份品牌资料</strong>
              <p>上传后，这里会显示版本、处理状态、切块数量和激活状态。</p>
            </div>
          ) : (
            <div className={styles.documentList}>
              {documents.data.items.map((document) => {
                const latest = document.versions[0];
                return (
                  <article className={styles.documentRow} key={document.id}>
                    <div className={styles.documentMeta}>
                      <span>{document.document_kind.toUpperCase()}</span>
                      <span>
                        {document.status === "active" ? "ACTIVE" : "STANDBY"}
                      </span>
                    </div>
                    <h3>{document.title}</h3>
                    {latest === undefined ? null : (
                      <dl>
                        <div>
                          <dt>VERSION</dt>
                          <dd>V{latest.version}</dd>
                        </div>
                        <div>
                          <dt>JOB</dt>
                          <dd>
                            {latest.ingestion_job_status ?? latest.status}
                          </dd>
                        </div>
                        <div>
                          <dt>CHUNKS</dt>
                          <dd>{latest.chunk_count}</dd>
                        </div>
                      </dl>
                    )}
                    <div className={styles.rowActions}>
                      {latest?.status === "ready" && !latest.active ? (
                        <button
                          type="button"
                          disabled={activate.isPending}
                          onClick={() =>
                            activate.mutate({
                              documentId: document.id,
                              versionId: latest.id,
                            })
                          }
                        >
                          激活此版本
                        </button>
                      ) : null}
                      {document.status === "active" ? (
                        <button
                          type="button"
                          className={styles.quietButton}
                          disabled={deactivate.isPending}
                          onClick={() => deactivate.mutate(document.id)}
                        >
                          停用
                        </button>
                      ) : null}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <form className={styles.retrievalPanel} onSubmit={handleRetrieval}>
        <div>
          <p>03 / GENERATION CONTEXT DEBUG</p>
          <h3>文案上下文召回测试</h3>
          <span>
            仅供内部调试朋友圈文案生成会使用的品牌规则，不是面向家长的检索服务。
          </span>
        </div>
        <label>
          <span className={styles.visuallyHidden}>选题或文案生成意图</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <button type="submit" disabled={retrieval.isPending}>
          {retrieval.isPending ? "召回中…" : "测试生成上下文"}
        </button>
        {retrieval.isSuccess ? (
          <ol className={styles.results}>
            {retrieval.data.items.map((item) => (
              <li key={item.chunk_id}>
                <span>
                  {item.document_title} / {item.fused_score.toFixed(4)}
                </span>
                <p>{item.text}</p>
              </li>
            ))}
          </ol>
        ) : null}
        {retrieval.isError ? (
          <p role="alert">上下文召回失败或当前没有可用模型。</p>
        ) : null}
      </form>

      <p className={styles.liveRegion} role="status" aria-live="polite">
        {announcement}
      </p>
    </section>
  );
}

function isBrandDocumentKind(value: string): value is BrandDocumentKind {
  return kindOptions.some((option) => option.value === value);
}
