import { describe, expect, it } from "vitest";

import {
  DIGITAL_IP_FEEDBACK_STORAGE_KEY,
  MAX_DIGITAL_IP_FEEDBACK_ITEMS,
  MAX_DIGITAL_IP_FEEDBACK_NOTE_LENGTH,
  clearDigitalIpFeedback,
  createDigitalIpFeedback,
  fingerprintText,
  loadDigitalIpFeedback,
  saveDigitalIpFeedback,
  type FeedbackStorage,
} from "./feedback";

class MemoryStorage implements FeedbackStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}

function feedback(index: number) {
  return createDigitalIpFeedback(
    {
      query: `场景 ${index}`,
      profileFingerprint: "a".repeat(64),
      chunkIds: [`chunk-${index}`],
      versionIds: [`version-${index}`],
      decision: index % 2 === 0 ? "accepted" : "rejected",
      reason: index % 2 === 0 ? "relevant" : "missing_rule",
      note: "n".repeat(MAX_DIGITAL_IP_FEEDBACK_NOTE_LENGTH + 20),
    },
    new Date(`2026-08-18T00:00:${String(index % 60).padStart(2, "0")}.000Z`),
    `feedback-${index}`,
  );
}

describe("digital IP feedback ledger", () => {
  it("stores only safe identifiers and a bounded optional note", () => {
    const storage = new MemoryStorage();
    const record = feedback(1);

    saveDigitalIpFeedback(record, storage);

    expect(loadDigitalIpFeedback(storage)).toEqual([record]);
    expect(record.queryFingerprint).toBe(fingerprintText("场景 1"));
    expect(record.note).toHaveLength(MAX_DIGITAL_IP_FEEDBACK_NOTE_LENGTH);
    expect(storage.getItem(DIGITAL_IP_FEEDBACK_STORAGE_KEY)).not.toContain(
      "场景 1",
    );
  });

  it("drops malformed storage and malformed records without throwing", () => {
    const storage = new MemoryStorage();
    storage.setItem(DIGITAL_IP_FEEDBACK_STORAGE_KEY, "{not-json");
    expect(loadDigitalIpFeedback(storage)).toEqual([]);

    storage.setItem(
      DIGITAL_IP_FEEDBACK_STORAGE_KEY,
      JSON.stringify({
        schemaVersion: 1,
        items: [feedback(2), { schemaVersion: 1, decision: "maybe" }],
      }),
    );
    expect(loadDigitalIpFeedback(storage)).toEqual([feedback(2)]);
  });

  it("normalizes persisted records through an allowlist before re-saving", () => {
    const storage = new MemoryStorage();
    const record = feedback(3);
    storage.setItem(
      DIGITAL_IP_FEEDBACK_STORAGE_KEY,
      JSON.stringify({
        schemaVersion: 1,
        items: [{ ...record, chunkText: "private retrieved brand body" }],
      }),
    );

    expect(loadDigitalIpFeedback(storage)).toEqual([record]);
    saveDigitalIpFeedback(feedback(4), storage);
    expect(storage.getItem(DIGITAL_IP_FEEDBACK_STORAGE_KEY)).not.toContain(
      "private retrieved brand body",
    );
  });

  it("keeps newest feedback within the fixed ledger bound and clears it", () => {
    const storage = new MemoryStorage();
    for (let index = 0; index < MAX_DIGITAL_IP_FEEDBACK_ITEMS + 7; index += 1) {
      saveDigitalIpFeedback(feedback(index), storage);
    }

    const loaded = loadDigitalIpFeedback(storage);
    expect(loaded).toHaveLength(MAX_DIGITAL_IP_FEEDBACK_ITEMS);
    expect(loaded[0]?.id).toBe(`feedback-${MAX_DIGITAL_IP_FEEDBACK_ITEMS + 6}`);
    expect(loaded.at(-1)?.id).toBe("feedback-7");

    clearDigitalIpFeedback(storage);
    expect(loadDigitalIpFeedback(storage)).toEqual([]);
  });
});
