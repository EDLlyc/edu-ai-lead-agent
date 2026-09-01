import { useState } from "react";

import {
  getOfficialAccountEditorHandoffBody,
  type OfficialAccountEditorHandoffViewModel,
} from "./api";
import { copyRichHtml } from "./clipboard";

import styles from "./OfficialAccountEditorHandoff.module.css";

type Props = Readonly<{
  runId: string;
  handoff: OfficialAccountEditorHandoffViewModel | undefined;
  loading: boolean;
  error: Error | null;
}>;

export function OfficialAccountEditorHandoff({
  runId,
  handoff,
  loading,
  error,
}: Props) {
  const [announcement, setAnnouncement] = useState("");
  const [copying, setCopying] = useState(false);
  const ready = handoff?.copyReady === true;

  async function copyBody() {
    if (!ready) return;
    setCopying(true);
    setAnnouncement("正在准备微信兼容正文…");
    try {
      const html = await getOfficialAccountEditorHandoffBody(runId);
      const result = await copyRichHtml(html);
      const messages: Readonly<Record<typeof result.status, string>> = {
        copied: "正文富文本已复制，可粘贴到微信公众号编辑器。",
        unavailable: "当前浏览器不支持富文本剪贴板，请打开预览页手工复制。",
        permission_denied: "浏览器拒绝了剪贴板权限，请允许权限后重试。",
        failed: "正文复制失败，请打开预览页手工复制。",
      };
      setAnnouncement(messages[result.status]);
    } catch {
      setAnnouncement("正文接口读取失败，请确认本地 API 正常后重试。");
    } finally {
      setCopying(false);
    }
  }

  return (
    <section className={styles.handoff} aria-labelledby="editor-handoff-title">
      <header className={styles.header}>
        <div>
          <span>04 / WECHAT EDITOR HANDOFF</span>
          <h4 id="editor-handoff-title">微信公众号编辑器交接</h4>
          <p>
            复制微信兼容正文，单独下载正文图、新闻原图和 2.35:1
            封面；所有动作仅发生在本地。
          </p>
        </div>
        <strong data-ready={ready ? "true" : "false"}>
          {ready
            ? (handoff?.release?.kindLabel ?? "交接预检通过")
            : "交接尚未开放"}
        </strong>
      </header>

      <div className={styles.boundary} role="note">
        <strong>本地交接，未同步公众号</strong>
        <span>
          正式进入微信后仍需上传正文图片并单独设置封面；这里没有账号、令牌、草稿箱或发布动作。
        </span>
      </div>

      {loading ? <p role="status">正在核对交接门禁…</p> : null}
      {error !== null ? (
        <p className={styles.error} role="alert">
          交接信息读取失败，请确认后端 development flag 已开启。
        </p>
      ) : null}

      {handoff !== undefined ? (
        <>
          {handoff.release !== null ? (
            <div
              className={styles.releaseStatus}
              data-kind={handoff.release.kind}
              role="status"
            >
              <div>
                <span>{handoff.release.policyLabel}</span>
                <strong>{handoff.release.kindLabel}</strong>
                <small>
                  {handoff.release.kind === "machine"
                    ? "基于已持久化的规则校验、模型审校和图片质量状态，无需人工批准动作。"
                    : "使用不可变人工批准记录放行，没有伪装成机器决定。"}
                </small>
              </div>
              <div>
                <span>LAYOUT RECIPE</span>
                <strong>{handoff.recipeLabel ?? "小赛自适应版式"}</strong>
                <small>
                  内容 {handoff.contentFingerprint?.slice(0, 12) ?? "—"} · 产物{" "}
                  {handoff.artifactFingerprint?.slice(0, 12) ?? "—"}
                </small>
              </div>
            </div>
          ) : null}

          <p
            className={styles.mobileStatus}
            data-passed={handoff.mobileStatus === "passed" ? "true" : "false"}
            role="note"
          >
            <strong>
              {handoff.mobileStatus === "passed"
                ? "移动端验收已绑定"
                : "移动端验收尚未运行"}
            </strong>
            <span>{handoff.mobileStatusLabel}</span>
          </p>

          <ol className={styles.gates} aria-label="微信公众号编辑器交接门禁">
            {handoff.checks.map((check, index) => (
              <li
                key={`${check.code}-${index}`}
                data-severity={check.severity}
                data-passed={check.passed ? "true" : "false"}
              >
                <span>{check.label}</span>
                <strong>
                  {check.severity === "warning" && !check.passed
                    ? "提示"
                    : check.passed
                      ? "通过"
                      : "阻断"}
                </strong>
                <small>{check.detail}</small>
                <code>{check.code}</code>
              </li>
            ))}
          </ol>

          {handoff.warningCodes.includes(
            "context_image_rights_unverified_direct_use",
          ) ? (
            <p className={styles.rightsWarning} role="note">
              新闻原图按当前本地策略直接使用，发布权未验证；来源和署名会保留，但这不表示已经授权。
            </p>
          ) : null}

          <div className={styles.actions}>
            <button
              type="button"
              disabled={!ready || copying}
              onClick={() => void copyBody()}
            >
              {copying ? "正在复制…" : "复制公众号正文"}
            </button>
            {handoff.bundleUrl === null ? (
              <button type="button" disabled>
                下载交接 ZIP
              </button>
            ) : (
              <a
                className={styles.primaryDownload}
                href={handoff.bundleUrl}
                download={handoff.bundleFilename ?? undefined}
                onClick={() => setAnnouncement("交接 ZIP 下载已开始。")}
              >
                下载交接 ZIP
              </a>
            )}
            {handoff.previewUrl !== null ? (
              <a
                href={handoff.previewUrl}
                target="_blank"
                rel="noopener noreferrer"
                referrerPolicy="no-referrer"
              >
                打开独立复制预览（新窗口）
              </a>
            ) : null}
          </div>

          <p className={styles.announcement} aria-live="polite">
            {announcement ||
              (ready
                ? "正文和交接包已锁定到同一指纹。"
                : `阻断项：${handoff.blockingCodes.join("、") || "等待预检"}`)}
          </p>

          {handoff.media.length > 0 ? (
            <div className={styles.assets}>
              <h5>交接素材</h5>
              <ul>
                {handoff.media.map((asset) => (
                  <li key={asset.name}>
                    <div>
                      <strong>{asset.roleLabel}</strong>
                      <span>{asset.dimensionsLabel}</span>
                      <small>{asset.altText}</small>
                      {asset.credit !== null ? (
                        <small>署名：{asset.credit}</small>
                      ) : null}
                      {asset.placement !== null ? (
                        <small>
                          定位：第 {asset.placement.sectionIndex + 1} 节 ·
                          正文块 {asset.placement.blockIndex + 1}{" "}
                          {asset.placement.insertionLabel}（
                          {asset.placement.reasonLabel}）
                        </small>
                      ) : null}
                      {asset.sourcePageUrl !== null ? (
                        <a
                          className={styles.sourceLink}
                          href={asset.sourcePageUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          referrerPolicy="no-referrer"
                        >
                          查看新闻来源页
                        </a>
                      ) : null}
                      {asset.rightsStatus ===
                      "publish_permission_unverified" ? (
                        <em>发布权未验证 · 当前策略直接使用</em>
                      ) : null}
                    </div>
                    {asset.downloadUrl !== null ? (
                      <a
                        href={asset.downloadUrl}
                        download={asset.name}
                        onClick={() =>
                          setAnnouncement(`${asset.roleLabel}下载已开始。`)
                        }
                      >
                        下载
                      </a>
                    ) : (
                      <span>地址不可用</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {handoff.previewUrl !== null ? (
            <div className={styles.preview}>
              <div>
                <strong>小赛蓝 · 微信正文预览</strong>
                <code>{handoff.fingerprint?.slice(0, 16)}</code>
              </div>
              <iframe
                title="微信公众号编辑器交接预览"
                src={handoff.previewUrl}
                sandbox="allow-scripts"
                referrerPolicy="no-referrer"
              />
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
