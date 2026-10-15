import { describe, it, expect } from "vitest";
import { platformOf, identityKind, isCloseStage } from "./labels";
import { createDemoAdapter } from "./demo";
describe("identity isolation and reversible demo", () => {
  it("parses complete-UMO fallback keys without treating p as a platform", () => {
    expect(platformOf("p:aiocqhttp:FriendMessage:42:thread")).toBe("aiocqhttp");
    expect(identityKind("p:aiocqhttp:FriendMessage:42", "p:aiocqhttp:FriendMessage:42")).toBe(
      "umo",
    );
    expect(identityKind("42", "42")).toBe("legacy");
    expect(isCloseStage("亲密")).toBe(true);
  });
  it("keeps matching native IDs separate and rolls back explicit merges", async () => {
    const a = createDemoAdapter(() => "normal");
    const before = await a.getPersonKeys();
    const keys = before.filter((i) => i.user_id.includes("88017"));
    expect(new Set(keys.map((i) => i.user_id)).size).toBeGreaterThan(1);
    const alias = keys[0]!.user_id;
    await a.migrate("person:verified", [alias]);
    const changed = await a.getPersonKeys();
    expect(
      changed.filter((i) => i.user_id === alias).every((i) => i.person_key === "person:verified"),
    ).toBe(true);
    expect(
      changed
        .filter((i) => i.user_id !== alias && i.user_id.includes("88017"))
        .every((i) => i.person_key !== "person:verified"),
    ).toBe(true);
    await a.rollback();
    expect(await a.getPersonKeys()).toEqual(before);
  });
});
