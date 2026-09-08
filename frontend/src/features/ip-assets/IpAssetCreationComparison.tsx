import type { IpAsset, IpAssetCharacter, IpAssetType } from "./api";
import { IpAssetOriginalPreview } from "./IpAssetOriginalPreview";
import type { LocalIpAssetProfile } from "./profile";

import styles from "./IpAssetCreationComparison.module.css";

// A page-local submission receipt, never reconstructed from the editable form or storage.
export type IpAssetCreationSnapshot = Readonly<{
  prompt: string;
  character: IpAssetCharacter;
  characterLabel: string;
  assetType: IpAssetType;
  assetTypeLabel: string;
  profileRef: string;
  references: readonly IpAsset[];
}>;

export function IpAssetCreationComparison({
  snapshot,
  output,
  profile,
}: Readonly<{
  snapshot: IpAssetCreationSnapshot;
  output: IpAsset;
  profile: LocalIpAssetProfile;
}>) {
  return (
    <section
      className={styles.comparison}
      aria-labelledby="creation-comparison-title"
    >
      <header className={styles.heading}>
        <div>
          <p className={styles.eyebrow}>CREATION STUDY / 本次创作对照</p>
          <h2 id="creation-comparison-title">从参考，到新画面</h2>
        </div>
        <p>
          参考图与简报保留提交时的内容。
          <br />
          点击图片，放大查看细节。
        </p>
      </header>
      <div className={styles.spread}>
        <section
          className={styles.sources}
          aria-labelledby="comparison-sources-title"
        >
          <h3 id="comparison-sources-title">
            <span>01</span> 参考图 <i aria-hidden="true">→</i>
          </h3>
          <p className={styles.note}>
            按实际提交顺序 · {snapshot.references.length} 张
          </p>
          <ol className={styles.referenceList}>
            {snapshot.references.map((asset, index) => (
              <li key={asset.asset_ref}>
                <div className={styles.referenceCaption}>
                  <span>参考 {String(index + 1).padStart(2, "0")}</span>
                  <strong>{asset.canonical_name}</strong>
                </div>
                <IpAssetOriginalPreview asset={asset} profile={profile} />
              </li>
            ))}
          </ol>
        </section>
        <section
          className={styles.brief}
          aria-labelledby="comparison-brief-title"
        >
          <h3 id="comparison-brief-title">
            <span>02</span> 已提交简报 <i aria-hidden="true">→</i>
          </h3>
          <p className={styles.note}>本次请求的画面描述</p>
          <p className={styles.prompt}>{snapshot.prompt}</p>
          <dl className={styles.taxonomy}>
            <div>
              <dt>IP 角色</dt>
              <dd>{snapshot.characterLabel}</dd>
            </div>
            <div>
              <dt>资产类型</dt>
              <dd>{snapshot.assetTypeLabel}</dd>
            </div>
            <div>
              <dt>请求画幅</dt>
              <dd>1:1</dd>
            </div>
          </dl>
          <p className={styles.receipt}>
            提交快照 · 修改上方简报不会改变本次对照
          </p>
        </section>
        <section
          className={styles.result}
          aria-labelledby="comparison-result-title"
        >
          <h3 id="comparison-result-title">
            <span>03</span> 生成画面
          </h3>
          <p className={styles.note}>原图比例 · 完整呈现</p>
          <IpAssetOriginalPreview asset={output} profile={profile} />
          <div className={styles.resultCaption}>
            <strong>{output.canonical_name}</strong>
            <span>
              {output.shared ? "已在共享图库" : "仅在我的素材架 · 尚未共享"}
            </span>
          </div>
        </section>
      </div>
    </section>
  );
}
