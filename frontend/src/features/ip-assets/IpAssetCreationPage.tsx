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
import { IpAssetLogoutButton } from "./IpAssetLogoutButton";
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

type ReferenceSource = "all" | "favorite" | "uploaded" | "generated";

const referenceSourceOptions: readonly Readonly<{
  value: ReferenceSource;
  label: string;
  description: string;
}>[] = [
  {
    value: "all",
    label: "全部素材",
    description: "共享图库内所有可用于生成的素材",
  },
  {
    value: "favorite",
    label: "我的收藏",
    description: "我收藏且仍在共享图库的素材",
  },
  {
    value: "uploaded",
    label: "我的上传",
    description: "我上传且已进入共享图库的素材",
  },
  {
    value: "generated",
    label: "我的共享 AI 作品",
    description: "我生成并主动共享的作品",
  },
];

const demoCreationBrief =
  "小赛在明亮的未来科学课堂里演示火箭实验，开心挥手，保留角色原有 3D 形象与配色，画面简洁、有活力，适合作为微信公众号方形配图，不添加文字或标志。";

export function IpAssetCreationPage() {
  const capabilities = useIpAssetCapabilities();
  const [profile, setProfile] = useState<LocalIpAssetProfile | null>(
    loadLocalIpAssetProfile,
  );
  const restoredProfile = useRestoreIpAssetProfile(profile);
  const activeProfile = restoredProfile.isError ? null : profile;
  const [showProfileSetup, setShowProfileSetup] = useState(false);
  const [referenceQuery, setReferenceQuery] = useState("");
  const [referenceSource, setReferenceSource] =
    useState<ReferenceSource>("all");
  const [references, setReferences] = useState<readonly IpAsset[]>([]);
  const [initialReferenceRef, setInitialReferenceRef] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get("reference"),
  );
  const initialReference = useIpAssetDetail(initialReferenceRef, activeProfile);
  const [character, setCharacter] = useState<IpAssetCharacter>("xiao_sai");
  const [assetType, setAssetType] = useState<IpAssetType>("scene_illustration");
  const [prompt, setPrompt] = useState("");
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
    capabilities.data?.enabled === true && referenceSource === "all",
    activeProfile,
  );
  const referencePersonal = usePersonalIpAssets(
    activeProfile,
    referenceSource === "all" ? "favorite" : referenceSource,
    capabilities.data?.enabled === true && referenceSource !== "all",
  );
  const personal = usePersonalIpAssets(activeProfile, personalSource);
  const pickerAssets = useMemo(() => {
    const assets =
      referenceSource === "all"
        ? (library.data?.pages.flatMap((page) => page.items) ?? [])
        : (referencePersonal.data?.pages.flatMap((page) =>
            page.items.map((item) => ({
              ...item.asset,
              favorite: item.favorite,
            })),
          ) ?? []);
    return projectReferenceCandidates(
      assets,
      referenceSource === "all" ? "" : referenceQuery,
    );
  }, [
    library.data?.pages,
    referencePersonal.data?.pages,
    referenceQuery,
    referenceSource,
  ]);
  const personalItems = useMemo(
    () => personal.data?.pages.flatMap((page) => page.items) ?? [],
    [personal.data?.pages],
  );
  const activeReferenceOption =
    referenceSourceOptions.find((option) => option.value === referenceSource) ??
    referenceSourceOptions[0]!;
  const pickerIsLoading =
    referenceSource === "all" ? library.isLoading : referencePersonal.isLoading;
  const pickerIsError =
    referenceSource === "all" ? library.isError : referencePersonal.isError;
  const pickerHasNextPage =
    referenceSource === "all"
      ? library.hasNextPage
      : referencePersonal.hasNextPage;
  const pickerIsFetchingNextPage =
    referenceSource === "all"
      ? library.isFetchingNextPage
      : referencePersonal.isFetchingNextPage;

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

  const requireProfile = (
    action: () => void,
    message = "请先建立浏览器本地名片，再继续这项操作。",
  ) => {
    if (activeProfile === null) {
      setAnnouncement(message);
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
            setAnnouncement(
              result.favorite
                ? `已收藏「${asset.canonical_name}」。`
                : `已取消收藏「${asset.canonical_name}」。`,
            ),
          onError: () => setAnnouncement("收藏状态更新失败，请稍后重试。"),
        },
      );
    });

  const changeReferenceSource = (nextSource: ReferenceSource) => {
    const option = referenceSourceOptions.find(
      (candidate) => candidate.value === nextSource,
    );
    if (option === undefined || nextSource === referenceSource) return;
    if (nextSource !== "all" && activeProfile === null) {
      setAnnouncement(`查看「${option.label}」前，请先建立浏览器本地名片。`);
      setShowProfileSetup(true);
      return;
    }
    setReferenceSource(nextSource);
    setAnnouncement(`已切换到「${option.label}」，已选参考保持不变。`);
  };

  const toggleReference = (asset: IpAsset) => {
    const selectedIndex = references.findIndex(
      (item) => item.asset_ref === asset.asset_ref,
    );
    if (selectedIndex >= 0) {
      setReferences(
        references.filter((item) => item.asset_ref !== asset.asset_ref),
      );
      setAnnouncement(`已移除「${asset.canonical_name}」。`);
      return;
    }
    if (references.length >= 3) {
      setAnnouncement("最多选择三张参考图，请先移除一张再添加。");
      return;
    }
    const nextOrdinal = references.length + 1;
    setReferences([...references, asset]);
    setAnnouncement(
      `已将「${asset.canonical_name}」加入参考 0${nextOrdinal}。`,
    );
  };

  const moveReference = (from: number, to: number) => {
    const asset = references[from];
    if (asset === undefined) return;
    const moved = moveItem(references, from, to);
    if (moved === references) return;
    setReferences(moved);
    setAnnouncement(`已将「${asset.canonical_name}」调整为参考 0${to + 1}。`);
  };

  const removeReference = (index: number) => {
    const asset = references[index];
    if (asset === undefined) return;
    setReferences(references.filter((_item, position) => position !== index));
    setAnnouncement(`已从参考胶片移除「${asset.canonical_name}」。`);
  };

  const loadMoreReferences = () => {
    setAnnouncement(`正在加载更多「${activeReferenceOption.label}」。`);
    const request =
      referenceSource === "all"
        ? library.fetchNextPage()
        : referencePersonal.fetchNextPage();
    void request.then((result) => {
      setAnnouncement(
        result.isError
          ? "更多素材加载失败，请稍后重试。"
          : `已加载更多「${activeReferenceOption.label}」。`,
      );
    });
  };

  return (
    <section className={styles.studio} aria-labelledby="studio-title">
      <header className={styles.header}>
        <div className={styles.topBar}>
          <a className={styles.backLink} href="/ip-assets">
            ← 返回共享图库
          </a>
          <IpAssetLogoutButton className={styles.logoutButton} />
        </div>
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
      <div
        className={styles.feedbackBar}
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <span aria-hidden="true">●</span>
        <p>
          {announcement ||
            "操作反馈会显示在这里；选择素材后可在参考胶片中调整顺序。"}
        </p>
      </div>

      <section
        className={styles.creationStage}
        aria-labelledby="creation-stage-title"
      >
        <form
          className={styles.briefPanel}
          onSubmit={(event) => {
            event.preventDefault();
            requireProfile(() => {
              if (activeProfile === null) return;
              if (references.length < 1 || references.length > 3) {
                setAnnouncement("请先选择一至三张参考图。");
                return;
              }
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
              setAnnouncement("正在保存创作任务，请勿重复提交。");
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
                    setAnnouncement(
                      "创作任务已保存，正在等待独立后台生成服务领取。",
                    );
                  },
                  onError: () =>
                    setAnnouncement("创作任务提交失败，修改前可直接重试。"),
                },
              );
            }, "生成结果需要保存到个人素材架，请先建立浏览器本地名片。");
          }}
        >
          <div className={styles.sectionNumber}>01 / 创作简报</div>
          <h2 id="creation-stage-title">把画面说清楚</h2>
          <div className={styles.promptField}>
            <div>
              <label htmlFor="ip-asset-generation-prompt">画面描述</label>
              <button
                type="button"
                onClick={() => {
                  setPrompt(demoCreationBrief);
                  setAnnouncement(
                    "示例创作简报已填入，可以继续修改；尚未提交生成任务。",
                  );
                }}
              >
                载入示例简报
              </button>
            </div>
            <textarea
              id="ip-asset-generation-prompt"
              name="prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              required
              minLength={8}
              maxLength={2000}
              placeholder="例如：小赛在未来感科学课堂演示火箭实验，开心、明亮、适合公众号头图…"
            />
          </div>
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
            onMove={moveReference}
            onRemove={removeReference}
          />

          {references.length === 3 ? (
            <p className={styles.referenceLimit} role="note">
              已选满 3 张参考图。若要加入其他素材，请先从参考胶片移除一张。
            </p>
          ) : (
            <p className={styles.referenceGuidance}>
              已选 {references.length} / 3 张；至少选择 1
              张，顺序会影响模型参考优先级。
            </p>
          )}

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
          {capabilities.data?.generation_available === true ? (
            <p className={styles.capabilityNote}>
              生图接口已配置。提交后任务会保存到队列，由独立后台生成服务处理；这里不表示该服务当前在线。
            </p>
          ) : capabilities.data?.generation_available === false ? (
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
          submitting={generation.isPending}
          output={output.data}
          profile={activeProfile}
          sharing={share.isPending}
          onShare={(assetRef) => {
            if (activeProfile === null) return;
            setAnnouncement("正在将生成结果加入共享图库。");
            share.mutate(
              { token: activeProfile.token, assetRef },
              {
                onSuccess: () => setAnnouncement("图片已加入共享图库。"),
                onError: () =>
                  setAnnouncement("加入共享图库失败，请稍后重试。"),
              },
            );
          }}
          onDownload={(asset) => {
            setAnnouncement("正在准备生成结果原图。");
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
        <div
          className={styles.referenceSources}
          role="group"
          aria-label="创作素材来源"
        >
          {referenceSourceOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={referenceSource === option.value}
              onClick={() => changeReferenceSource(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className={styles.sourceSummary} id="active-reference-source">
          <p>
            <strong>{activeReferenceOption.label}</strong>
            <span>{activeReferenceOption.description}</span>
          </p>
          <span>
            当前显示 {pickerAssets.length} 张 · 已选 {references.length} / 3
          </span>
        </div>

        {pickerIsLoading ? (
          <p className={styles.pickerState} role="status">
            正在读取「{activeReferenceOption.label}」…
          </p>
        ) : pickerIsError ? (
          <div className={styles.pickerState} role="alert">
            <p>这个素材分类读取失败，已选参考不受影响。</p>
            <button
              type="button"
              onClick={() => {
                setAnnouncement(
                  `正在重新读取「${activeReferenceOption.label}」。`,
                );
                void (referenceSource === "all"
                  ? library.refetch()
                  : referencePersonal.refetch());
              }}
            >
              重新读取
            </button>
          </div>
        ) : pickerAssets.length === 0 ? (
          <p className={styles.pickerState} role="status">
            {referenceSource === "all"
              ? "没有找到符合当前搜索的共享素材。"
              : "这个分类暂时没有符合搜索的共享、可生成素材；私人未共享图片不会出现在这里。"}
          </p>
        ) : (
          <div
            className={styles.referenceLibrary}
            aria-describedby="active-reference-source"
          >
            {pickerAssets.map((asset) => {
              const selectedIndex = references.findIndex(
                (item) => item.asset_ref === asset.asset_ref,
              );
              const selected = selectedIndex >= 0;
              return (
                <article
                  key={asset.asset_ref}
                  className={`${styles.referenceCard} ${selected ? styles.referenceCardSelected : ""}`}
                >
                  <div className={styles.referencePreview}>
                    <SharedPreview asset={asset} />
                    {selected ? (
                      <span className={styles.selectionBadge}>
                        <span aria-hidden="true">✓</span> 已选 · 参考 0
                        {selectedIndex + 1}
                      </span>
                    ) : null}
                  </div>
                  <div>
                    <small>{selected ? "已进入参考胶片" : "共享素材"}</small>
                    <strong>{asset.canonical_name}</strong>
                    <div className={styles.referenceActions}>
                      <button
                        type="button"
                        aria-pressed={selected}
                        disabled={!selected && references.length >= 3}
                        onClick={() => toggleReference(asset)}
                      >
                        {selected ? "移出参考" : "加入参考"}
                      </button>
                      <button
                        type="button"
                        aria-pressed={asset.favorite}
                        disabled={
                          favorites.isPending &&
                          favorites.variables?.assetRef === asset.asset_ref
                        }
                        onClick={() => toggleFavorite(asset)}
                      >
                        {favorites.isPending &&
                        favorites.variables?.assetRef === asset.asset_ref
                          ? "保存中…"
                          : asset.favorite
                            ? "取消收藏"
                            : "收藏"}
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
        {pickerHasNextPage ? (
          <button
            className={styles.loadMore}
            type="button"
            disabled={pickerIsFetchingNextPage}
            onClick={loadMoreReferences}
          >
            {pickerIsFetchingNextPage
              ? "正在加载更多…"
              : `加载更多${activeReferenceOption.label}`}
          </button>
        ) : null}
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
                  (() => {
                    setAnnouncement(
                      `正在将「${item.asset.canonical_name}」加入共享图库。`,
                    );
                    share.mutate(
                      {
                        token: activeProfile.token,
                        assetRef: item.asset.asset_ref,
                      },
                      {
                        onSuccess: () =>
                          setAnnouncement("图片已加入共享图库。"),
                        onError: () =>
                          setAnnouncement("加入共享图库失败，请稍后重试。"),
                      },
                    );
                  })()
                }
                onDownload={() => {
                  setAnnouncement(
                    `正在准备「${item.asset.canonical_name}」原图。`,
                  );
                  void downloadIpAssetOriginal({
                    asset: item.asset,
                    profileToken: activeProfile.token,
                  }).then(
                    () => setAnnouncement("原图下载已开始。"),
                    () => setAnnouncement("原图下载失败，请稍后重试。"),
                  );
                }}
                sharing={
                  share.isPending &&
                  share.variables?.assetRef === item.asset.asset_ref
                }
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
  onMove,
  onRemove,
}: Readonly<{
  references: readonly IpAsset[];
  onMove: (from: number, to: number) => void;
  onRemove: (index: number) => void;
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
                      onClick={() => onMove(index, index - 1)}
                      aria-label={`将 ${asset.canonical_name} 前移`}
                    >
                      ←
                    </button>
                    <button
                      type="button"
                      disabled={index === references.length - 1}
                      onClick={() => onMove(index, index + 1)}
                      aria-label={`将 ${asset.canonical_name} 后移`}
                    >
                      →
                    </button>
                    <button
                      type="button"
                      onClick={() => onRemove(index)}
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
  submitting,
  output,
  profile,
  sharing,
  onShare,
  onDownload,
}: Readonly<{
  status: ReturnType<typeof useIpAssetGeneration>["data"];
  statusError: boolean;
  submitting: boolean;
  output: IpAsset | undefined;
  profile: LocalIpAssetProfile | null;
  sharing: boolean;
  onShare: (assetRef: string) => void;
  onDownload: (asset: IpAsset) => void;
}>) {
  const displayStatus = statusError
    ? "状态读取失败"
    : submitting
      ? "正在提交"
      : status === undefined
        ? "等待创作"
        : statusLabel(status.status);
  const placeholderCopy = statusError
    ? "暂时无法读取任务状态，系统会保留已经提交的任务；请稍后刷新页面确认。"
    : submitting
      ? "正在保存创作任务，完成后才会进入后台生成队列。"
      : status?.status === "failed"
        ? "本次生成没有完成。可以检查画面描述与参考素材后，使用同一简报重试。"
        : status?.status === "queued"
          ? "任务已保存，正在等待独立后台生成服务领取。后台服务未启动时，任务会继续安全排队。"
          : status?.status === "running"
            ? "后台生成服务已领取任务，模型正在组合参考素材与画面描述。"
            : status?.status === "succeeded"
              ? "图片已经生成，正在读取你的私人结果。"
              : "完成简报并选择参考图后，作品会在这里出现。";
  const visibleOutput = submitting ? undefined : output;
  return (
    <section
      className={styles.outputStage}
      aria-labelledby="output-stage-title"
      aria-busy={
        !statusError &&
        (submitting ||
          status?.status === "queued" ||
          status?.status === "running")
      }
    >
      <div className={styles.outputTopline}>
        <p className={styles.sectionNumber}>OUTPUT / 私人结果</p>
        <span className={styles.outputStatus} aria-live="polite">
          <i aria-hidden="true" />
          {displayStatus}
        </span>
      </div>
      <h2 id="output-stage-title">生成结果</h2>
      {statusError ? (
        <p className={styles.error} role="alert">
          任务状态读取失败。
        </p>
      ) : null}
      {visibleOutput === undefined ? (
        <div className={styles.outputPlaceholder}>
          <span aria-hidden="true">✦</span>
          <p>{placeholderCopy}</p>
        </div>
      ) : (
        <div className={styles.outputReady}>
          <PrivatePreview asset={visibleOutput} profile={profile} eager />
          <strong>{visibleOutput.canonical_name}</strong>
          <small>
            {visibleOutput.shared ? "已在共享图库" : "仅在我的素材架"}
          </small>
          <div>
            <button type="button" onClick={() => onDownload(visibleOutput)}>
              下载原图
            </button>
            {!visibleOutput.shared ? (
              <button
                type="button"
                disabled={sharing}
                onClick={() => onShare(visibleOutput.asset_ref)}
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
  sharing,
}: Readonly<{
  item: IpAssetPersonalItem;
  profile: LocalIpAssetProfile;
  onFavorite: () => void;
  onShare: () => void;
  onDownload: () => void;
  sharing: boolean;
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
            <button type="button" disabled={sharing} onClick={onShare}>
              {sharing ? "正在加入…" : "加入共享"}
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function SharedPreview({ asset }: Readonly<{ asset: IpAsset }>) {
  const [failed, setFailed] = useState(false);
  const url = ipAssetResourceUrl(asset.thumbnail_url);
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
    const url = ipAssetResourceUrl(asset.thumbnail_url);
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

function projectReferenceCandidates(
  assets: readonly IpAsset[],
  query: string,
): readonly IpAsset[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const unique = new Map<string, IpAsset>();
  for (const asset of assets) {
    if (!asset.shared || asset.status !== "ready") continue;
    if (unique.has(asset.asset_ref)) continue;
    if (
      normalizedQuery.length > 0 &&
      !referenceSearchText(asset).includes(normalizedQuery)
    ) {
      continue;
    }
    unique.set(asset.asset_ref, asset);
  }
  return [...unique.values()];
}

function referenceSearchText(asset: IpAsset): string {
  return [
    asset.canonical_name,
    asset.character,
    asset.asset_type,
    asset.department,
    asset.contributor,
    asset.emotion,
    asset.action,
    asset.scene,
    asset.intended_use,
    asset.style,
    ...asset.tags,
  ]
    .join(" ")
    .toLocaleLowerCase();
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
