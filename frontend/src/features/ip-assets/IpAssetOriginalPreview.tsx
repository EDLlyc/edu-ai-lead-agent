import { useCallback, useEffect, useId, useRef, useState } from "react";

import { fetchIpAssetBlob, ipAssetResourceUrl, type IpAsset } from "./api";
import type { LocalIpAssetProfile } from "./profile";

import styles from "./IpAssetOriginalPreview.module.css";

export function IpAssetOriginalPreview({
  asset,
  profile,
}: Readonly<{ asset: IpAsset; profile: LocalIpAssetProfile | null }>) {
  const url = originalPreviewUrl(asset);
  if (url === null || (!asset.shared && profile === null)) {
    return <PreviewMessage name={asset.canonical_name} failed />;
  }
  return (
    <OriginalPreviewLoader
      key={`${asset.asset_ref}:${url}:${profile?.profileRef ?? "shared"}`}
      asset={asset}
      resourceUrl={url}
      profileToken={asset.shared ? undefined : profile?.token}
    />
  );
}

function OriginalPreviewLoader({
  asset,
  resourceUrl,
  profileToken,
}: Readonly<{
  asset: IpAsset;
  resourceUrl: string;
  profileToken: string | undefined;
}>) {
  const [privateMedia, setPrivateMedia] = useState<Readonly<{
    url: string;
    token: string;
  }> | null>(null);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const closeZoom = useCallback(() => setZoomed(false), []);
  const url = asset.shared
    ? resourceUrl
    : privateMedia?.token === profileToken
      ? privateMedia?.url
      : undefined;

  useEffect(() => {
    if (profileToken === undefined) return;
    let active = true;
    let ownedUrl: string | null = null;
    void fetchIpAssetBlob(asset.preview_url, profileToken).then(
      (blob) => {
        if (!active) return;
        ownedUrl = URL.createObjectURL(blob);
        setPrivateMedia({ url: ownedUrl, token: profileToken });
      },
      () => {
        if (active) setFailed(true);
      },
    );
    return () => {
      active = false;
      if (ownedUrl !== null) URL.revokeObjectURL(ownedUrl);
    };
  }, [asset.preview_url, profileToken]);

  return (
    <div className={styles.preview}>
      <button
        className={styles.imageButton}
        type="button"
        onClick={() => setZoomed(true)}
        aria-label={`放大查看 ${asset.canonical_name}`}
      >
        {url === undefined || failed ? null : (
          <img
            src={url}
            alt={asset.canonical_name}
            width={asset.width}
            height={asset.height}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
          />
        )}
        {!loaded || failed ? (
          <PreviewMessage name={asset.canonical_name} failed={failed} />
        ) : null}
        <span className={styles.zoomHint}>
          <span aria-hidden="true">↗</span> 查看大图
        </span>
      </button>
      {zoomed ? (
        <PreviewDialog
          asset={asset}
          url={url}
          failed={failed}
          onFailure={() => setFailed(true)}
          onClose={closeZoom}
        />
      ) : null}
    </div>
  );
}

function PreviewMessage({
  name,
  failed,
}: Readonly<{ name: string; failed: boolean }>) {
  return (
    <span className={styles.message} role="status">
      {name} · {failed ? "原图预览不可用" : "正在读取原图…"}
    </span>
  );
}

function PreviewDialog({
  asset,
  url,
  failed,
  onFailure,
  onClose,
}: Readonly<{
  asset: IpAsset;
  url: string | undefined;
  failed: boolean;
  onFailure: () => void;
  onClose: () => void;
}>) {
  const titleId = useId();
  const closeButton = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      } else if (event.key === "Tab") {
        // This read-only dialog has exactly one interactive control.
        event.preventDefault();
        closeButton.current?.focus();
      }
    };
    const containFocus = (event: FocusEvent) => {
      if (
        event.target instanceof Node &&
        !panel.current?.contains(event.target)
      )
        closeButton.current?.focus();
    };
    document.addEventListener("keydown", handleKey);
    document.addEventListener("focusin", containFocus);
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.removeEventListener("focusin", containFocus);
      document.body.style.overflow = previousOverflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [onClose]);

  return (
    <div
      className={styles.backdrop}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header>
          <div>
            <p>ORIGINAL / 原图预览</p>
            <h2 id={titleId}>{asset.canonical_name}</h2>
          </div>
          <button
            ref={closeButton}
            type="button"
            onClick={onClose}
            aria-label="关闭原图预览"
          >
            关闭 ×
          </button>
        </header>
        <div className={styles.dialogImage}>
          {!failed && url !== undefined ? (
            <img
              src={url}
              alt={asset.canonical_name}
              onLoad={() => setLoaded(true)}
              onError={onFailure}
            />
          ) : null}
          {failed || !loaded ? (
            <PreviewMessage name={asset.canonical_name} failed={failed} />
          ) : null}
        </div>
        <p className={styles.dialogNote}>完整画面 · 预览不会下载或共享图片</p>
      </div>
    </div>
  );
}

function originalPreviewUrl(asset: IpAsset): string | null {
  if (asset.status !== "ready") return null;
  const resolved = ipAssetResourceUrl(asset.preview_url);
  if (resolved === null) return null;
  const url = new URL(resolved);
  // Preview must never resolve to the counted download endpoint, even on the API origin.
  return url.pathname === `/api/v1/ip-assets/${asset.asset_ref}/preview` &&
    !url.search &&
    !url.hash &&
    !url.username &&
    !url.password
    ? resolved
    : null;
}
