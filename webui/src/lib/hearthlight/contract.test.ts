import { describe, expect, it } from "vitest";
import { createHostAdapter } from "./host";
import type { GroupItem, GrowthItem } from "./types";

// Mirrors tests/test_panel_state.py GROUP_KEYS / GROWTH_KEYS and the exact shapes
// emitted by ContractV1.list_group_states / list_growth_states.
const groupFixture: GroupItem = {
  umo: "aiocqhttp:GroupMessage:10001",
  member_count: 12,
  activity_level: "medium",
  topic: "周末计划",
  topic_age_min: 3.5,
  last_activity: "2026-10-15T12:00:00+08:00",
  allow: true,
  reason: "ok",
  cooldown_remaining_sec: 0,
  hourly_remaining: 6,
};

const growthFixture: GrowthItem = {
  persona_id: "lan",
  user_id: "webchat:FriendMessage:webchat!u1!private",
  level: 7,
  progress: 0.68,
  max_level: 10,
  traits: ["亲近", "常来"],
};

function sdk(responses: Record<string, unknown>) {
  return {
    ready: async () => undefined,
    apiGet: async (path: string) => responses[path],
    apiPost: async () => ({}),
  };
}

describe("actual host group contract", () => {
  it("keeps flat ContractV1 fields without inventing advisory metrics", async () => {
    const adapter = createHostAdapter(sdk({ "group-state": { items: [groupFixture] } }));
    await expect(adapter.getGroupState()).resolves.toEqual([groupFixture]);
    expect(Object.keys(groupFixture)).toEqual([
      "umo",
      "member_count",
      "activity_level",
      "topic",
      "topic_age_min",
      "last_activity",
      "allow",
      "reason",
      "cooldown_remaining_sec",
      "hourly_remaining",
    ]);
  });

  it("rejects the old invented group shape instead of silently coercing it", async () => {
    const adapter = createHostAdapter(
      sdk({
        "group-state": {
          items: [{ group_id: "g", activity: 0.5, advisory: "join", persona_id: "lan" }],
        },
      }),
    );
    await expect(adapter.getGroupState()).rejects.toThrow(/group-state/);
  });

  it("accepts a group without a topic (topic_age_min is null)", async () => {
    const item = { ...groupFixture, topic: "", topic_age_min: null };
    const adapter = createHostAdapter(sdk({ "group-state": { items: [item] } }));
    await expect(adapter.getGroupState()).resolves.toEqual([item]);
  });
});

describe("actual host growth contract", () => {
  it("keeps level/progress/max_level/traits and drops phase/trust/familiarity", async () => {
    const adapter = createHostAdapter(sdk({ "growth-state": { items: [growthFixture] } }));
    await expect(adapter.getGrowthState()).resolves.toEqual([growthFixture]);
    expect(Object.keys(growthFixture)).toEqual([
      "persona_id",
      "user_id",
      "level",
      "progress",
      "max_level",
      "traits",
    ]);
  });

  it("rejects the old invented growth shape", async () => {
    const adapter = createHostAdapter(
      sdk({
        "growth-state": {
          items: [{ persona_id: "lan", user_id: "u", phase: "steady", trust: 0.9 }],
        },
      }),
    );
    await expect(adapter.getGrowthState()).rejects.toThrow(/growth-state/);
  });

  it("requires traits to be an array", async () => {
    const adapter = createHostAdapter(
      sdk({
        "growth-state": { items: [{ ...growthFixture, traits: "亲近" }] },
      }),
    );
    await expect(adapter.getGrowthState()).rejects.toThrow(/growth-state/);
  });
});
