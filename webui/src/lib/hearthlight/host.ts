import {
  AdapterError,
  type GroupItem,
  type GrowthItem,
  type HearthlightAdapter,
  type MotivationItem,
  type MigrateResult,
  type RekeyResult,
} from "./types";

export interface AstrBotPluginPageSDK {
  ready: () => unknown;
  apiGet: (relativePath: string) => Promise<unknown>;
  apiPost: (relativePath: string, body: unknown) => Promise<unknown>;
}

declare global {
  interface Window {
    AstrBotPluginPage?: AstrBotPluginPageSDK;
  }
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Normalise SDK responses: JSON string bodies, {body:"..."} and {status:"ok",data} envelopes. */
export function unwrapResponse(raw: unknown, depth = 0): unknown {
  if (depth > 4) throw new AdapterError("invalid", "响应嵌套过深");
  if (typeof raw === "string") {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new AdapterError("invalid", "响应不是有效 JSON");
    }
    return unwrapResponse(parsed, depth + 1);
  }
  if (!isObj(raw)) throw new AdapterError("invalid", "响应格式无效");
  if (typeof raw["body"] === "string" && !("items" in raw))
    return unwrapResponse(raw["body"], depth + 1);
  if ("status" in raw) {
    if (raw["status"] !== "ok") {
      const msg =
        typeof raw["message"] === "string"
          ? raw["message"]
          : `宿主返回状态 ${String(raw["status"])}`;
      const code = raw["code"] ?? raw["status"];
      throw new AdapterError(code === 403 || code === "forbidden" ? "forbidden" : "server", msg);
    }
    return "data" in raw ? unwrapResponse(raw["data"], depth + 1) : raw;
  }
  return raw;
}

export function requireItems<T>(raw: unknown): T[] {
  const v = unwrapResponse(raw);
  if (!isObj(v) || !Array.isArray(v["items"]))
    throw new AdapterError("invalid", "响应缺少 items 数组");
  return v["items"] as T[];
}

export function requireItemsWith<T>(
  raw: unknown,
  endpoint: string,
  validate: (value: unknown) => value is T,
): T[] {
  const items = requireItems<unknown>(raw);
  if (!items.every(validate)) {
    throw new AdapterError("invalid", `${endpoint} 返回的 items 不符合实际契约`);
  }
  return items;
}

const isString = (v: unknown): v is string => typeof v === "string";
const isNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isBoolean = (v: unknown): v is boolean => typeof v === "boolean";
const isStringArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(isString);

const isActivityLevel = (v: unknown): v is GroupItem["activity_level"] =>
  v === "low" || v === "medium" || v === "high";

function groupItem(v: unknown): v is GroupItem {
  return (
    isObj(v) &&
    isString(v["umo"]) &&
    isNumber(v["member_count"]) &&
    isActivityLevel(v["activity_level"]) &&
    isString(v["topic"]) &&
    (v["topic_age_min"] === null || isNumber(v["topic_age_min"])) &&
    isString(v["last_activity"]) &&
    isBoolean(v["allow"]) &&
    isString(v["reason"]) &&
    isNumber(v["cooldown_remaining_sec"]) &&
    isNumber(v["hourly_remaining"])
  );
}

function growthItem(v: unknown): v is GrowthItem {
  return (
    isObj(v) &&
    isString(v["persona_id"]) &&
    isString(v["user_id"]) &&
    isNumber(v["level"]) &&
    isNumber(v["progress"]) &&
    isNumber(v["max_level"]) &&
    isStringArray(v["traits"])
  );
}

export function requireOk<T extends { ok: boolean }>(raw: unknown): T {
  const v = unwrapResponse(raw);
  if (!isObj(v) || v["ok"] !== true) {
    const msg = isObj(v) && typeof v["error"] === "string" ? v["error"] : "操作未返回 ok:true";
    throw new AdapterError("server", msg);
  }
  return v as unknown as T;
}

const firstText = (...values: unknown[]): string => {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
};

/** Project raw `SELECT * FROM motivation_log` rows onto the UI's stable shape. */
export function normalizeMotivationItem(raw: unknown): MotivationItem {
  if (!isObj(raw)) throw new AdapterError("invalid", "motivation-log 项目格式无效");
  const personaId = firstText(raw["persona_id"], raw["personaId"], raw["persona"]);
  const userId = firstText(raw["user_id"], raw["userId"], raw["umo"]);
  const kind = firstText(raw["kind"], raw["type"], raw["event_type"]);
  const reasonCode = firstText(
    raw["reason_code"],
    raw["selected_reason"],
    raw["blocked_reason"],
    raw["reason"],
  );
  const explicitResult = firstText(raw["result"]);
  const adopted = raw["adopted"] === true || raw["adopted"] === 1;
  const blocked = raw["blocked_reason"] === true ||
    (typeof raw["blocked_reason"] === "string" && raw["blocked_reason"].trim().length > 0);
  const result = explicitResult ||
    (kind === "proactive_outcome" && (adopted || raw["adopted"] === false || raw["adopted"] === 0)
      ? adopted
        ? "sent"
        : "skipped"
      : undefined);
  return {
    ...raw,
    persona_id: personaId || "(未记录)",
    user_id: userId,
    kind: kind || "unknown",
    reason_code: reasonCode,
    receipt_key: firstText(raw["receipt_key"], raw["entry_id"]),
    ...(result ? { result } : {}),
    ...(blocked && !firstText(raw["blocked_reason"]) ? { blocked_reason: reasonCode } : {}),
    ...(firstText(raw["created_at"]) ? { created_at: firstText(raw["created_at"]) } : {}),
  };
}

function wrapErr(e: unknown): never {
  if (e instanceof AdapterError) throw e;
  const msg = e instanceof Error ? e.message : String(e);
  throw new AdapterError(
    /403|forbidden/i.test(msg) ? "forbidden" : "network",
    msg || "宿主请求失败",
  );
}

export function createHostAdapter(sdk: AstrBotPluginPageSDK): HearthlightAdapter {
  const get = async (p: string) => {
    try {
      return await sdk.apiGet(p);
    } catch (e) {
      wrapErr(e);
    }
  };
  const post = async (p: string, b: unknown) => {
    try {
      return await sdk.apiPost(p, b);
    } catch (e) {
      wrapErr(e);
    }
  };
  return {
    mode: "host",
    async getLifeState() {
      const v = unwrapResponse(await get("life-state"));
      if (!isObj(v) || !Array.isArray(v["items"]))
        throw new AdapterError("invalid", "life-state 缺少 items");
      return { day: String(v["day"] ?? ""), items: v["items"] as never };
    },
    getRelationships: async () => requireItems(await get("relationships")),
    getEmotionState: async () => requireItems(await get("emotion-state")),
    getGroupState: async () =>
      requireItemsWith(await get("group-state"), "group-state", groupItem),
    getGrowthState: async () =>
      requireItemsWith(await get("growth-state"), "growth-state", growthItem),
    getMotivationLog: async () =>
      requireItems<unknown>(await get("motivation-log")).map(normalizeMotivationItem),
    getPersonKeys: async () => requireItems(await get("person/keys")),
    rekeyDryRun: async () => requireOk<RekeyResult>(await post("person/rekey", { dry_run: true })),
    migrate: async (person_id, aliases) =>
      requireOk<MigrateResult>(await post("person/migrate", { person_id, aliases })),
    rollback: async () => requireOk<MigrateResult>(await post("person/migrate/rollback", {})),
  };
}

export type HostDetection =
  | { status: "host"; adapter: HearthlightAdapter }
  | { status: "no-sdk" }
  | { status: "ready-failed"; message: string };

/** Only a real SDK whose ready() resolves counts as host mode. */
export async function detectHost(timeoutMs = 2500): Promise<HostDetection> {
  if (typeof window === "undefined") return { status: "no-sdk" };
  const sdk = window.AstrBotPluginPage;
  if (
    !sdk ||
    typeof sdk.ready !== "function" ||
    typeof sdk.apiGet !== "function" ||
    typeof sdk.apiPost !== "function"
  )
    return { status: "no-sdk" };
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      Promise.resolve(sdk.ready()),
      new Promise((_, rej) => {
        timer = setTimeout(() => rej(new Error("ready() 超时")), timeoutMs);
      }),
    ]);
    return { status: "host", adapter: createHostAdapter(sdk) };
  } catch (e) {
    return { status: "ready-failed", message: e instanceof Error ? e.message : String(e) };
  } finally {
    clearTimeout(timer);
  }
}
