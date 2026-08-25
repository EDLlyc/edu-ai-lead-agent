import { useEffect, useMemo, useRef, useState } from "react";

import {
  downloadIpAssetOriginal,
  emptyIpAssetFilters,
  fetchIpAssetBlob,
  ipAssetResourceUrl,
  type IpAsset,
  type IpAssetCharacter,
  type IpAssetPersonalItem,
  type IpAssetPersonalSource,
  type IpAssetType,
} from "./api";
import {
  useCreateIpAssetGeneration,
  useIpAssetCapabilities,
  useIpAssetDetail,
  useIpAssetGeneration,
  useIpAssets,
  usePersonalIpAssets,
  useRestoreIpAssetProfile,
  useSetIpAssetFavorite,
  useShareIpAsset,
} from "./hooks";
import { ProfileSetupDialog } from "./ProfileSetupDialog";
import {
  clearLocalIpAssetProfile,
  loadLocalIpAssetProfile,
  type LocalIpAssetProfile,
} from "./profile";

import styles from "./IpAssetCreationPage.module.css";

const characterOptions: readonly Readonly<{
  value: IpAssetCharacter;
  label: string;
}>[] = [
  { value: "xiao_sai", label: "小赛" },
  { value: "sai_xiansheng", label: "赛先生" },
  { value: "duo", label: "双角色" },
  { value: "other", label: "其他 IP" },
];

const assetTypeOptions: readonly Readonly<{
  value: IpAssetType;
  label: string;
}>[] = [
  { value: "scene_illustration", label: "场景插画" },
  { value: "meme_sticker", label: "表情包" },
  { value: "full_body_action", label: "全身动作" },
  { value: "portrait_avatar", label: "头像" },
  { value: "expression", label: "表情" },
  { value: "poster_element", label: "海报元素" },
  { value: "transparent_cutout", label: "透明底素材" },
  { value: "identity_reference", label: "形象设定" },
  { value: "other", label: "其他" },
];

const personalTabs: readonly Readonly<{
  value: IpAssetPersonalSource;
  label: string;
}>[] = [
  { value: "all", label: "全部" },
  { value: "generated", label: "AI 生成" },
  { value: "uploaded", label: "我的上传" },
  { value: "favorite", label: "收藏" },
];

export function IpAssetCreationPage() {
  const capabilities = useIpAssetCapabilities();
  const [profile, setProfile] = useState<LocalIpAssetProfile | null>(
    loadLocalIpAssetProfile,
  );
  const restoredProfile = useRestoreIpAssetProfile(profile);
  const activeProfile = restoredProfile.isError ? null : profile;
  const [showProfileSetup, setShowProfileSetup] = useState(false);
  const [referenceQuery, setReferenceQuery] = useState("");
  const [references, setReferences] = useState<readonly IpAsset[]>([]);
  const [initialReferenceRef, setInitialReferenceRef] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get("reference"),
  );
  const initialReference = useIpAssetDetail(initialReferenceRef, activeProfile);
  const [character, setCharacter] = useState<IpAssetCharacter>("xiao_sai");
  const [assetType, setAssetType] = useState<IpAssetType>("scene_illustration");
  const [jobRef, setJobRef] = useState<string | null>(null);
  const [personalSource, setPersonalSource] =
    useState<IpAssetPersonalSource>("all");
  const [announcement, setAnnouncement] = useState("");
  const generationAttempt = useRef<{
    readonly signature: string;
    readonly idempotencyKey: string;
  } | null>(null);
  const generation = useCreateIpAssetGeneration();
  const generationStatus = useIpAssetGeneration(jobRef, activeProfile);
  const output = useIpAssetDetail(
    generationStatus.data?.output_asset_ref ?? null,
    activeProfile,
  );
  const favorites = useSetIpAssetFavorite();
  const share = useShareIpAsset();
  const pickerFilters = useMemo(
    () => ({ ...emptyIpAssetFilters, query: referenceQuery }),
    [referenceQuery],
  );
  const library = useIpAssets(
    pickerFilters,
    capabilities.data?.enabled === true,
    activeProfile,
  );
  const personal = usePersonalIpAssets(activeProfile, personalSource);
  const pickerAssets = useMemo(
    () =>
      library.data?.pages
        .flatMap((page) => page.items)
        .filter((asset) => asset.status === "ready") ?? [],
    [library.data?.pages],
  );
  const personalItems = useMemo(
    () => personal.data?.pages.flatMap((page) => page.items) ?? [],
    [personal.data?.pages],
  );

  useEffect(() => {
    if (!restoredProfile.isError || profile === null) return;
    clearLocalIpAssetProfile();
  }, [profile, restoredProfile.isError]);

  useEffect(() => {
    if (initialReference.data === undefined || initialReferenceRef === null)
      return;
    const timer = window.setTimeout(() => {
      if (
        initialReference.data.status === "ready" &&
        initialReference.data.shared
      ) {
        setReferences([initialReference.data]);
        setAnnouncement("已将共享图库图片放入参考 01。");
      } else {
        setAnnouncement("该图片不是可用的共享参考素材。");
      }
      setInitialReferenceRef(null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [initialReference.data, initialReferenceRef]);

  const requireProfile = (action: () => void) => {
    if (activeProfile === null) {
      setShowProfileSetup(true);
      return;
    }
    action();
  };

  const toggleFavorite = (asset: IpAsset) =>
    requireProfile(() => {
      if (activeProfile === null) return;
      favorites.mutate(
        {
          token: activeProfile.token,
          assetRef: asset.asset_ref,
          favorite: !asset.favorite,
        },
        {
          onSuccess: (result) =>
            setAnnouncement(result.favorite ? "已加入收藏。" : "已取消收藏。"),
        },
      );
    });

  return (
    <section className={styles.studio} aria-labelledby="studio-title">
      <header className={styles.header}>
        <a className={styles.backLink} href="/ip-assets">
          ← 返回共享图库
        </a>
        <div className={styles.headerGrid}>
          <div>
            <p className={styles.kicker}>SAI IMAGE ATELIER / 01</p>
            <h1 id="studio-title">AI 视觉创作室</h1>
            <p className={styles.intro}>
              从共享图库挑选角色、动作与场景参考，组合成一次可追溯的创作。结果先进入你的素材架，再由你决定是否加入共享图库。
            </p>
          </div>
          <div className={styles.profileCard}>
            <span>浏览器本地名片</span>
            {activeProfile === null ? (
              <>
                <strong>尚未建立</strong>
                <button type="button" onClick={() => setShowProfileSetup(true)}>
                  建立名片
                </button>
              </>
            ) : (
              <>
                <strong>{activeProfile.displayName}</strong>
                <small>
                  {activeProfile.department} ·{" "}
                  {activeProfile.profileRef.slice(-6)}
                </small>
              </>
            )}
            <p>无密码、无身份验证、无跨设备恢复。</p>
          </div>
        </div>
      </header>

      {capabilities.isError ? (
        <p className={styles.error} role="alert">
          无法连接 IP 资产服务。
        </p>
      ) : null}
      {restoredProfile.isError ? (
        <p className={styles.capabilityNote} role="status">
          这台浏览器保存的素材名片已失效，请重新建立。
        </p>
      ) : null}
      {announcement ? (
        <p className={styles.visuallyHidden} role="status" aria-live="polite">
          {announcement}
        </p>
      ) : null}

      <section
        className={styles.creationStage}
        aria-labelledby="creation-stage-title"
      >
        <form
          className={styles.briefPanel}
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            requireProfile(() => {
              if (activeProfile === null) return;
              if (references.length < 1 || references.length > 3) {
                setAnnouncement("请先选择一至三张参考图。");
                return;
              }
              const prompt = formText(form, "prompt");
              const signature = JSON.stringify({
                prompt,
                character,
                assetType,
                department: activeProfile.department,
                contributor: activeProfile.displayName,
                referenceAssetRefs: references.map((item) => item.asset_ref),
              });
              const idempotencyKey =
                generationAttempt.current?.signature === signature
                  ? generationAttempt.current.idempotencyKey
                  : createIdempotencyKey();
              generationAttempt.current = { signature, idempotencyKey };
              generation.mutate(
                {
                  prompt,
                  character,
                  assetType,
                  department: activeProfile.department,
                  contributor: activeProfile.displayName,
                  referenceAssetRefs: references.map((item) => item.asset_ref),
                  idempotencyKey,
                  profileToken: activeProfile.token,
                },
                {
                  onSuccess: (job) => {
                    setJobRef(job.job_ref);
                    setAnnouncement("生成任务已建立，正在等待结果。");
                  },
                },
              );
            });
          }}
        >
          <div className={styles.sectionNumber}>01 / 创作简报</div>
          <h2 id="creation-stage-title">把画面说清楚</h2>
          <label className={styles.promptField}>
            <span>画面描述</span>
            <textarea
              name="prompt"
              required
              minLength={8}
              maxLength={2000}
              placeholder="例如：小赛在未来感科学课堂演示火箭实验，开心、明亮、适合公众号头图…"
            />
          </label>
          <div className={styles.optionGrid}>
            <label>
              <span>IP 角色</span>
              <select
                value={character}
                onChange={(event) =>
                  setCharacter(event.target.value as IpAssetCharacter)
                }
              >
                {characterOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>资产类型</span>
              <select
                value={assetType}
                onChange={(event) =>
                  setAssetType(event.target.value as IpAssetType)
                }
              >
                {assetTypeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <ReferenceFilmstrip
            references={references}
            onChange={setReferences}
          />

          <button
            className={styles.generateButton}
            type="submit"
            disabled={
              capabilities.data?.generation_available !== true ||
              generation.isPending
            }
          >
            <span aria-hidden="true">✦</span>
            {generation.isPending ? "正在建立任务…" : "生成 1:1 图片"}
          </button>
          {capabilities.data?.generation_available === false ? (
            <p className={styles.capabilityNote}>
              当前生图服务未启用；参考选择、个人素材与收藏仍可使用。
            </p>
          ) : null}
          {generation.isError ? (
            <p className={styles.error} role="alert">
              生成任务创建失败，请检查参考图后重试。
            </p>
          ) : null}
        </form>

        <OutputStage
          status={generationStatus.data}
          statusError={generationStatus.isError}
          output={output.data}
          profile={activeProfile}
          sharing={share.isPending}
          onShare={(assetRef) => {
            if (activeProfile === null) return;
            share.mutate(
              { token: activeProfile.token, assetRef },
              { onSuccess: () => setAnnouncement("图片已加入共享图库。") },
            );
          }}
          onDownload={(asset) => {
            void downloadIpAssetOriginal({
              asset,
              ...(activeProfile === null
                ? {}
                : { profileToken: activeProfile.token }),
            }).then(
              () => setAnnouncement("原图下载已开始。"),
              () => setAnnouncement("原图下载失败，请稍后重试。"),
            );
          }}
        />
      </section>

      <section
        className={styles.picker}
        aria-labelledby="reference-library-title"
      >
        <div className={styles.pickerHeading}>
          <div>
            <p className={styles.sectionNumber}>02 / 参考图库</p>
            <h2 id="reference-library-title">选择创作素材</h2>
          </div>
          <label>
            <span className={styles.visuallyHidden}>筛选参考图库</span>
            <input
              value={referenceQuery}
              maxLength={200}
              placeholder="按名称、动作、场景筛选…"
              onChange={(event) => setReferenceQuery(event.target.value)}
            />
          </label>
        </div>
        {library.isLoading ? <p role="status">正在读取共享素材…</p> : null}
        <div className={styles.referenceLibrary}>
          {pickerAssets.map((asset) => {
            const selectedIndex = references.findIndex(
              (item) => item.asset_ref === asset.asset_ref,
            );
            const selected = selectedIndex >= 0;
            return (
              <article key={asset.asset_ref} className={styles.referenceCard}>
                <SharedPreview asset={asset} />
                <div>
                  <small>
                    {selected ? `参考 ${selectedIndex + 1}` : "共享素材"}
                  </small>
                  <strong>{asset.canonical_name}</strong>
                  <div className={styles.referenceActions}>
                    <button
                      type="button"
                      aria-pressed={selected}
                      disabled={!selected && references.length >= 3}
                      onClick={() =>
                        setReferences((current) =>
                          selected
                            ? current.filter(
                                (item) => item.asset_ref !== asset.asset_ref,
                              )
                            : [...current, asset],
                        )
                      }
                    >
                      {selected ? "移出参考" : "加入参考"}
                    </button>
                    <button
                      type="button"
                      aria-pressed={asset.favorite}
                      onClick={() => toggleFavorite(asset)}
                    >
                      {asset.favorite ? "取消收藏" : "收藏"}
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section
        className={styles.personalShelf}
        aria-labelledby="personal-shelf-title"
      >
        <div className={styles.shelfHeading}>
          <div>
            <p className={styles.sectionNumber}>03 / 我的素材架</p>
            <h2 id="personal-shelf-title">继续使用，不必重新寻找</h2>
          </div>
          <div className={styles.tabs} role="tablist" aria-label="个人素材来源">
            {personalTabs.map((tab) => (
              <button
                key={tab.value}
                type="button"
                role="tab"
                aria-selected={personalSource === tab.value}
                onClick={() =>
                  requireProfile(() => setPersonalSource(tab.value))
                }
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        {activeProfile === null ? (
          <button
            className={styles.emptyShelf}
            type="button"
            onClick={() => setShowProfileSetup(true)}
          >
            建立浏览器本地名片，开始保存生成图、上传和收藏
          </button>
        ) : personal.isLoading ? (
          <p role="status">正在整理个人素材…</p>
        ) : personalItems.length === 0 ? (
          <p className={styles.emptyShelf}>这个分类还没有素材。</p>
        ) : (
          <div className={styles.personalGrid}>
            {personalItems.map((item) => (
              <PersonalAssetCard
                key={item.asset.asset_ref}
                item={item}
                profile={activeProfile}
                onFavorite={() => toggleFavorite(item.asset)}
                onShare={() =>
                  share.mutate(
                    {
                      token: activeProfile.token,
                      assetRef: item.asset.asset_ref,
                    },
                    {
                      onSuccess: () => setAnnouncement("图片已加入共享图库。"),
                    },
                  )
                }
                onDownload={() => {
                  void downloadIpAssetOriginal({
                    asset: item.asset,
                    profileToken: activeProfile.token,
                  });
                }}
              />
            ))}
          </div>
        )}
      </section>

      {showProfileSetup ? (
        <ProfileSetupDialog
          onClose={() => setShowProfileSetup(false)}
          onCreated={(created) => {
            setProfile(created);
            setShowProfileSetup(false);
            setAnnouncement("本地素材名片已建立。");
          }}
        />
      ) : null}
    </section>
  );
}

function ReferenceFilmstrip({
  references,
  onChange,
}: Readonly<{
  references: readonly IpAsset[];
  onChange: (assets: readonly IpAsset[]) => void;
}>) {
  return (
    <section className={styles.filmstrip} aria-labelledby="filmstrip-title">
      <div>
        <span id="filmstrip-title">参考胶片</span>
        <small>按顺序传入模型 · 1–3 张</small>
      </div>
      <ol>
        {[0, 1, 2].map((index) => {
          const asset = references[index];
          return (
            <li
              key={index}
              className={asset === undefined ? styles.emptyFrame : undefined}
            >
              <span className={styles.frameNumber}>0{index + 1}</span>
              {asset === undefined ? (
                <p>等待素材</p>
              ) : (
                <>
                  <SharedPreview asset={asset} />
                  <strong>{asset.canonical_name}</strong>
                  <div>
                    <button
                      type="button"
                      disabled={index === 0}
                      onClick={() =>
                        onChange(moveItem(references, index, index - 1))
                      }
                      aria-label={`将 ${asset.canonical_name} 前移`}
                    >
                      ←
                    </button>
                    <button
                      type="button"
                      disabled={index === references.length - 1}
                      onClick={() =>
                        onChange(moveItem(references, index, index + 1))
                      }
                      aria-label={`将 ${asset.canonical_name} 后移`}
                    >
                      →
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        onChange(
                          references.filter(
                            (_item, position) => position !== index,
                          ),
                        )
                      }
                      aria-label={`移除 ${asset.canonical_name}`}
                    >
                      ×
                    </button>
                  </div>
                </>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function OutputStage({
  status,
  statusError,
  output,
  profile,
  sharing,
  onShare,
  onDownload,
}: Readonly<{
  status: ReturnType<typeof useIpAssetGeneration>["data"];
  statusError: boolean;
  output: IpAsset | undefined;
  profile: LocalIpAssetProfile | null;
  sharing: boolean;
  onShare: (assetRef: string) => void;
  onDownload: (asset: IpAsset) => void;
}>) {
  return (
    <section
      className={styles.outputStage}
      aria-labelledby="output-stage-title"
    >
      <div className={styles.outputTopline}>
        <p className={styles.sectionNumber}>OUTPUT / 私人结果</p>
        <span aria-live="polite">
          {status === undefined ? "等待创作" : statusLabel(status.status)}
        </span>
      </div>
      <h2 id="output-stage-title">生成结果</h2>
      {statusError ? (
        <p className={styles.error} role="alert">
          任务状态读取失败。
        </p>
      ) : null}
      {output === undefined ? (
        <div className={styles.outputPlaceholder}>
          <span aria-hidden="true">✦</span>
          <p>
            {status?.status === "failed"
              ? `生成失败：${status.error_code ?? "generation_failed"}`
              : status?.status === "queued" || status?.status === "running"
                ? "模型正在组合参考素材与画面描述…"
                : "完成简报并选择参考图后，作品会在这里出现。"}
          </p>
        </div>
      ) : (
        <div className={styles.outputReady}>
          <PrivatePreview asset={output} profile={profile} eager />
          <strong>{output.canonical_name}</strong>
          <small>{output.shared ? "已在共享图库" : "仅在我的素材架"}</small>
          <div>
            <button type="button" onClick={() => onDownload(output)}>
              下载原图
            </button>
            {!output.shared ? (
              <button
                type="button"
                disabled={sharing}
                onClick={() => onShare(output.asset_ref)}
              >
                {sharing ? "正在加入…" : "加入共享图库"}
              </button>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

function PersonalAssetCard({
  item,
  profile,
  onFavorite,
  onShare,
  onDownload,
}: Readonly<{
  item: IpAssetPersonalItem;
  profile: LocalIpAssetProfile;
  onFavorite: () => void;
  onShare: () => void;
  onDownload: () => void;
}>) {
  const generated = item.membership_sources.includes("generated");
  return (
    <article className={styles.personalCard}>
      <PrivatePreview asset={item.asset} profile={profile} />
      <div>
        <span className={styles.sourceBadge}>
          {generated
            ? "AI 生成"
            : item.membership_sources.includes("uploaded")
              ? "我的上传"
              : "收藏"}
        </span>
        <strong>{item.asset.canonical_name}</strong>
        <small>{item.asset.shared ? "共享可见" : "个人素材"}</small>
        <div>
          <button
            type="button"
            aria-pressed={item.favorite}
            onClick={onFavorite}
          >
            {item.favorite ? "取消收藏" : "收藏"}
          </button>
          <button type="button" onClick={onDownload}>
            下载
          </button>
          {generated && !item.asset.shared ? (
            <button type="button" onClick={onShare}>
              加入共享
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function SharedPreview({ asset }: Readonly<{ asset: IpAsset }>) {
  const [failed, setFailed] = useState(false);
  const url = ipAssetResourceUrl(asset.preview_url);
  return url === null || failed ? (
    <span
      className={styles.previewFallback}
      role="img"
      aria-label={`${asset.canonical_name} 预览不可用`}
    />
  ) : (
    <img
      src={url}
      alt={asset.canonical_name}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

function PrivatePreview({
  asset,
  profile,
  eager = false,
}: Readonly<{
  asset: IpAsset;
  profile: LocalIpAssetProfile | null;
  eager?: boolean;
}>) {
  if (asset.shared) {
    const url = ipAssetResourceUrl(asset.preview_url);
    return url === null ? (
      <span
        className={styles.previewFallback}
        role="img"
        aria-label={`${asset.canonical_name} 预览不可用`}
      />
    ) : (
      <img
        src={url}
        alt={asset.canonical_name}
        loading={eager ? "eager" : "lazy"}
      />
    );
  }
  if (profile === null) {
    return (
      <span
        className={styles.previewFallback}
        role="img"
        aria-label={`${asset.canonical_name} 需要本地素材名片`}
      />
    );
  }
  return (
    <PrivatePreviewLoader
      key={`${asset.preview_url}:${profile.profileRef}`}
      asset={asset}
      eager={eager}
      profile={profile}
    />
  );
}

function PrivatePreviewLoader({
  asset,
  profile,
  eager,
}: Readonly<{
  asset: IpAsset;
  profile: LocalIpAssetProfile;
  eager: boolean;
}>) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    void fetchIpAssetBlob(asset.preview_url, profile.token).then(
      (blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      },
      () => {
        if (active) setFailed(true);
      },
    );
    return () => {
      active = false;
      if (objectUrl !== null) URL.revokeObjectURL(objectUrl);
    };
  }, [asset.preview_url, profile.token]);
  return url === null ? (
    <span
      className={styles.previewFallback}
      role="img"
      aria-label={`${asset.canonical_name} ${failed ? "预览读取失败" : "正在读取"}`}
    />
  ) : (
    <img
      src={url}
      alt={asset.canonical_name}
      loading={eager ? "eager" : "lazy"}
    />
  );
}

function moveItem(
  items: readonly IpAsset[],
  from: number,
  to: number,
): readonly IpAsset[] {
  if (to < 0 || to >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(from, 1);
  if (item === undefined) return items;
  next.splice(to, 0, item);
  return next;
}

function createIdempotencyKey(): string {
  if (typeof crypto.randomUUID === "function")
    return `ip-studio-${crypto.randomUUID()}`;
  return `ip-studio-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function statusLabel(
  status: "queued" | "running" | "succeeded" | "failed",
): string {
  return {
    queued: "排队中",
    running: "生成中",
    succeeded: "已完成",
    failed: "失败",
  }[status];
}

function formText(form: FormData, key: string): string {
  const value = form.get(key);
  return typeof value === "string" ? value : "";
}
