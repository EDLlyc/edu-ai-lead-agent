import {
  forwardRef,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import HTMLFlipBook from "react-pageflip";

import type { IpAssetFlipbookPage } from "./flipbookDraft";
import {
  buildIpAssetFlipbookLeaves,
  deriveIpAssetFlipbookPageRatio,
  type IpAssetFlipbookLeaf as Leaf,
} from "./flipbookLeaves";

import styles from "./IpAssetFlipbookRenderer.module.css";

type PageFlipController = Readonly<{
  flipNext: () => void;
  flipPrev: () => void;
  turnToNextPage: () => void;
  turnToPrevPage: () => void;
  turnToPage: (page: number) => void;
  getCurrentPageIndex: () => number;
}>;

type FlipbookHandle = Readonly<{
  pageFlip: () => PageFlipController;
}>;

type PageFlipState = "user_fold" | "fold_corner" | "flipping" | "read";

export function IpAssetFlipbookRenderer({
  pages,
  title,
}: Readonly<{
  pages: readonly IpAssetFlipbookPage[];
  title: string;
}>) {
  const bookRef = useRef<FlipbookHandle | null>(null);
  const [currentPage, setCurrentPage] = useState(0);
  const [flipState, setFlipState] = useState<PageFlipState>("read");
  const reducedMotion = usePrefersReducedMotion();
  const leaves = useMemo(() => buildIpAssetFlipbookLeaves(pages), [pages]);
  const pageRatio = useMemo(
    () => deriveIpAssetFlipbookPageRatio(pages),
    [pages],
  );
  const bookKey = pages.map((page) => page.assetRef).join(":");
  const pageHeight = 700;
  const pageWidth = Math.round(pageHeight * pageRatio);
  const minWidth = Math.round(300 * pageRatio);
  const currentPosition = Math.min(currentPage + 1, leaves.length);
  const canGoPrevious = currentPage > 0 && flipState === "read";
  const canGoNext = currentPage < leaves.length - 1 && flipState === "read";

  const getController = useCallback(() => bookRef.current?.pageFlip(), []);
  const handleInit = useCallback(() => {
    const controller = getController();
    setCurrentPage(controller?.getCurrentPageIndex() ?? 0);
    setFlipState("read");
  }, [getController]);
  const previous = () => {
    const controller = getController();
    if (!canGoPrevious || controller === undefined) return;
    if (reducedMotion) {
      controller.turnToPrevPage();
      return;
    }
    setFlipState("flipping");
    controller.flipPrev();
  };
  const next = () => {
    const controller = getController();
    if (!canGoNext || controller === undefined) return;
    if (reducedMotion) {
      controller.turnToNextPage();
      return;
    }
    setFlipState("flipping");
    controller.flipNext();
  };
  const goTo = (page: number) => {
    const controller = getController();
    if (flipState !== "read" || controller === undefined) return;
    controller.turnToPage(page);
    setCurrentPage(page);
  };
  const handleKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (isInteractiveTarget(event.target)) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      previous();
    } else if (event.key === "ArrowRight" || event.key === " ") {
      event.preventDefault();
      next();
    } else if (event.key === "Home") {
      event.preventDefault();
      goTo(0);
    } else if (event.key === "End") {
      event.preventDefault();
      goTo(leaves.length - 1);
    }
  };

  return (
    <section
      className={styles.renderer}
      aria-labelledby="flipbook-preview-title"
    >
      <div className={styles.previewHeading}>
        <div>
          <p>LIVE PAGE PROOF</p>
          <h2 id="flipbook-preview-title">翻页预览</h2>
        </div>
        <p
          className={styles.pagePosition}
          aria-live="polite"
          aria-atomic="true"
        >
          第 {currentPosition} / {leaves.length} 页
          {flipState === "read" ? "" : " · 翻页中"}
        </p>
      </div>

      <div
        className={styles.bookStage}
        role="region"
        aria-label={`${title.trim() || "未命名相册"}翻页区域`}
        aria-busy={flipState !== "read"}
        tabIndex={0}
        onKeyDown={handleKeyboard}
        style={{ "--book-page-ratio": pageRatio } as CSSProperties}
      >
        <div className={styles.stageRule} aria-hidden="true">
          <span>ISSUE 01</span>
          <span>2—20 SELECTED WORKS</span>
        </div>
        <HTMLFlipBook
          key={bookKey}
          ref={bookRef}
          className={styles.book ?? ""}
          style={{}}
          width={pageWidth}
          height={pageHeight}
          minWidth={minWidth}
          maxWidth={pageWidth}
          minHeight={300}
          maxHeight={pageHeight}
          size="stretch"
          startPage={0}
          drawShadow
          flippingTime={reducedMotion ? 1 : 680}
          usePortrait
          startZIndex={0}
          autoSize
          maxShadowOpacity={0.24}
          showCover
          mobileScrollSupport
          clickEventForward={false}
          useMouseEvents
          swipeDistance={24}
          showPageCorners={!reducedMotion}
          disableFlipByClick={false}
          onFlip={(event: unknown) => {
            const data = readEventData(event);
            if (typeof data === "number") setCurrentPage(data);
          }}
          onChangeState={(event: unknown) => {
            const data = readEventData(event);
            if (isPageFlipState(data)) setFlipState(data);
          }}
          onInit={handleInit}
        >
          {leaves.map((leaf, index) => (
            <FlipbookLeaf
              key={leaf.key}
              leaf={leaf}
              leafNumber={index + 1}
              title={title}
            />
          ))}
        </HTMLFlipBook>
      </div>

      <div className={styles.controls} aria-label="翻页控制">
        <button type="button" disabled={!canGoPrevious} onClick={previous}>
          <span aria-hidden="true">←</span>
          上一页
        </button>
        <p>支持拖拽页角、触摸滑动与方向键</p>
        <button type="button" disabled={!canGoNext} onClick={next}>
          下一页
          <span aria-hidden="true">→</span>
        </button>
      </div>
    </section>
  );
}

const FlipbookLeaf = forwardRef<
  HTMLDivElement,
  Readonly<{ leaf: Leaf; leafNumber: number; title: string }>
>(function FlipbookLeaf({ leaf, leafNumber, title }, ref) {
  const [failed, setFailed] = useState(false);
  if (leaf.kind === "back") {
    return (
      <div
        ref={ref}
        className={`${styles.leaf} ${styles.backCover}`}
        data-density={leaf.density}
        role="group"
        aria-label={`第 ${leafNumber} 页，封底`}
      />
    );
  }
  if (leaf.kind === "blank") {
    return (
      <div
        ref={ref}
        className={`${styles.leaf} ${styles.blankLeaf}`}
        data-density={leaf.density}
        role="group"
        aria-label={`第 ${leafNumber} 页，内封底留白`}
      >
        <span aria-hidden="true" />
      </div>
    );
  }
  const isCover = leaf.density === "hard";
  return (
    <div
      ref={ref}
      className={`${styles.leaf} ${isCover ? styles.frontCover : styles.imageLeaf}`}
      data-density={leaf.density}
      role="group"
      aria-label={`第 ${leafNumber} 页${isCover ? "，封面" : ""}：${leaf.page.canonicalName}`}
    >
      <div className={styles.leafTopline} aria-hidden="true">
        <span>{String(leafNumber).padStart(2, "0")}</span>
        <span>{isCover ? "COVER STORY" : "SAI VISUAL ARCHIVE"}</span>
      </div>
      <div className={styles.imageMat}>
        {failed ? (
          <div
            className={styles.imageFallback}
            role="img"
            aria-label={`${leaf.page.canonicalName}：图片预览失败`}
          >
            <span aria-hidden="true">×</span>
            图片预览失败
          </div>
        ) : (
          <img
            src={leaf.page.previewUrl}
            alt={leaf.page.canonicalName}
            draggable={false}
            onError={() => setFailed(true)}
          />
        )}
      </div>
      <div className={styles.caption}>
        <span>
          {isCover ? title.trim() || "未命名相册" : leaf.page.canonicalName}
        </span>
        <small>
          {leaf.page.width} × {leaf.page.height}
        </small>
      </div>
    </div>
  );
});

function readEventData(event: unknown): unknown {
  return typeof event === "object" && event !== null && "data" in event
    ? event.data
    : undefined;
}

function isPageFlipState(value: unknown): value is PageFlipState {
  return (
    value === "user_fold" ||
    value === "fold_corner" ||
    value === "flipping" ||
    value === "read"
  );
}

function isInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return ["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA"].includes(
    target.tagName,
  );
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () =>
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = () => setReduced(query.matches);
    query.addEventListener("change", handleChange);
    return () => query.removeEventListener("change", handleChange);
  }, []);
  return reduced;
}
