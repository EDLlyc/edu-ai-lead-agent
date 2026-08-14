import { apiClient, resolveApiResourceUrl } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type ContentEditionResponse =
  components["schemas"]["ContentEditionResponse"];
export type ContentEditionSlotResponse =
  components["schemas"]["ContentEditionSlotResponse"];
export type ContentEditionSelectionResponse =
  components["schemas"]["ContentEditionSelectionResponse"];

export type ContentEditionSelectionViewModel = Readonly<{
  id: string;
  ordinal: number;
  title: string;
  eventTimeLabel: string;
  state: ContentEditionSelectionResponse["state"];
  stateLabel: string;
  copyStatus: string | null;
  packageStatus: string | null;
  deliveryStatus: string | null;
  packageUrl: string | null;
  sources: readonly Readonly<{ label: string; url: string }>[];
}>;

export type ContentEditionSlotViewModel = Readonly<{
  slot: ContentEditionSlotResponse["content_slot"];
  displayName: string;
  enabled: boolean;
  targetLabel: string;
  windowLabel: string;
  state: ContentEditionSlotResponse["state"];
  stateLabel: string;
  selectedCount: number;
  itemLimit: number;
  unfilledCount: number;
  unfilledReasons: readonly string[];
  errorCode: string | null;
  selections: readonly ContentEditionSelectionViewModel[];
}>;

export type ContentEditionViewModel = Readonly<{
  businessDate: string;
  timezone: string;
  scoringProfile: string;
  slotModeEnabled: boolean;
  slots: readonly ContentEditionSlotViewModel[];
}>;

const slotStateLabels: Readonly<
  Record<ContentEditionSlotResponse["state"], string>
> = {
  disabled: "未启用",
  missing: "等待准备",
  preparing: "生产中",
  ready: "栏目已就绪",
  failed: "栏目异常",
  expired: "窗口已结束",
};

const selectionStateLabels: Readonly<
  Record<ContentEditionSelectionResponse["state"], string>
> = {
  preparing: "素材生产中",
  ready: "等待投递",
  failed: "该条生产失败",
  expired: "已错过窗口",
  delivered: "已投递",
  delivery_unknown: "投递结果未知",
};

const unfilledReasonLabels: Readonly<Record<string, string>> = {
  no_candidates: "没有进入候选集的新闻",
  all_vetoed: "候选均触发硬性否决",
  below_threshold: "候选未达到质量阈值",
  same_day_already_selected: "候选已在今日其他栏目入选",
  insufficient_eligible_candidates: "合格候选不足，不为凑数降标",
};

export async function getContentEdition(
  businessDate: string,
  profile = "preview",
  signal?: AbortSignal,
): Promise<ContentEditionViewModel> {
  const { data, error } = await apiClient.GET(
    "/api/v1/content-editions/{business_date}",
    {
      params: { path: { business_date: businessDate }, query: { profile } },
      ...(signal === undefined ? {} : { signal }),
    },
  );
  if (data === undefined) {
    throw new Error(
      error === undefined
        ? "content_edition_failed"
        : "content_edition_api_error",
    );
  }
  return mapContentEdition(data);
}

export function mapContentEdition(
  response: ContentEditionResponse,
): ContentEditionViewModel {
  return {
    businessDate: response.business_date,
    timezone: response.timezone,
    scoringProfile: response.scoring_profile,
    slotModeEnabled: response.slot_mode_enabled,
    slots: response.slots.map((slot) => ({
      slot: slot.content_slot,
      displayName: slot.display_name,
      enabled: slot.enabled,
      targetLabel: formatTime(slot.target_at),
      windowLabel: `${formatTime(slot.target_at)}—${formatTime(slot.expires_at)}`,
      state: slot.state,
      stateLabel: slotStateLabels[slot.state],
      selectedCount: slot.selected_count,
      itemLimit: slot.item_limit,
      unfilledCount: slot.unfilled_count,
      unfilledReasons: slot.unfilled_reason_codes.map(
        (reason) => unfilledReasonLabels[reason] ?? `未填满：${reason}`,
      ),
      errorCode: slot.error_code,
      selections: slot.selections.map((selection) => ({
        id: selection.selection_id,
        ordinal: selection.ordinal,
        title: selection.title,
        eventTimeLabel: formatDateTime(selection.event_time),
        state: selection.state,
        stateLabel: selectionStateLabels[selection.state],
        copyStatus: selection.copy_status,
        packageStatus: selection.material_package_status,
        deliveryStatus: selection.delivery_status,
        packageUrl:
          selection.material_package_url === null
            ? null
            : resolveApiResourceUrl(selection.material_package_url),
        sources: selection.source_links.flatMap((source) => {
          const url = resolveApiResourceUrl(source.url);
          return url === null
            ? []
            : [{ label: source.title ?? source.source_name, url }];
        }),
      })),
    })),
  };
}

export function currentShanghaiBusinessDate(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const read = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${read("year")}-${read("month")}-${read("day")}`;
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatDateTime(value: string | null): string {
  if (value === null) return "时间未记录";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
