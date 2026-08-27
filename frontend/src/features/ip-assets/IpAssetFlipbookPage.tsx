import { useEffect, useState } from "react";

import { IpAssetFlipbookRenderer } from "./IpAssetFlipbookRenderer";
import {
  clearStagedIpAssetFlipbookDraft,
  IP_ASSET_FLIPBOOK_MIN_PAGES,
  moveIpAssetFlipbookPage,
  readStagedIpAssetFlipbookDraft,
  removeIpAssetFlipbookPage,
  type IpAssetFlipbookDraft,
  type IpAssetFlipbookPage as FlipbookPage,
} from "./flipbookDraft";

import styles from "./IpAssetFlipbookPage.module.css";

export function IpAssetFlipbookPage() {
  const [initialDraft] = useState(readDraftSafely);
  const [title, setTitle] = useState(initialDraft?.title ?? "");
  const [pages, setPages] = useState<readonly FlipbookPage[]>(
    initialDraft?.pages ?? [],
  );
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    clearStagedIpAssetFlipbookDraft();
  }, []);

  if (initialDraft === null) return <MissingFlipbookDraft />;

  const movePage = (from: number, to: number, page: FlipbookPage) => {
    setPages((current) => moveIpAssetFlipbookPage(current, from, to));
    setAnnouncement(`${page.canonicalName} 已移到第 ${to + 1} 位。`);
  };
  const removePage = (index: number, page: FlipbookPage) => {
    setPages((current) => removeIpAssetFlipbookPage(current, index));
    setAnnouncement(`${page.canonicalName} 已从相册移除。`);
  };

  return (
    <section className={styles.page} aria-labelledby="flipbook-page-title">
      <header className={styles.masthead}>
        <div className={styles.topline}>
          <a href="/ip-assets">← 返回 IP 资产库</a>
          <span>SAI VISUAL EDITION · 01</span>
        </div>
        <div className={styles.heroCopy}>
          <div>
            <p className={styles.eyebrow}>PHOTO FLIPBOOK / 即时相册</p>
            <h1 id="flipbook-page-title">把灵感，装订成一本相册。</h1>
          </div>
          <p className={styles.heroNote}>
            调整顺序就是重新编排故事，第一张图片始终作为封面。此版本只在当前页面保留，刷新后不会保存。
          </p>
        </div>
      </header>

      <div className={styles.workspace}>
        <div
          className={styles.editor}
          role="region"
          aria-labelledby="flipbook-editor-title"
        >
          <div className={styles.editorHeading}>
            <div>
              <p>EDIT DESK</p>
              <h2 id="flipbook-editor-title">相册编排</h2>
            </div>
            <span>{String(pages.length).padStart(2, "0")} 张</span>
          </div>

          <label className={styles.titleField}>
            <span>相册标题</span>
            <input
              aria-label="相册标题"
              value={title}
              maxLength={80}
              placeholder="给这组图片起一个标题"
              onChange={(event) => setTitle(event.currentTarget.value)}
            />
            <small>{title.length} / 80</small>
          </label>

          <div className={styles.orderHeading}>
            <h3>图片顺序</h3>
            <p>使用按钮调整；排在第 1 位的图片是封面。</p>
          </div>
          <ol className={styles.pageOrder}>
            {pages.map((page, index) => (
              <li key={page.assetRef} className={styles.orderItem}>
                <span className={styles.orderNumber} aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <img src={page.previewUrl} alt="" />
                <div className={styles.orderCopy}>
                  <strong>{page.canonicalName}</strong>
                  <span>
                    {index === 0 ? "封面" : `${page.width} × ${page.height}`}
                  </span>
                </div>
                <div className={styles.orderActions}>
                  <button
                    type="button"
                    disabled={index === 0}
                    aria-label={`上移 ${page.canonicalName}`}
                    onClick={() => movePage(index, index - 1, page)}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    disabled={index === pages.length - 1}
                    aria-label={`下移 ${page.canonicalName}`}
                    onClick={() => movePage(index, index + 1, page)}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className={styles.removeButton}
                    aria-label={`移除 ${page.canonicalName}`}
                    onClick={() => removePage(index, page)}
                  >
                    ×
                  </button>
                </div>
              </li>
            ))}
          </ol>
          <p
            className={styles.announcement}
            aria-live="polite"
            aria-atomic="true"
          >
            {announcement}
          </p>
          <p className={styles.memoryNote}>
            <span aria-hidden="true">●</span>
            即时预览 · 不写入浏览器、数据库或图片资产
          </p>
        </div>

        <div className={styles.previewColumn}>
          {pages.length >= IP_ASSET_FLIPBOOK_MIN_PAGES ? (
            <IpAssetFlipbookRenderer pages={pages} title={title} />
          ) : (
            <section
              className={styles.minimumState}
              aria-labelledby="minimum-title"
            >
              <p>LAYOUT PAUSED</p>
              <h2 id="minimum-title">至少需要 2 张图片才能继续翻页</h2>
              <p>
                当前编排已保留在本页。请返回资产库重新选择图片，制作一册新的即时相册。
              </p>
              <a href="/ip-assets">返回资产库选择图片</a>
            </section>
          )}
        </div>
      </div>
    </section>
  );
}

function MissingFlipbookDraft() {
  return (
    <section
      className={styles.recovery}
      aria-labelledby="flipbook-recovery-title"
    >
      <div className={styles.recoveryMark} aria-hidden="true">
        <span>01</span>
        <span>×</span>
      </div>
      <div>
        <p>EMPTY CONTACT SHEET</p>
        <h1 id="flipbook-recovery-title">这本即时相册已经合上了</h1>
        <p>
          相册草稿只在打开页面时传递一次，刷新、直接访问或关闭页面后不会保存。回到资产库选择
          2–20 张可用图片即可重新制作。
        </p>
        <a href="/ip-assets">返回 IP 资产库</a>
      </div>
    </section>
  );
}

function readDraftSafely(): IpAssetFlipbookDraft | null {
  try {
    return readStagedIpAssetFlipbookDraft();
  } catch {
    return null;
  }
}
