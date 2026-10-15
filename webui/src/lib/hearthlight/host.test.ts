import { describe, expect, it } from "vitest";
import { createHostAdapter, normalizeMotivationItem, requireItems, requireOk, unwrapResponse } from "./host";
import { AdapterError } from "./types";
import { KINDS, reasonLabel } from "./labels";

describe("host response unwrapping", () => {
  it("unwraps {status:'ok', data}", () => {
    expect(requireItems({ status: "ok", data: { items: [1, 2] } })).toEqual([1, 2]);
  });
  it("parses SDK string bodies", () => {
    expect(requireItems(JSON.stringify({ status: "ok", data: { items: [3] } }))).toEqual([3]);
  });
  it("rejects a truthy object without items", () => {
    expect(() => requireItems({ hello: true })).toThrow(AdapterError);
  });
  it("throws on non-ok status instead of returning data", () => {
    expect(() => unwrapResponse({ status: "error", message: "boom" })).toThrow("boom");
  });
  it("POST requires ok === true", () => {
    expect(() => requireOk({ ok: "yes" })).toThrow(AdapterError);
    expect(
      requireOk<{ ok: boolean; backup_path: string }>({ ok: true, backup_path: "/b" }).backup_path,
    ).toBe("/b");
  });

  it("projects raw motivation_log rows into the page contract", async () => {
    const rawRow = {
      entry_id: "entry-42",
      persona_id: "persona-lan",
      kind: "proactive_outcome",
      value: 0,
      reason: "quiet_hours",
      selected_reason: "quiet_hours",
      blocked_reason: "quiet_hours",
      reason_code: "",
      adopted: 0,
      created_at: "2026-10-15T10:00:00+00:00",
      umo: "test:FriendMessage:42",
      user_id: "p:test:FriendMessage:42",
      receipt_key: null,
    };
    const sdk = {
      ready: () => Promise.resolve(),
      apiGet: async () => ({ items: [rawRow] }),
      apiPost: async () => ({ ok: true }),
    };
    const items = await createHostAdapter(sdk).getMotivationLog();
    expect(items).toHaveLength(1);
    const item = items[0]!;

    expect(item.persona_id).toBe("persona-lan");
    expect(item.user_id).toBe("p:test:FriendMessage:42");
    expect(item.kind).toBe("proactive_outcome");
    expect(item.reason_code).toBe("quiet_hours");
    expect(item.result).toBe("skipped");
    expect(item.receipt_key).toBe("entry-42");
    expect(KINDS[item.kind]).toBe("主动结果回执");
    expect(reasonLabel(item.reason_code)).toBe("处于安静时段，延后处理");
  });

  it("uses the raw reason when an older row has no reason code", () => {
    const item = normalizeMotivationItem({
      entry_id: "legacy-1",
      persona_id: "persona-yu",
      kind: "legacy_audit",
      reason: "legacy reason",
    });
    expect(item.reason_code).toBe("legacy reason");
    expect(reasonLabel(item.reason_code)).toBe("legacy reason");
    expect(item.receipt_key).toBe("legacy-1");
  });
});
