import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  emptyIpAssetFilters,
  ipAssetResourceUrl,
  type IpAsset,
  type IpAssetCharacter,
  type IpAssetFilters,
  type IpAssetLeaderboard,
  type IpAssetLeaderboardPeriod,
  type IpAssetOrientation,
  type IpAssetRecognition,
  type IpAssetSource,
  type IpAssetType,
} from "./api";
import {
  useIpAssetCapabilities,
  useIpAssetDetail,
  useIpAssetImageSearch,
  useIpAssetLeaderboard,
  useIpAssetPackageDownload,
  useIpAssets,
  useRestoreIpAssetProfile,
  useSetIpAssetFavorite,
  useIpAssetTextSearch,
  useRecognizeIpAsset,
  useUploadIpAsset,
} from "./hooks";
import { ProfileSetupDialog } from "./ProfileSetupDialog";
import { IpAssetLogoutButton } from "./IpAssetLogoutButton";
import {
  clearLocalIpAssetProfile,
  loadLocalIpAssetProfile,
  type LocalIpAssetProfile,
} from "./profile";
import {
  createIpAssetFlipbookDraft,
  IP_ASSET_FLIPBOOK_MAX_PAGES,
  IP_ASSET_FLIPBOOK_MIN_PAGES,
  openIpAssetFlipbook,
} from "./flipbookDraft";

import styles from "./IpAssetHub.module.css";

const characterOptions: readonly Readonly<{
  value: IpAssetCharacter;
  label: string;
}>[] = [
  { value: "sai_xiansheng", label: "赛先生" },
  { value: "xiao_sai", label: "小赛" },
  { value: "duo", label: "双角色" },
  { value: "other", label: "其他 IP" },
];

const assetTypeOptions: readonly Readonly<{
  value: IpAssetType;
  label: string;
}>[] = [
  { value: "identity_reference", label: "形象设定" },
  { value: "portrait_avatar", label: "头像" },
  { value: "full_body_action", label: "全身动作" },
  { value: "expression", label: "表情" },
  { value: "meme_sticker", label: "表情包" },
  { value: "transparent_cutout", label: "透明底素材" },
  { value: "scene_illustration", label: "场景插画" },
  { value: "poster_element", label: "海报元素" },
  { value: "other", label: "其他" },
];

const sourceOptions: readonly Readonly<{
  value: IpAssetSource;
  label: string;
}>[] = [
  { value: "uploaded", label: "同事上传" },
  { value: "generated", label: "AI 生成" },
  { value: "seed_import", label: "已有图库导入" },
];

const orientationOptions: readonly Readonly<{
  value: IpAssetOrientation;
  label: string;
}>[] = [
  { value: "square", label: "方图" },
  { value: "portrait", label: "竖图" },
  { value: "landscape", label: "横图" },
];

const exampleSearchPrompts = [
  "小赛开心庆祝，适合社群推送的透明底图片",
  "赛先生在实验室认真思考，适合科学课堂",
  "赛先生与小赛一起探索太空，用于公众号封面",
] as const;

const labels = {
  character: Object.fromEntries(
    characterOptions.map((item) => [item.value, item.label]),
  ) as Readonly<Record<IpAssetCharacter, string>>,
  assetType: Object.fromEntries(
    assetTypeOptions.map((item) => [item.value, item.label]),
  ) as Readonly<Record<IpAssetType, string>>,
  source: Object.fromEntries(
    sourceOptions.map((item) => [item.value, item.label]),
  ) as Readonly<Record<IpAssetSource, string>>,
};

export function IpAssetHub() {
  const capabilities = useIpAssetCapabilities();
  const [profile, setProfile] = useState<LocalIpAssetProfile | null>(
    loadLocalIpAssetProfile,
  );
  const restoredProfile = useRestoreIpAssetProfile(profile);
  const activeProfile = restoredProfile.isError ? null : profile;
  const [showProfileSetup, setShowProfileSetup] = useState(false);
  const [filters, setFilters] = useState<IpAssetFilters>(emptyIpAssetFilters);
  const assets = useIpAssets(
    filters,
    capabilities.data?.enabled === true,
    activeProfile,
  );
  const textSearch = useIpAssetTextSearch();
  const imageSearch = useIpAssetImageSearch();
  const packageDownload = useIpAssetPackageDownload(activeProfile);
  const upload = useUploadIpAsset();
  const favorite = useSetIpAssetFavorite();
  const [leaderboardPeriod, setLeaderboardPeriod] =
    useState<IpAssetLeaderboardPeriod>("30d");
  const leaderboard = useIpAssetLeaderboard(leaderboardPeriod);
  const [searchMessage, setSearchMessage] = useState("");
  const [priorTurns, setPriorTurns] = useState<readonly string[]>([]);
  const [selectedAssetRef, setSelectedAssetRef] = useState<string | null>(null);
  const [selectedAssets, setSelectedAssets] = useState<
    ReadonlyMap<string, IpAsset>
  >(() => new Map());
  const [flipbookMessage, setFlipbookMessage] = useState("");
  const [activeTool, setActiveTool] = useState<"upload" | null>(null);
  const detail = useIpAssetDetail(selectedAssetRef, activeProfile);
  const closeDetail = useCallback(() => setSelectedAssetRef(null), []);
  const closeTool = useCallback(() => setActiveTool(null), []);
  const searchResult = imageSearch.data ?? textSearch.data;
  const searchError = imageSearch.error ?? textSearch.error;
  const [favoriteProjection, setFavoriteProjection] = useState<{
    profileRef: string;
    values: Readonly<Record<string, boolean>>;
  } | null>(null);
  const displayedAssets = useMemo(() => {
    const favoriteOverrides =
      favoriteProjection !== null &&
      favoriteProjection.profileRef === activeProfile?.profileRef
        ? favoriteProjection.values
        : {};
    const candidates =
      searchResult?.items.map((item) => item.asset) ??
      assets.data?.pages.flatMap((page) => page.items) ??
      [];
    return [
      ...new Map(
        candidates.map((item) => {
          const favoriteOverride = favoriteOverrides[item.asset_ref];
          return [
            item.asset_ref,
            favoriteOverride === undefined
              ? item
              : { ...item, favorite: favoriteOverride },
          ] as const;
        }),
      ).values(),
    ];
  }, [
    activeProfile?.profileRef,
    assets.data?.pages,
    favoriteProjection,
    searchResult?.items,
  ]);
  const searchMatches = useMemo(
    () =>
      new Map(
        searchResult?.items.map((item) => [
          item.asset.asset_ref,
          {
            explanation: item.explanation,
            similarity: item.similarity ?? null,
          },
        ]) ?? [],
      ),
    [searchResult?.items],
  );
  const flipbookSelectionAllowed =
    selectedAssets.size >= IP_ASSET_FLIPBOOK_MIN_PAGES &&
    selectedAssets.size <= IP_ASSET_FLIPBOOK_MAX_PAGES;
  const flipbookSelectionGuide =
    selectedAssets.size < IP_ASSET_FLIPBOOK_MIN_PAGES
      ? `再选择 ${IP_ASSET_FLIPBOOK_MIN_PAGES - selectedAssets.size} 张图片即可制作相册`
      : selectedAssets.size > IP_ASSET_FLIPBOOK_MAX_PAGES
        ? `相册最多使用 ${IP_ASSET_FLIPBOOK_MAX_PAGES} 张，请移除 ${selectedAssets.size - IP_ASSET_FLIPBOOK_MAX_PAGES} 张`
        : `已满足 ${IP_ASSET_FLIPBOOK_MIN_PAGES}–${IP_ASSET_FLIPBOOK_MAX_PAGES} 张相册范围`;

  const openSelectedFlipbook = () => {
    try {
      const draft = createIpAssetFlipbookDraft([...selectedAssets.values()]);
      setFlipbookMessage("");
      openIpAssetFlipbook(draft);
    } catch {
      setFlipbookMessage(
        "这些图片暂时无法制作相册，请清空后重新选择可用的共享图片。",
      );
    }
  };

  const updateFilter = <Key extends keyof IpAssetFilters>(
    key: Key,
    value: IpAssetFilters[Key],
  ) => {
    setFilters((current) => ({ ...current, [key]: value }));
    textSearch.reset();
    imageSearch.reset();
  };

  useEffect(() => {
    if (!restoredProfile.isError || profile === null) return;
    clearLocalIpAssetProfile();
  }, [profile, restoredProfile.isError]);

  const toggleFavorite = (asset: IpAsset) => {
    if (activeProfile === null) {
      setShowProfileSetup(true);
      return;
    }
    const nextFavorite = !asset.favorite;
    favorite.mutate(
      {
        token: activeProfile.token,
        assetRef: asset.asset_ref,
        favorite: nextFavorite,
      },
      {
        onSuccess: () => {
          setFavoriteProjection((current) => ({
            profileRef: activeProfile.profileRef,
            values: {
              ...(current?.profileRef === activeProfile.profileRef
                ? current.values
                : {}),
              [asset.asset_ref]: nextFavorite,
            },
          }));
        },
      },
    );
  };

  return (
    <section className={styles.hub} aria-labelledby="ip-asset-hub-title">
      <header className={styles.header}>
        <div className={styles.titleGroup}>
          <div className={styles.productMark} aria-hidden="true">
            <span />
            IP
          </div>
          <div>
            <div className={styles.titleLine}>
              <p className={styles.kicker}>SAI VISUAL LIBRARY</p>
              <span className={styles.boundaryPill}>公司内网 · 演示登录</span>
            </div>
            <h1 id="ip-asset-hub-title">IP 数字资产中心</h1>
          </div>
        </div>
        <div className={styles.headerActions}>
          <button
            type="button"
            className={styles.secondaryAction}
            onClick={() => setActiveTool("upload")}
          >
            <span aria-hidden="true">↑</span>
            上传图片
          </button>
          <a className={styles.primaryAction} href="/ip-assets/create">
            <span aria-hidden="true">✦</span>
            AI 创作
          </a>
          <IpAssetLogoutButton className={styles.logoutAction} />
        </div>
        <div className={styles.headerCopy}>
          <p className={styles.intro}>
            汇集赛先生与小赛视觉资产，用自然语言找到合适的图片，再下载、复用或继续创作。
          </p>
          <p className={styles.boundaryNote} role="note">
            登录入口不验证身份；上传人与部门仍为自填信息。请勿部署到公网。
          </p>
        </div>
      </header>

      {capabilities.isLoading ? (
        <p role="status">正在读取资产中心能力…</p>
      ) : null}
      {capabilities.isError ? (
        <p className={styles.error} role="alert">
          无法连接资产中心 API，请确认本地服务已启动。
        </p>
      ) : null}
      {capabilities.data !== undefined && !capabilities.data.enabled ? (
        <p className={styles.error} role="alert">
          服务器尚未启用 IP 数字资产中心。
        </p>
      ) : null}

      {capabilities.data?.enabled === true ? (
        <>
          {!capabilities.data.generation_available ? (
            <div className={styles.capabilityHint}>
              <span aria-hidden="true" />
              AI 创作暂未启用，上传、检索和下载不受影响
            </div>
          ) : null}
          <SearchConsole
            filters={filters}
            message={searchMessage}
            semanticAvailable={capabilities.data.semantic_search_available}
            searching={textSearch.isPending || imageSearch.isPending}
            onMessageChange={setSearchMessage}
            onFilterChange={updateFilter}
            onReset={() => {
              setFilters(emptyIpAssetFilters);
              setSearchMessage("");
              setPriorTurns([]);
              textSearch.reset();
              imageSearch.reset();
            }}
            onTextSearch={() => {
              const message = searchMessage.trim();
              if (message.length === 0) return;
              imageSearch.reset();
              textSearch.mutate(
                {
                  message,
                  priorTurns,
                  filters,
                  ...(activeProfile === null
                    ? {}
                    : { profileToken: activeProfile.token }),
                },
                {
                  onSuccess: () => {
                    setPriorTurns((turns) => [...turns, message].slice(-4));
                  },
                },
              );
            }}
            onImageSearch={(file) => {
              textSearch.reset();
              imageSearch.mutate({
                file,
                filters,
                ...(activeProfile === null
                  ? {}
                  : { profileToken: activeProfile.token }),
              });
            }}
          />

          {searchError !== null ? (
            <p className={styles.searchError} role="alert">
              检索失败：{searchError.message}
              。图库浏览仍可继续，请检查图片或稍后重试。
            </p>
          ) : null}

          {searchResult !== undefined ? (
            <div
              className={styles.searchStatus}
              role="status"
              aria-live="polite"
            >
              <div>
                <span className={styles.statusDot} aria-hidden="true" />
                <strong>
                  {searchResult.mode === "semantic"
                    ? "语义 + 元数据结果"
                    : "元数据降级结果"}
                </strong>
                <span>{searchResult.items.length} 项</span>
                {searchResult.degraded_reason !== null ? (
                  <small>
                    语义服务暂不可用：{searchResult.degraded_reason}
                  </small>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => {
                  textSearch.reset();
                  imageSearch.reset();
                }}
              >
                返回完整图库
              </button>
            </div>
          ) : null}

          <div className={styles.libraryLayout}>
            <section
              className={styles.galleryRegion}
              aria-labelledby="library-title"
            >
              <div className={styles.galleryHeader}>
                <div>
                  <p>共享资产库</p>
                  <h2 id="library-title">全部图片</h2>
                </div>
                <span>{displayedAssets.length} 项资产</span>
              </div>

              {assets.isLoading ? <p role="status">正在装载视觉档案…</p> : null}
              {assets.isError ? (
                <p className={styles.error} role="alert">
                  图库读取失败，请稍后重试。
                </p>
              ) : null}
              {!assets.isLoading &&
              !assets.isError &&
              displayedAssets.length === 0 ? (
                <div className={styles.empty}>
                  <div className={styles.emptyIllustration} aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                  <div>
                    <strong>还没有找到合适的图片</strong>
                    <p>可以调整检索条件，或上传第一张 IP 资产。</p>
                  </div>
                  <div className={styles.emptyActions}>
                    <button
                      type="button"
                      onClick={() => setActiveTool("upload")}
                    >
                      上传图片
                    </button>
                    <a href="/ip-assets/create">AI 创作</a>
                  </div>
                </div>
              ) : (
                <AssetGrid
                  assets={displayedAssets}
                  searchMatches={searchMatches}
                  selectedAssets={selectedAssets}
                  activeRef={selectedAssetRef}
                  onOpen={setSelectedAssetRef}
                  onFavorite={toggleFavorite}
                  onToggle={(asset) => {
                    setFlipbookMessage("");
                    setSelectedAssets((current) => {
                      const next = new Map(current);
                      if (next.has(asset.asset_ref)) {
                        next.delete(asset.asset_ref);
                      } else {
                        next.set(asset.asset_ref, asset);
                      }
                      return next;
                    });
                  }}
                />
              )}
              {searchResult === undefined && assets.hasNextPage ? (
                <button
                  type="button"
                  className={styles.loadMore}
                  disabled={assets.isFetchingNextPage}
                  onClick={() => void assets.fetchNextPage()}
                >
                  {assets.isFetchingNextPage
                    ? "正在装载下一页…"
                    : "继续装载图库"}
                </button>
              ) : null}
            </section>
            <LeaderboardRail
              entries={leaderboard.data?.items ?? []}
              loading={leaderboard.isLoading}
              period={leaderboardPeriod}
              onOpen={setSelectedAssetRef}
              onPeriodChange={setLeaderboardPeriod}
            />
          </div>

          {selectedAssets.size > 0 ? (
            <div
              className={styles.downloadTray}
              role="region"
              aria-label="已选资产操作"
            >
              <span>{selectedAssets.size} 项已选择</span>
              <button
                type="button"
                className={styles.flipbookButton}
                disabled={!flipbookSelectionAllowed}
                aria-describedby="flipbook-selection-guide"
                onClick={openSelectedFlipbook}
              >
                制作翻页相册
              </button>
              <button
                type="button"
                disabled={packageDownload.isPending}
                onClick={() =>
                  packageDownload.mutate([...selectedAssets.keys()])
                }
              >
                {packageDownload.isPending ? "正在打包…" : "下载 ZIP + 清单"}
              </button>
              <button
                type="button"
                className={styles.clearSelectionButton}
                onClick={() => {
                  setSelectedAssets(new Map());
                  setFlipbookMessage("");
                }}
              >
                清空
              </button>
              <span
                className={styles.selectionGuide}
                id="flipbook-selection-guide"
                aria-live="polite"
              >
                {flipbookSelectionGuide}
              </span>
              {flipbookMessage === "" ? null : (
                <span className={styles.error} role="alert">
                  {flipbookMessage}
                </span>
              )}
              {packageDownload.isError ? (
                <span className={styles.error} role="alert">
                  ZIP 下载失败，请稍后重试。
                </span>
              ) : null}
              {packageDownload.isSuccess ? (
                <span className={styles.success} role="status">
                  ZIP 下载已开始。
                </span>
              ) : null}
            </div>
          ) : null}

          {selectedAssetRef !== null ? (
            <AssetDetail
              loading={detail.isLoading}
              asset={detail.data}
              onFavorite={() => {
                if (detail.data !== undefined) toggleFavorite(detail.data);
              }}
              onClose={closeDetail}
            />
          ) : null}

          {activeTool === "upload" ? (
            <ToolDialog
              labelledBy="ip-upload-title"
              eyebrow="新增到共享资产库"
              onClose={closeTool}
            >
              <UploadPanel
                mutation={upload}
                recognitionAvailable={capabilities.data.recognition_available}
                profile={activeProfile}
              />
            </ToolDialog>
          ) : null}

          {showProfileSetup ? (
            <ProfileSetupDialog
              onClose={() => setShowProfileSetup(false)}
              onCreated={(created) => {
                setProfile(created);
                setShowProfileSetup(false);
              }}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function LeaderboardRail({
  entries,
  loading,
  period,
  onOpen,
  onPeriodChange,
}: Readonly<{
  entries: IpAssetLeaderboard["items"];
  loading: boolean;
  period: IpAssetLeaderboardPeriod;
  onOpen: (assetRef: string) => void;
  onPeriodChange: (period: IpAssetLeaderboardPeriod) => void;
}>) {
  return (
    <div className={styles.leaderboard} aria-labelledby="leaderboard-title">
      <div className={styles.leaderboardHeading}>
        <div>
          <p>DOWNLOAD INDEX</p>
          <h2 id="leaderboard-title">下载排行</h2>
        </div>
        <div className={styles.leaderboardTabs} aria-label="排行榜周期">
          <button
            type="button"
            aria-pressed={period === "30d"}
            onClick={() => onPeriodChange("30d")}
          >
            30 天
          </button>
          <button
            type="button"
            aria-pressed={period === "all"}
            onClick={() => onPeriodChange("all")}
          >
            全部
          </button>
        </div>
      </div>
      {loading ? <p role="status">正在统计下载热度…</p> : null}
      {!loading && entries.length === 0 ? (
        <p className={styles.leaderboardEmpty}>还没有下载记录。</p>
      ) : (
        <ol>
          {entries.map((entry, index) => (
            <li key={entry.asset.asset_ref}>
              <button
                type="button"
                onClick={() => onOpen(entry.asset.asset_ref)}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <span>
                  <strong>{entry.asset.canonical_name}</strong>
                  <small>{entry.download_count} 次下载</small>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
      <p className={styles.leaderboardNote}>仅汇总次数，不记录下载者身份。</p>
    </div>
  );
}

function SearchConsole({
  filters,
  message,
  semanticAvailable,
  searching,
  onMessageChange,
  onFilterChange,
  onReset,
  onTextSearch,
  onImageSearch,
}: Readonly<{
  filters: IpAssetFilters;
  message: string;
  semanticAvailable: boolean;
  searching: boolean;
  onMessageChange: (value: string) => void;
  onFilterChange: <Key extends keyof IpAssetFilters>(
    key: Key,
    value: IpAssetFilters[Key],
  ) => void;
  onReset: () => void;
  onTextSearch: () => void;
  onImageSearch: (file: File) => void;
}>) {
  const [exampleNotice, setExampleNotice] = useState("");
  return (
    <section className={styles.searchConsole} aria-labelledby="ip-search-title">
      <form
        className={styles.chatForm}
        onSubmit={(event) => {
          event.preventDefault();
          onTextSearch();
        }}
      >
        <h2 id="ip-search-title" className={styles.visuallyHidden}>
          智能找图
        </h2>
        <div className={styles.searchInput}>
          <span className={styles.searchIcon} aria-hidden="true" />
          <label className={styles.visuallyHidden} htmlFor="ip-asset-chat">
            自然语言找图
          </label>
          <input
            id="ip-asset-chat"
            value={message}
            onChange={(event) => onMessageChange(event.target.value)}
            placeholder="和图库对话，例如：找一张小赛开心庆祝、适合社群推送的透明底图片"
            maxLength={2000}
          />
          <button
            type="submit"
            disabled={searching || message.trim().length === 0}
          >
            {searching ? "检索中…" : "开始找图"}
          </button>
        </div>
        <small className={styles.searchHint}>
          {semanticAvailable
            ? "多模态检索已连接 · 明确的角色与类型会优先匹配"
            : "当前使用分类与关键词检索 · 向量服务恢复后自动增强"}
        </small>
        <div className={styles.examplePrompts} aria-label="示例找图问题">
          <span>试试这样问</span>
          {exampleSearchPrompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => {
                onMessageChange(prompt);
                setExampleNotice("示例问题已填入，可以继续修改或开始找图。");
              }}
            >
              {prompt}
            </button>
          ))}
        </div>
        {exampleNotice === "" ? null : (
          <small className={styles.exampleNotice} role="status">
            {exampleNotice}
          </small>
        )}
      </form>
      <div className={styles.filterToolbar} aria-label="图库筛选">
        <FilterSelect
          label="IP 角色"
          value={filters.character}
          options={characterOptions}
          onChange={(value) =>
            onFilterChange("character", value as IpAssetCharacter | "")
          }
        />
        <FilterSelect
          label="来源"
          value={filters.sourceKind}
          options={sourceOptions}
          onChange={(value) =>
            onFilterChange("sourceKind", value as IpAssetSource | "")
          }
        />
        <FilterSelect
          label="构图"
          value={filters.orientation}
          options={orientationOptions}
          onChange={(value) =>
            onFilterChange("orientation", value as IpAssetOrientation | "")
          }
        />
        <FilterSelect
          label="资产类型"
          value={filters.assetType}
          options={assetTypeOptions}
          onChange={(value) =>
            onFilterChange("assetType", value as IpAssetType | "")
          }
        />
        <details className={styles.moreFilters}>
          <summary>更多筛选</summary>
          <div>
            <label>
              <span>部门（自填）</span>
              <input
                value={filters.department}
                maxLength={80}
                onChange={(event) =>
                  onFilterChange("department", event.target.value)
                }
              />
            </label>
            <label>
              <span>关键词</span>
              <input
                value={filters.query}
                maxLength={200}
                onChange={(event) =>
                  onFilterChange("query", event.target.value)
                }
              />
            </label>
            <label>
              <span>标签</span>
              <input
                value={filters.tag}
                maxLength={40}
                onChange={(event) => onFilterChange("tag", event.target.value)}
              />
            </label>
          </div>
        </details>
        <label className={styles.imageQuery}>
          <span aria-hidden="true">⌁</span>
          以图搜图
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              if (file !== undefined) onImageSearch(file);
              event.currentTarget.value = "";
            }}
          />
        </label>
        <button type="button" className={styles.ghostButton} onClick={onReset}>
          重置
        </button>
      </div>
    </section>
  );
}

function FilterSelect({
  label,
  value,
  options,
  allowEmpty = true,
  onChange,
}: Readonly<{
  label: string;
  value: string;
  options: readonly Readonly<{ value: string; label: string }>[];
  allowEmpty?: boolean;
  onChange: (value: string) => void;
}>) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {allowEmpty ? <option value="">全部</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function AssetGrid({
  assets,
  searchMatches,
  selectedAssets,
  activeRef,
  onOpen,
  onFavorite,
  onToggle,
}: Readonly<{
  assets: readonly IpAsset[];
  searchMatches: ReadonlyMap<
    string,
    Readonly<{ explanation: string; similarity: number | null }>
  >;
  selectedAssets: ReadonlyMap<string, IpAsset>;
  activeRef: string | null;
  onOpen: (assetRef: string) => void;
  onFavorite: (asset: IpAsset) => void;
  onToggle: (asset: IpAsset) => void;
}>) {
  return (
    <div className={styles.assetGrid} aria-label="IP 图片列表">
      {assets.map((asset) => {
        const match = searchMatches.get(asset.asset_ref);
        return (
          <article
            key={asset.asset_ref}
            className={
              asset.asset_ref === activeRef ? styles.activeCard : undefined
            }
          >
            <div className={styles.assetVisual}>
              <AssetPreview key={asset.preview_url} asset={asset} />
              <span className={styles.assetState} data-state={asset.status}>
                {asset.status === "ready"
                  ? "可用"
                  : asset.status === "processing"
                    ? "处理中"
                    : "处理失败"}
              </span>
              <label className={styles.selector}>
                <input
                  type="checkbox"
                  aria-label={
                    asset.status === "ready" && asset.shared
                      ? `选择 ${asset.canonical_name}`
                      : `${asset.canonical_name} 暂不可选择`
                  }
                  checked={selectedAssets.has(asset.asset_ref)}
                  disabled={asset.status !== "ready" || !asset.shared}
                  onChange={() => onToggle(asset)}
                />
                <span aria-hidden="true">
                  {asset.status !== "ready" || !asset.shared
                    ? "不可选"
                    : selectedAssets.has(asset.asset_ref)
                      ? "✓ 已选"
                      : "选择"}
                </span>
              </label>
              <button
                type="button"
                className={styles.favoriteButton}
                aria-label={
                  asset.favorite
                    ? `取消收藏 ${asset.canonical_name}`
                    : `收藏 ${asset.canonical_name}`
                }
                aria-pressed={asset.favorite}
                onClick={() => onFavorite(asset)}
              >
                {asset.favorite ? "♥" : "♡"}
              </button>
            </div>
            <button
              type="button"
              className={styles.cardBody}
              onClick={() => onOpen(asset.asset_ref)}
            >
              <span className={styles.cardTaxonomy}>
                <span>{labels.character[asset.character]}</span>
                <span>{labels.assetType[asset.asset_type]}</span>
              </span>
              <strong>{asset.canonical_name}</strong>
              {match === undefined ? null : (
                <span className={styles.matchReason}>
                  <small>匹配理由</small>
                  {match.explanation}
                  {match.similarity === null ? null : (
                    <small>含画面语义线索</small>
                  )}
                </span>
              )}
              <span className={styles.cardFooter}>
                <small>
                  {asset.width} × {asset.height}
                </small>
                <small>{labels.source[asset.source_kind]}</small>
              </span>
            </button>
          </article>
        );
      })}
    </div>
  );
}

function AssetPreview({
  asset,
  detail = false,
}: Readonly<{ asset: IpAsset; detail?: boolean }>) {
  const [failed, setFailed] = useState(false);
  const previewPath = detail ? asset.preview_url : asset.thumbnail_url;
  const preview =
    asset.status === "ready" ? ipAssetResourceUrl(previewPath) : null;
  const unavailableMessage =
    asset.status === "processing"
      ? "图片正在处理，暂不可预览"
      : asset.status === "failed"
        ? "图片处理失败，暂不可预览"
        : "图片预览不可用";

  if (preview === null || failed) {
    return (
      <div
        className={detail ? styles.detailPreviewFallback : styles.brokenPreview}
        role="img"
        aria-label={`${asset.canonical_name}：${unavailableMessage}`}
      >
        {unavailableMessage}
      </div>
    );
  }
  return (
    <img
      className={detail ? styles.detailPreview : undefined}
      src={preview}
      alt={`${asset.canonical_name}，${labels.character[asset.character]} ${labels.assetType[asset.asset_type]}`}
      loading={detail ? "eager" : "lazy"}
      onError={() => setFailed(true)}
    />
  );
}

type RecognitionMetadata = Readonly<{
  emotion: string;
  action: string;
  scene: string;
  intendedUse: string;
  style: string;
  tags: string;
}>;

const emptyRecognitionMetadata: RecognitionMetadata = {
  emotion: "",
  action: "",
  scene: "",
  intendedUse: "",
  style: "",
  tags: "",
};

function UploadPanel({
  mutation,
  recognitionAvailable,
  profile,
}: Readonly<{
  mutation: ReturnType<typeof useUploadIpAsset>;
  recognitionAvailable: boolean;
  profile: LocalIpAssetProfile | null;
}>) {
  const recognition = useRecognizeIpAsset();
  const [file, setFile] = useState<File | null>(null);
  const [character, setCharacter] = useState<IpAssetCharacter>("xiao_sai");
  const [assetType, setAssetType] = useState<IpAssetType>("meme_sticker");
  const [department, setDepartment] = useState("");
  const [contributor, setContributor] = useState("");
  const [metadata, setMetadata] = useState<RecognitionMetadata>(
    emptyRecognitionMetadata,
  );
  const [recognitionState, setRecognitionState] = useState<
    "idle" | "pending" | "suggested" | "failed"
  >("idle");
  const [suggestionIdentity, setSuggestionIdentity] = useState("");
  const recognitionEpoch = useRef(0);
  const previewUrl = useMemo(() => {
    if (file === null || typeof URL.createObjectURL !== "function") return null;
    return URL.createObjectURL(file);
  }, [file]);

  useEffect(
    () => () => {
      if (previewUrl !== null && typeof URL.revokeObjectURL === "function")
        URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  const applySuggestion = (suggestion: IpAssetRecognition) => {
    setCharacter(suggestion.character);
    setAssetType(suggestion.asset_type);
    setMetadata({
      emotion: suggestion.emotion,
      action: suggestion.action,
      scene: suggestion.scene,
      intendedUse: suggestion.intended_use,
      style: suggestion.style,
      tags: (suggestion.tags ?? []).join("，"),
    });
    setSuggestionIdentity(suggestion.model);
    setRecognitionState("suggested");
  };

  const selectFile = (nextFile: File | null) => {
    recognitionEpoch.current += 1;
    recognition.reset();
    setFile(nextFile);
    setCharacter("xiao_sai");
    setAssetType("meme_sticker");
    setMetadata(emptyRecognitionMetadata);
    setRecognitionState("idle");
    setSuggestionIdentity("");
  };

  return (
    <form
      className={styles.toolPanel}
      aria-labelledby="ip-upload-title"
      onSubmit={(event) => {
        event.preventDefault();
        if (file === null) return;
        mutation.mutate({
          file,
          character,
          assetType,
          department,
          contributor,
          emotion: metadata.emotion,
          action: metadata.action,
          scene: metadata.scene,
          intendedUse: metadata.intendedUse,
          style: metadata.style,
          tags: metadata.tags,
          ...(profile === null ? {} : { profileToken: profile.token }),
        });
      }}
    >
      <div className={styles.toolHeading}>
        <h2 id="ip-upload-title">上传资产</h2>
        <p>选择图片并补全分类，系统会生成统一名称并保存原件。</p>
      </div>
      <label className={styles.fileDrop}>
        <input
          required
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(event) =>
            selectFile(event.currentTarget.files?.[0] ?? null)
          }
        />
        {previewUrl === null ? null : (
          <img
            className={styles.localPreview}
            src={previewUrl}
            alt="待上传图片本地预览"
          />
        )}
        <strong>{file?.name ?? "选择 PNG / JPEG / WebP"}</strong>
        <small>最大 25 MiB，上传后立即进入共享图库</small>
      </label>
      <div className={styles.recognitionActions}>
        <button
          type="button"
          className={styles.recognitionButton}
          disabled={
            file === null ||
            !recognitionAvailable ||
            recognitionState === "pending"
          }
          onClick={() => {
            if (file === null || !recognitionAvailable) return;
            const epoch = recognitionEpoch.current + 1;
            recognitionEpoch.current = epoch;
            setRecognitionState("pending");
            setSuggestionIdentity("");
            recognition.mutate(file, {
              onSuccess: (suggestion) => {
                if (recognitionEpoch.current === epoch)
                  applySuggestion(suggestion);
              },
              onError: () => {
                if (recognitionEpoch.current === epoch)
                  setRecognitionState("failed");
              },
            });
          }}
        >
          <span aria-hidden="true">✦</span>
          {recognitionState === "pending" ? "AI 识别中…" : "AI 辅助识别"}
        </button>
        {!recognitionAvailable ? (
          <p className={styles.recognitionUnavailable}>
            AI 辅助识别暂未启用，仍可手动填写并上传。
          </p>
        ) : null}
        {recognitionState === "suggested" ? (
          <p
            className={styles.recognitionStatus}
            role="status"
            aria-live="polite"
          >
            <strong>AI 建议，请确认</strong>
            已回填可编辑分类与描述（{suggestionIdentity}）。
          </p>
        ) : null}
        {recognitionState === "failed" ? (
          <p className={styles.recognitionError} role="alert">
            AI 识别失败，已保留当前图片和填写内容，可继续手动上传。
          </p>
        ) : null}
      </div>
      <FilterSelect
        label="IP 角色 *"
        value={character}
        options={characterOptions}
        allowEmpty={false}
        onChange={(value) => setCharacter(value as IpAssetCharacter)}
      />
      <FilterSelect
        label="资产类型 *"
        value={assetType}
        options={assetTypeOptions}
        allowEmpty={false}
        onChange={(value) => setAssetType(value as IpAssetType)}
      />
      <details>
        <summary>补充描述信息</summary>
        <div className={styles.metadataGrid}>
          <label>
            <span>部门（自填）</span>
            <input
              name="department"
              value={department}
              maxLength={80}
              onChange={(event) => setDepartment(event.target.value)}
            />
          </label>
          <label>
            <span>上传人（自填）</span>
            <input
              name="contributor"
              value={contributor}
              maxLength={80}
              onChange={(event) => setContributor(event.target.value)}
            />
          </label>
          {(
            [
              ["emotion", "情绪", 40],
              ["action", "动作", 40],
              ["scene", "场景", 60],
              ["intendedUse", "用途", 60],
              ["style", "风格", 40],
              ["tags", "标签（逗号分隔）", 900],
            ] as const
          ).map(([name, label, maxLength]) => (
            <label key={name}>
              <span>{label}</span>
              <input
                name={name}
                value={metadata[name]}
                maxLength={maxLength}
                onChange={(event) =>
                  setMetadata((current) => ({
                    ...current,
                    [name]: event.target.value,
                  }))
                }
              />
            </label>
          ))}
        </div>
      </details>
      <button type="submit" disabled={file === null || mutation.isPending}>
        {mutation.isPending ? "正在校验并上传…" : "上传到共享图库"}
      </button>
      <MutationFeedback
        error={mutation.error}
        success={
          mutation.data === undefined
            ? null
            : mutation.data.duplicate
              ? "相同原件已存在，已返回原资产。"
              : `已登记：${mutation.data.asset.canonical_name}`
        }
      />
    </form>
  );
}

function ToolDialog({
  labelledBy,
  eyebrow,
  children,
  onClose,
}: Readonly<{
  labelledBy: string;
  eyebrow: string;
  children: ReactNode;
  onClose: () => void;
}>) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useDialogFocus(panel, closeButton, onClose);

  return (
    <div className={styles.dialogBackdrop} onMouseDown={onClose}>
      <div
        ref={panel}
        className={styles.toolDialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className={styles.dialogTopline}>
          <p>{eyebrow}</p>
          <button ref={closeButton} type="button" onClick={onClose}>
            <span aria-hidden="true">×</span>
            <span className={styles.visuallyHidden}>关闭面板</span>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function useDialogFocus(
  panel: Readonly<{ current: HTMLElement | null }>,
  initialFocus: Readonly<{ current: HTMLElement | null }>,
  onClose: () => void,
) {
  useEffect(() => {
    const previouslyFocused =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    initialFocus.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || panel.current === null) return;
      const focusable = Array.from(
        panel.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter(
        (element) =>
          !element.matches('input[type="hidden"]') &&
          element.closest("[hidden], [aria-hidden='true']") === null &&
          (element.matches("summary") ||
            element.closest("details:not([open])") === null),
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (first === undefined || last === undefined) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, [initialFocus, onClose, panel]);
}

function AssetDetail({
  loading,
  asset,
  onFavorite,
  onClose,
}: Readonly<{
  loading: boolean;
  asset: ReturnType<typeof useIpAssetDetail>["data"];
  onFavorite: () => void;
  onClose: () => void;
}>) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  useDialogFocus(panel, closeButton, onClose);

  return (
    <div className={styles.dialogBackdrop} onMouseDown={onClose}>
      <div
        ref={panel}
        className={styles.detailPanel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="ip-asset-detail-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button
          ref={closeButton}
          type="button"
          className={styles.closeButton}
          onClick={onClose}
        >
          <span aria-hidden="true">×</span>
          <span className={styles.visuallyHidden}>关闭详情</span>
        </button>
        {loading || asset === undefined ? (
          <p role="status">正在读取资产详情…</p>
        ) : (
          <>
            <AssetPreview key={asset.preview_url} asset={asset} detail />
            <p>ASSET / {asset.asset_ref}</p>
            <h2 id="ip-asset-detail-title">{asset.canonical_name}</h2>
            <dl>
              <div>
                <dt>角色</dt>
                <dd>{labels.character[asset.character]}</dd>
              </div>
              <div>
                <dt>类型</dt>
                <dd>{labels.assetType[asset.asset_type]}</dd>
              </div>
              <div>
                <dt>尺寸</dt>
                <dd>
                  {asset.width} × {asset.height}
                </dd>
              </div>
              <div>
                <dt>来源</dt>
                <dd>{labels.source[asset.source_kind]}</dd>
              </div>
              <div>
                <dt>部门 / 上传人（自填）</dt>
                <dd>
                  {asset.department || "未填写"} /{" "}
                  {asset.contributor || "未填写"}
                </dd>
              </div>
              <div>
                <dt>原始文件</dt>
                <dd>{asset.safe_original_filename}</dd>
              </div>
            </dl>
            {asset.status !== "ready" ? (
              <p className={styles.unavailable} role="status">
                原件仍在处理或处理失败，当前不可预览、下载或用作创作参考。
              </p>
            ) : ipAssetResourceUrl(asset.download_url) === null ? null : (
              <div className={styles.detailActions}>
                <a
                  className={styles.downloadLink}
                  href={ipAssetResourceUrl(asset.download_url) ?? ""}
                  download
                >
                  下载不可变原件
                </a>
                <button
                  type="button"
                  aria-pressed={asset.favorite}
                  onClick={onFavorite}
                >
                  {asset.favorite ? "取消收藏" : "收藏图片"}
                </button>
                <a
                  className={styles.creationLink}
                  href={`/ip-assets/create?reference=${encodeURIComponent(asset.asset_ref)}`}
                >
                  用作 AI 创作参考
                </a>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function MutationFeedback({
  error,
  success,
}: Readonly<{ error: Error | null; success: string | null }>) {
  if (error !== null)
    return (
      <p className={styles.error} role="alert">
        操作失败：{error.message}
      </p>
    );
  if (success !== null)
    return (
      <p className={styles.success} role="status">
        {success}
      </p>
    );
  return null;
}
