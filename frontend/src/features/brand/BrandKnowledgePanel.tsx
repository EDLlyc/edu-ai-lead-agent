import { type FormEvent, useState } from "react";

import type { BrandDocumentKind, DigitalIpProfile } from "./api";
import {
  clearDigitalIpFeedback,
  createDigitalIpFeedback,
  feedbackReasons,
  loadDigitalIpFeedback,
  saveDigitalIpFeedback,
  type FeedbackDecision,
  type FeedbackReason,
} from "./feedback";
import {
  useActivateBrandVersion,
  useBrandDocuments,
  useDeactivateBrandDocument,
  useDigitalIpProfile,
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

const reasonLabels: Readonly<Record<FeedbackReason, string>> = {
  relevant: "规则相关",
  tone_match: "语气匹配",
  missing_rule: "缺少所需规则",
  irrelevant: "结果不相关",
  conflicting_rule: "规则存在冲突",
};

const channelLabels: Readonly<Record<string, string>> = {
  wechat_moments: "朋友圈文案",
  internal_copy_generation: "内部文案生成",
};

const scenarioLabels: Readonly<Record<string, string>> = {
  science_education: "科学教育",
  parent_communication: "家长沟通",
  brand_copy: "品牌文案",
};

export function BrandKnowledgePanel() {
  const profile = useDigitalIpProfile();
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
  const [feedbackDecision, setFeedbackDecision] =
    useState<FeedbackDecision>("accepted");
  const [feedbackReason, setFeedbackReason] =
    useState<FeedbackReason>("relevant");
  const [feedbackNote, setFeedbackNote] = useState("");
  const [feedbackItems, setFeedbackItems] = useState(() =>
    loadDigitalIpFeedback(),
  );
  const [feedbackStatus, setFeedbackStatus] = useState("");

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
    setFeedbackStatus("");
    retrieval.mutate(query.trim());
  }

  function handleFeedback() {
    if (!retrieval.isSuccess || profile.data === undefined) return;
    const record = createDigitalIpFeedback({
      query: retrieval.data.query,
      profileFingerprint: profile.data.profile_fingerprint,
      chunkIds: retrieval.data.items.map((item) => item.chunk_id),
      versionIds: retrieval.data.items.map((item) => item.version_id),
      decision: feedbackDecision,
      reason: feedbackReason,
      note: feedbackNote,
    });
    try {
      setFeedbackItems([...saveDigitalIpFeedback(record)]);
      setFeedbackNote("");
      setFeedbackStatus("反馈已保存在当前浏览器，不会自动修改品牌知识。");
    } catch {
      setFeedbackStatus("浏览器无法保存反馈，请检查本地存储设置。");
    }
  }

  function handleClearFeedback() {
    try {
      clearDigitalIpFeedback();
      setFeedbackItems([]);
      setFeedbackStatus("本地反馈记录已清除。");
    } catch {
      setFeedbackStatus("浏览器无法清除反馈，请检查本地存储设置。");
    }
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

      <section className={styles.profileShell} aria-label="数字 IP 人设与资产">
        {profile.isPending ? (
          <p role="status">正在聚合数字 IP 人设与资产元数据…</p>
        ) : profile.isError ? (
          <div className={styles.profileEmpty} role="alert">
            <strong>数字 IP 人设暂不可用</strong>
            <p>品牌文档工作台仍可使用；请确认只读 profile API 已启动。</p>
          </div>
        ) : (
          <DigitalIpProfileCard profile={profile.data} />
        )}
      </section>

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
          <div className={styles.retrievalOutput}>
            <div className={styles.evidenceBoundary} role="note">
              <strong>evidence_eligible = false</strong>
              <span>以下内容只能约束品牌表达，不能作为外部事实证据。</span>
            </div>
            {retrieval.data.items.length === 0 ? (
              <p className={styles.retrievalEmpty}>
                当前 active 版本没有召回匹配规则；系统不会编造品牌指导。
              </p>
            ) : (
              <ol className={styles.results}>
                {retrieval.data.items.map((item) => (
                  <li key={item.chunk_id}>
                    <div className={styles.resultHeader}>
                      <strong>{item.document_title}</strong>
                      <span>{kindLabel(item.document_kind)}</span>
                      <span>VERSION / {item.version_id.slice(0, 8)}</span>
                    </div>
                    <p>{item.text}</p>
                    <dl className={styles.scoreGrid}>
                      <div>
                        <dt>FUSED</dt>
                        <dd>{item.fused_score.toFixed(4)}</dd>
                      </div>
                      <div>
                        <dt>FULL TEXT</dt>
                        <dd>{item.full_text_score.toFixed(4)}</dd>
                      </div>
                      <div>
                        <dt>VECTOR</dt>
                        <dd>{item.vector_score.toFixed(4)}</dd>
                      </div>
                    </dl>
                    <TagGroup label="语气" tags={item.tone_tags} />
                    <TagGroup label="安全" tags={item.safety_tags} />
                    <TagGroup label="视觉" tags={item.visual_tags} />
                  </li>
                ))}
              </ol>
            )}
            <div className={styles.feedbackPanel} aria-label="记录本地召回反馈">
              <div>
                <p>04 / BROWSER-LOCAL FEEDBACK</p>
                <h4>人工采纳记录</h4>
                <span>
                  只保存查询指纹与版本 ID；不会自动学习、激活资料或触发发布。
                </span>
              </div>
              <fieldset>
                <legend>反馈结论</legend>
                <label>
                  <input
                    type="radio"
                    name="feedback-decision"
                    value="accepted"
                    checked={feedbackDecision === "accepted"}
                    onChange={() => setFeedbackDecision("accepted")}
                  />
                  采纳
                </label>
                <label>
                  <input
                    type="radio"
                    name="feedback-decision"
                    value="rejected"
                    checked={feedbackDecision === "rejected"}
                    onChange={() => setFeedbackDecision("rejected")}
                  />
                  不采纳
                </label>
              </fieldset>
              <label>
                <span>受控原因</span>
                <select
                  value={feedbackReason}
                  onChange={(event) => {
                    if (isFeedbackReason(event.target.value)) {
                      setFeedbackReason(event.target.value);
                    }
                  }}
                >
                  {feedbackReasons.map((reason) => (
                    <option key={reason} value={reason}>
                      {reasonLabels[reason]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>短备注（可选，最多 160 字）</span>
                <textarea
                  maxLength={160}
                  value={feedbackNote}
                  onChange={(event) => setFeedbackNote(event.target.value)}
                />
              </label>
              <div className={styles.feedbackActions}>
                <button
                  type="button"
                  disabled={profile.data === undefined}
                  onClick={handleFeedback}
                >
                  保存本地反馈
                </button>
                <button
                  type="button"
                  className={styles.quietButton}
                  disabled={feedbackItems.length === 0}
                  onClick={handleClearFeedback}
                >
                  清除本地反馈
                </button>
                <span>当前浏览器：{feedbackItems.length} 条</span>
              </div>
              <p
                className={styles.feedbackStatus}
                role="status"
                aria-live="polite"
              >
                {feedbackStatus}
              </p>
            </div>
          </div>
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

function DigitalIpProfileCard({
  profile,
}: Readonly<{ profile: DigitalIpProfile }>) {
  const positioning = bindingTitles(profile, "positioning");
  const approvedExamples = bindingTitles(profile, "approved_example");
  const prohibitedLanguage = bindingTitles(profile, "prohibited_language");
  const safetyRules = bindingTitles(profile, "safety_rule");

  return (
    <article className={styles.profileCard}>
      <div className={styles.profileTopline}>
        <div>
          <p>00 / DIGITAL IP PROFILE</p>
          <h3 id="digital-ip-profile-title">{profile.display_name}</h3>
          <span>{profile.identity_summary}</span>
        </div>
        <div className={styles.fingerprint}>
          <span>PROFILE FINGERPRINT</span>
          <code>{profile.profile_fingerprint.slice(0, 16)}</code>
          <small>{profile.profile_version}</small>
        </div>
      </div>

      <div className={styles.characterGrid}>
        {profile.characters.map((character) => (
          <div key={character.character_id}>
            <span>{character.character_id}</span>
            <strong>{character.display_name}</strong>
            <small>{character.role}</small>
          </div>
        ))}
      </div>

      <dl className={styles.profileStats}>
        <div>
          <dt>ACTIVE DOCUMENTS</dt>
          <dd>{profile.active_document_count}</dd>
        </div>
        <div>
          <dt>AUDIENCE</dt>
          <dd>{profile.audiences.join(" / ")}</dd>
        </div>
        <div>
          <dt>CHANNELS</dt>
          <dd>
            {profile.channels
              .map((channel) => channelLabels[channel] ?? channel)
              .join(" / ")}
          </dd>
        </div>
        <div>
          <dt>SCENARIOS</dt>
          <dd>
            {profile.content_scenarios
              .map((scenario) => scenarioLabels[scenario] ?? scenario)
              .join(" / ")}
          </dd>
        </div>
      </dl>

      <section
        className={styles.bindingPanel}
        aria-labelledby="active-binding-title"
      >
        <div>
          <p>ACTIVE-READY SOURCE BINDINGS</p>
          <h4 id="active-binding-title">规则版本绑定</h4>
        </div>
        {profile.document_bindings.length === 0 ? (
          <p className={styles.bindingEmpty}>
            暂无 active-ready 品牌版本；固定身份不代表已有规则正文。
          </p>
        ) : (
          <ul className={styles.bindingList}>
            {profile.document_bindings.map((binding) => (
              <li key={binding.version_id}>
                <div>
                  <span>{kindLabel(binding.document_kind)}</span>
                  <span>V{binding.version}</span>
                </div>
                <strong>{binding.title}</strong>
                <small>ACTIVE / READY</small>
                <small>
                  有效期：{binding.valid_from ?? "未限定"} →{" "}
                  {binding.valid_until ?? "长期有效"}
                </small>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className={styles.personaGrid}>
        <section>
          <h4>核心定位</h4>
          <p>
            {positioning.length > 0
              ? `由 active 定位资料约束：${positioning.join("、")}`
              : "暂无 active 定位资料，不复制或臆造核心价值。"}
          </p>
        </section>
        <section>
          <h4>性格与语气</h4>
          <TagGroup label="ACTIVE TAGS" tags={profile.tone_tags} />
        </section>
        <section>
          <h4>常用表达</h4>
          <p>
            {approvedExamples.length > 0
              ? `从优秀示例召回：${approvedExamples.join("、")}`
              : "暂无 active 优秀示例；完整表达只在受控召回中读取。"}
          </p>
        </section>
        <section>
          <h4>禁用与安全</h4>
          <p>
            {[...prohibitedLanguage, ...safetyRules].length > 0
              ? `绑定规则：${[...prohibitedLanguage, ...safetyRules].join("、")}`
              : "暂无 active 禁用/安全规则正文。"}
          </p>
          <TagGroup label="SAFETY TAGS" tags={profile.safety_tags} />
        </section>
      </div>

      <section
        className={styles.visualCatalog}
        aria-labelledby="visual-catalog-title"
      >
        <div className={styles.visualHeader}>
          <div>
            <p>CONTROLLED VISUAL METADATA</p>
            <h4 id="visual-catalog-title">已审核视觉资产</h4>
          </div>
          <span>
            {profile.visual_catalog_status.toUpperCase()} /{" "}
            {profile.visual_catalog_version ?? "NO CATALOG"}
          </span>
        </div>
        {profile.visual_catalog_status === "unavailable" ? (
          <div className={styles.visualEmpty} role="status">
            <strong>视觉 manifest 当前不可用</strong>
            <p>文字人设仍可查看；页面不会伪造资产，也不会暴露私有路径。</p>
          </div>
        ) : profile.visual_assets.length === 0 ? (
          <div className={styles.visualEmpty} role="status">
            <strong>暂无已审核角色资产</strong>
            <p>catalog 已读取，但没有匹配赛先生或小赛的 approved 元数据。</p>
          </div>
        ) : (
          <div className={styles.visualGrid}>
            {profile.visual_assets.map((asset) => (
              <article key={asset.asset_ref}>
                <div>
                  <span>{asset.asset_kind.toUpperCase()}</span>
                  <span>APPROVED</span>
                </div>
                <h5>{asset.display_name}</h5>
                <dl>
                  <div>
                    <dt>角色</dt>
                    <dd>{asset.characters.join(" / ") || "—"}</dd>
                  </div>
                  <div>
                    <dt>用途</dt>
                    <dd>{asset.roles.join(" / ") || "—"}</dd>
                  </div>
                  <div>
                    <dt>主题</dt>
                    <dd>{asset.topics.join(" / ") || "—"}</dd>
                  </div>
                  <div>
                    <dt>动作</dt>
                    <dd>{asset.poses.join(" / ") || "—"}</dd>
                  </div>
                  <div>
                    <dt>场景</dt>
                    <dd>{asset.scene_tags.join(" / ") || "—"}</dd>
                  </div>
                  <div>
                    <dt>尺寸</dt>
                    <dd>
                      {asset.width} × {asset.height}
                    </dd>
                  </div>
                </dl>
                <small>
                  REF {asset.asset_ref} / PRIORITY {asset.priority}
                </small>
              </article>
            ))}
          </div>
        )}
      </section>
    </article>
  );
}

function TagGroup({
  label,
  tags,
}: Readonly<{ label: string; tags: readonly string[] }>) {
  return (
    <div className={styles.tagGroup}>
      <strong>{label}</strong>
      {tags.length === 0 ? (
        <span>暂无 active 标签</span>
      ) : (
        <ul>
          {tags.map((tag) => (
            <li key={tag}>{tag}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function bindingTitles(
  profile: DigitalIpProfile,
  kind: BrandDocumentKind,
): readonly string[] {
  return profile.document_bindings
    .filter((binding) => binding.document_kind === kind)
    .map((binding) => `${binding.title}（V${binding.version}）`);
}

function kindLabel(value: BrandDocumentKind): string {
  return kindOptions.find((option) => option.value === value)?.label ?? value;
}

function isBrandDocumentKind(value: string): value is BrandDocumentKind {
  return kindOptions.some((option) => option.value === value);
}

function isFeedbackReason(value: string): value is FeedbackReason {
  return feedbackReasons.some((reason) => reason === value);
}
