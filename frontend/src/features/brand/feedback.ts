export const DIGITAL_IP_FEEDBACK_STORAGE_KEY =
  "edu-ai-lead-agent.digital-ip-feedback.v1";
export const DIGITAL_IP_FEEDBACK_SCHEMA_VERSION = 1 as const;
export const MAX_DIGITAL_IP_FEEDBACK_ITEMS = 50;
export const MAX_DIGITAL_IP_FEEDBACK_NOTE_LENGTH = 160;

export const feedbackDecisions = ["accepted", "rejected"] as const;
export const feedbackReasons = [
  "relevant",
  "tone_match",
  "missing_rule",
  "irrelevant",
  "conflicting_rule",
] as const;

export type FeedbackDecision = (typeof feedbackDecisions)[number];
export type FeedbackReason = (typeof feedbackReasons)[number];

export type DigitalIpFeedbackRecord = Readonly<{
  schemaVersion: typeof DIGITAL_IP_FEEDBACK_SCHEMA_VERSION;
  id: string;
  createdAt: string;
  queryFingerprint: string;
  profileFingerprint: string;
  chunkIds: readonly string[];
  versionIds: readonly string[];
  decision: FeedbackDecision;
  reason: FeedbackReason;
  note?: string;
}>;

type FeedbackLedger = Readonly<{
  schemaVersion: typeof DIGITAL_IP_FEEDBACK_SCHEMA_VERSION;
  items: readonly DigitalIpFeedbackRecord[];
}>;

export type FeedbackStorage = Pick<
  Storage,
  "getItem" | "setItem" | "removeItem"
>;

type CreateFeedbackInput = Readonly<{
  query: string;
  profileFingerprint: string;
  chunkIds: readonly string[];
  versionIds: readonly string[];
  decision: FeedbackDecision;
  reason: FeedbackReason;
  note?: string;
}>;

export function createDigitalIpFeedback(
  input: CreateFeedbackInput,
  createdAt = new Date(),
  id = createFeedbackId(createdAt, input),
): DigitalIpFeedbackRecord {
  const note = input.note?.trim().slice(0, MAX_DIGITAL_IP_FEEDBACK_NOTE_LENGTH);
  const base = {
    schemaVersion: DIGITAL_IP_FEEDBACK_SCHEMA_VERSION,
    id,
    createdAt: createdAt.toISOString(),
    queryFingerprint: fingerprintText(input.query.trim()),
    profileFingerprint: input.profileFingerprint,
    chunkIds: uniqueBounded(input.chunkIds),
    versionIds: uniqueBounded(input.versionIds),
    decision: input.decision,
    reason: input.reason,
  } as const;
  return note === undefined || note.length === 0 ? base : { ...base, note };
}

export function loadDigitalIpFeedback(
  storage: FeedbackStorage = window.localStorage,
): readonly DigitalIpFeedbackRecord[] {
  let raw: string | null;
  try {
    raw = storage.getItem(DIGITAL_IP_FEEDBACK_STORAGE_KEY);
  } catch {
    return [];
  }
  if (raw === null) return [];
  try {
    const value: unknown = JSON.parse(raw);
    if (!isRecord(value) || value.schemaVersion !== 1) return [];
    if (!Array.isArray(value.items)) return [];
    return value.items
      .map(normalizeDigitalIpFeedbackRecord)
      .filter((item): item is DigitalIpFeedbackRecord => item !== null)
      .slice(0, MAX_DIGITAL_IP_FEEDBACK_ITEMS);
  } catch {
    return [];
  }
}

export function saveDigitalIpFeedback(
  record: DigitalIpFeedbackRecord,
  storage: FeedbackStorage = window.localStorage,
): readonly DigitalIpFeedbackRecord[] {
  const normalizedRecord = normalizeDigitalIpFeedbackRecord(record);
  if (normalizedRecord === null) {
    throw new Error("invalid_digital_ip_feedback");
  }
  const items = [
    normalizedRecord,
    ...loadDigitalIpFeedback(storage).filter(
      (item) => item.id !== normalizedRecord.id,
    ),
  ].slice(0, MAX_DIGITAL_IP_FEEDBACK_ITEMS);
  const ledger: FeedbackLedger = {
    schemaVersion: DIGITAL_IP_FEEDBACK_SCHEMA_VERSION,
    items,
  };
  storage.setItem(DIGITAL_IP_FEEDBACK_STORAGE_KEY, JSON.stringify(ledger));
  return items;
}

export function clearDigitalIpFeedback(
  storage: FeedbackStorage = window.localStorage,
): void {
  storage.removeItem(DIGITAL_IP_FEEDBACK_STORAGE_KEY);
}

export function fingerprintText(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `q-fnv1a-${(hash >>> 0).toString(16).padStart(8, "0")}-${value.length}`;
}

function createFeedbackId(createdAt: Date, input: CreateFeedbackInput): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `feedback-${createdAt.getTime()}-${fingerprintText(
    `${input.profileFingerprint}:${input.query}`,
  ).slice(9)}`;
}

function uniqueBounded(values: readonly string[]): readonly string[] {
  return [...new Set(values)].slice(0, 10);
}

function normalizeDigitalIpFeedbackRecord(
  value: unknown,
): DigitalIpFeedbackRecord | null {
  if (
    !isRecord(value) ||
    value.schemaVersion !== 1 ||
    !isBoundedString(value.id, 120) ||
    !isIsoInstant(value.createdAt) ||
    !isBoundedString(value.queryFingerprint, 80) ||
    !isBoundedString(value.profileFingerprint, 80) ||
    !isBoundedIdentifierList(value.chunkIds) ||
    !isBoundedIdentifierList(value.versionIds) ||
    !isFeedbackDecision(value.decision) ||
    !isFeedbackReason(value.reason) ||
    (value.note !== undefined &&
      (typeof value.note !== "string" ||
        value.note.length > MAX_DIGITAL_IP_FEEDBACK_NOTE_LENGTH))
  ) {
    return null;
  }
  const record = {
    schemaVersion: DIGITAL_IP_FEEDBACK_SCHEMA_VERSION,
    id: value.id,
    createdAt: value.createdAt,
    queryFingerprint: value.queryFingerprint,
    profileFingerprint: value.profileFingerprint,
    chunkIds: [...value.chunkIds],
    versionIds: [...value.versionIds],
    decision: value.decision,
    reason: value.reason,
  } as const;
  return value.note === undefined ? record : { ...record, note: value.note };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFeedbackDecision(value: unknown): value is FeedbackDecision {
  return feedbackDecisions.some((decision) => decision === value);
}

function isFeedbackReason(value: unknown): value is FeedbackReason {
  return feedbackReasons.some((reason) => reason === value);
}

function isBoundedString(value: unknown, maximum: number): value is string {
  return (
    typeof value === "string" && value.length > 0 && value.length <= maximum
  );
}

function isIsoInstant(value: unknown): value is string {
  return (
    isBoundedString(value, 40) &&
    Number.isFinite(Date.parse(value)) &&
    value.includes("T")
  );
}

function isBoundedIdentifierList(value: unknown): value is readonly string[] {
  return (
    Array.isArray(value) &&
    value.length <= 10 &&
    value.every((item) => isBoundedString(item, 120))
  );
}
