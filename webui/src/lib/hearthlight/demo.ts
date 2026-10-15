// Fictional, in-memory demo adapter. Never touches the network.
import {
  AdapterError,
  type EmotionItem,
  type GroupItem,
  type GrowthItem,
  type HearthlightAdapter,
  type LifeState,
  type MotivationItem,
  type PersonKeyItem,
  type RelationshipItem,
} from "./types";

export type DemoScenario = "normal" | "empty" | "error" | "forbidden";

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

const QQ = (id: string) => `aiocqhttp:FriendMessage:${id}`;
const TG = (id: string) => `telegram:FriendMessage:${id}`;
const DC = (id: string) => `discord:FriendMessage:${id}`;

interface DemoDB {
  life: LifeState;
  relationships: RelationshipItem[];
  emotions: EmotionItem[];
  groups: GroupItem[];
  growth: GrowthItem[];
  motivation: MotivationItem[];
  keys: PersonKeyItem[];
  backups: { path: string; keys: PersonKeyItem[]; relationships: RelationshipItem[] }[];
}

function seed(): DemoDB {
  const today = new Date();
  const day = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const rel = (
    user_id: string,
    persona_id: string,
    stage: string,
    affinity: number,
    bond: boolean,
    min: number,
    person_key: string | null,
    nickname: string,
  ): RelationshipItem => ({
    user_id,
    persona_id,
    stage,
    affinity,
    bond,
    updated_at: ago(min),
    person_key,
    is_group: false,
    nickname,
  });

  const relationships: RelationshipItem[] = [
    rel(QQ("20431"), "lan", "intimate", 0.91, true, 12, "person:xiaoman", "林小满"),
    rel(DC("551203"), "lan", "friend", 0.58, false, 300, DC("551203"), "小满 (Discord)"),
    rel(QQ("30872"), "lan", "close", 0.77, true, 46, "person:xubai", "周叙白"),
    rel(TG("71920"), "yu", "close", 0.73, true, 95, "person:ayou", "阿柚"),
    rel(QQ("88017"), "yu", "friend", 0.55, false, 180, QQ("88017"), "沈既明"),
    rel(TG("88017"), "qingtan", "acquaintance", 0.34, false, 520, TG("88017"), "Kite"),
    rel(DC("604411"), "qingtan", "intimate", 0.88, true, 30, "person:wenhe", "温禾"),
    rel(QQ("41256"), "mobai", "friend", 0.61, false, 260, "person:chenzhou", "陆沉舟"),
    rel(TG("90033"), "mobai", "stranger", 0.12, false, 1440, TG("90033"), "星野"),
    rel(QQ("30872"), "yu", "acquaintance", 0.41, false, 800, "person:xubai", "周叙白"),
    {
      user_id: "aiocqhttp:GroupMessage:778102",
      persona_id: "lan",
      stage: "friend",
      affinity: 0.5,
      bond: false,
      updated_at: ago(20),
      person_key: null,
      is_group: true,
    },
  ];

  const keys: PersonKeyItem[] = relationships
    .filter((r) => !r.is_group)
    .map((r, i) => ({
      persona_id: r.persona_id,
      user_id: r.user_id,
      rows: [18, 7, 22, 15, 11, 4, 26, 13, 2, 5][i] ?? 3,
      person_key: r.person_key,
      ...(r.nickname ? { nickname: r.nickname } : {}),
    }));
  keys.push(
    { persona_id: "lan", user_id: "88017", rows: 14, person_key: null, nickname: "（旧记录）" },
    { persona_id: "yu", user_id: "20431", rows: 6, person_key: null, nickname: "（旧记录）" },
  );

  return {
    life: {
      day,
      items: [
        {
          persona_id: "lan",
          persona_name: "岚",
          activity: "整理旧照片",
          scene: "午后的书房，窗边有一盏暖灯",
          energy: 0.72,
          summary: "心情平稳，愿意慢慢聊天。",
          as_of: ago(8),
        },
        {
          persona_id: "yu",
          persona_name: "屿",
          activity: "散步归来",
          scene: "海边小镇的石板路",
          energy: 0.48,
          summary: "有点疲倦，但对晚上的约定很期待。",
          as_of: ago(25),
        },
        {
          persona_id: "qingtan",
          persona_name: "青檀",
          activity: "临帖练字",
          scene: "安静的茶室",
          energy: 0.86,
          summary: "专注而清醒，适合深入的话题。",
          as_of: ago(14),
        },
        {
          persona_id: "mobai",
          persona_name: "墨白",
          activity: "补觉中",
          scene: "下雨的公寓",
          energy: 0.22,
          summary: "能量偏低，回复会简短一些。",
          as_of: ago(62),
        },
      ],
    },
    relationships,
    emotions: [
      {
        persona_id: "lan",
        user_id: QQ("20431"),
        state: "joyful",
        valence: 0.7,
        last_event: "对方分享了猫咪新照片",
        mode: "playful",
        as_of: ago(12),
      },
      {
        persona_id: "lan",
        user_id: QQ("30872"),
        state: "calm",
        valence: 0.3,
        last_event: "聊到了周末计划",
        mode: "gentle",
        as_of: ago(46),
      },
      {
        persona_id: "yu",
        user_id: TG("71920"),
        state: "wistful",
        valence: -0.2,
        last_event: "提到一位远方的朋友",
        mode: "supportive",
        as_of: ago(95),
      },
      {
        persona_id: "yu",
        user_id: QQ("88017"),
        state: "content",
        valence: 0.45,
        last_event: "一起推荐了一本书",
        mode: "gentle",
        as_of: ago(180),
      },
      {
        persona_id: "qingtan",
        user_id: DC("604411"),
        state: "calm",
        valence: 0.5,
        last_event: "讨论书法用纸",
        mode: "quiet",
        as_of: ago(30),
      },
      {
        persona_id: "qingtan",
        user_id: TG("88017"),
        state: "anxious",
        valence: -0.35,
        last_event: "对方很久未回复",
        mode: "reserved",
        as_of: ago(520),
      },
      {
        persona_id: "mobai",
        user_id: QQ("41256"),
        state: "tired",
        valence: -0.1,
        last_event: "深夜的长对话",
        mode: "quiet",
        as_of: ago(260),
      },
    ],
    groups: [
      {
        umo: "aiocqhttp:GroupMessage:778102",
        member_count: 24,
        activity_level: "high",
        topic: "周末共读会",
        topic_age_min: 6,
        last_activity: ago(3),
        allow: true,
        reason: "ok",
        cooldown_remaining_sec: 0,
        hourly_remaining: 5,
      },
      {
        umo: "aiocqhttp:GroupMessage:556019",
        member_count: 31,
        activity_level: "high",
        topic: "夜猫子车队",
        topic_age_min: 2,
        last_activity: ago(2),
        allow: false,
        reason: "group_busy",
        cooldown_remaining_sec: 0,
        hourly_remaining: 6,
      },
      {
        umo: "telegram:GroupMessage:-100233",
        member_count: 12,
        activity_level: "low",
        topic: "城市散步计划",
        topic_age_min: 140,
        last_activity: ago(140),
        allow: false,
        reason: "cooldown",
        cooldown_remaining_sec: 37,
        hourly_remaining: 3,
      },
    ],
    growth: [
      {
        persona_id: "lan",
        user_id: QQ("20431"),
        level: 10,
        progress: 1,
        max_level: 10,
        traits: ["亲密", "常来", "开朗"],
      },
      {
        persona_id: "lan",
        user_id: QQ("30872"),
        level: 7,
        progress: 0.68,
        max_level: 10,
        traits: ["亲近", "常来"],
      },
      {
        persona_id: "yu",
        user_id: TG("71920"),
        level: 7,
        progress: 0.35,
        max_level: 10,
        traits: ["亲近"],
      },
      {
        persona_id: "yu",
        user_id: QQ("88017"),
        level: 4,
        progress: 0.4,
        max_level: 10,
        traits: ["熟悉"],
      },
      {
        persona_id: "qingtan",
        user_id: DC("604411"),
        level: 9,
        progress: 0.82,
        max_level: 10,
        traits: ["亲近", "熟客", "安静"],
      },
      {
        persona_id: "qingtan",
        user_id: TG("88017"),
        level: 3,
        progress: 0.3,
        max_level: 10,
        traits: ["熟悉"],
      },
      {
        persona_id: "mobai",
        user_id: QQ("41256"),
        level: 6,
        progress: 0.4,
        max_level: 10,
        traits: ["熟悉", "夜谈"],
      },
      {
        persona_id: "mobai",
        user_id: TG("90033"),
        level: 1,
        progress: 0.2,
        max_level: 10,
        traits: [],
      },
    ],
    motivation: [
      {
        persona_id: "lan",
        user_id: QQ("20431"),
        kind: "greeting",
        result: "sent",
        reason_code: "delivered",
        receipt_key: "ww-rcpt-7f3a91c2",
        created_at: ago(35),
      },
      {
        persona_id: "qingtan",
        user_id: DC("604411"),
        kind: "share",
        result: "sent",
        reason_code: "delivered",
        receipt_key: "ww-rcpt-2b81e0d4",
        created_at: ago(70),
      },
      {
        persona_id: "yu",
        user_id: TG("71920"),
        kind: "care_check",
        result: "skipped",
        reason_code: "user_recently_active",
        receipt_key: "ww-rcpt-c0de5512",
        created_at: ago(110),
      },
      {
        persona_id: "mobai",
        user_id: QQ("41256"),
        kind: "follow_up",
        result: "deferred",
        reason_code: "quiet_hours",
        receipt_key: "ww-rcpt-91aa0f3e",
        created_at: ago(180),
      },
      {
        persona_id: "lan",
        user_id: QQ("30872"),
        kind: "follow_up",
        result: "skipped",
        reason_code: "cooldown",
        receipt_key: "ww-rcpt-5e6f7a8b",
        created_at: ago(240),
      },
      {
        persona_id: "qingtan",
        user_id: TG("88017"),
        kind: "care_check",
        result: "failed",
        reason_code: "channel_error",
        receipt_key: "ww-rcpt-0ff1ce42",
        created_at: ago(330),
      },
      {
        persona_id: "yu",
        user_id: QQ("88017"),
        kind: "greeting",
        result: "skipped",
        reason_code: "affinity_below_threshold",
        receipt_key: "ww-rcpt-4d4e5f60",
        created_at: ago(60 * 20),
      },
      {
        persona_id: "lan",
        user_id: QQ("20431"),
        kind: "share",
        result: "sent",
        reason_code: "delivered",
        receipt_key: "ww-rcpt-a1b2c3d4",
        created_at: ago(60 * 26),
      },
      {
        persona_id: "mobai",
        user_id: TG("90033"),
        kind: "greeting",
        result: "skipped",
        reason_code: "affinity_below_threshold",
        receipt_key: "ww-rcpt-77889900",
        created_at: ago(60 * 30),
      },
      {
        persona_id: "qingtan",
        user_id: DC("604411"),
        kind: "follow_up",
        result: "deferred",
        reason_code: "deferred_by_scheduler",
        receipt_key: "ww-rcpt-e5e5d4d4",
        created_at: ago(60 * 44),
      },
      {
        persona_id: "yu",
        user_id: TG("71920"),
        kind: "greeting",
        result: "sent",
        reason_code: "delivered",
        receipt_key: "ww-rcpt-3c3c2b2b",
        created_at: ago(60 * 50),
      },
      {
        persona_id: "lan",
        user_id: DC("551203"),
        kind: "care_check",
        result: "skipped",
        reason_code: "mystery_code_x",
        receipt_key: "ww-rcpt-99ab00cd",
        created_at: ago(60 * 60),
      },
    ],
    keys,
    backups: [],
  };
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function createDemoAdapter(getScenario: () => DemoScenario): HearthlightAdapter {
  const db = seed();
  const failing = new Set(["emotion", "group", "growth", "motivation"]);

  async function run<T>(name: string, full: () => T, empty: T): Promise<T> {
    await wait(380 + Math.random() * 320);
    const s = getScenario();
    if (s === "error" && failing.has(name))
      throw new AdapterError("server", `演示：${name} 接口返回 500`);
    if (s === "forbidden" && name === "keys")
      throw new AdapterError("forbidden", "演示：当前账号无权读取身份映射");
    if (s === "empty") return empty;
    return clone(full());
  }

  return {
    mode: "demo",
    getLifeState: () => run("life", () => db.life, { day: db.life.day, items: [] }),
    getRelationships: () => run("relationships", () => db.relationships, []),
    getEmotionState: () => run("emotion", () => db.emotions, []),
    getGroupState: () => run("group", () => db.groups, []),
    getGrowthState: () => run("growth", () => db.growth, []),
    getMotivationLog: () => run("motivation", () => db.motivation, []),
    getPersonKeys: () => run("keys", () => db.keys, []),
    async rekeyDryRun() {
      await wait(500);
      if (getScenario() === "forbidden")
        throw new AdapterError("forbidden", "演示：无权执行 rekey");
      // Only aliases explicitly bound by tmemory are proposed; bare IDs are never inferred.
      const bound = db.keys.filter(
        (k) => k.user_id === DC("551203") && k.person_key !== "person:xiaoman",
      );
      return {
        ok: true,
        dry_run: true,
        plan: bound.length
          ? [
              {
                persona_id: "lan",
                person_id: "person:xiaoman",
                aliases: bound.map((b) => b.user_id),
              },
            ]
          : [],
        results: {
          skipped_bare_ids: db.keys
            .filter((k) => !k.user_id.includes(":") && !k.person_key)
            .map((k) => k.user_id),
        },
      };
    },
    async migrate(person_id, aliases) {
      await wait(700);
      if (getScenario() === "forbidden") throw new AdapterError("forbidden", "演示：无权执行迁移");
      const path = `demo://backups/person-migrate-${Date.now()}.json`;
      db.backups.push({ path, keys: clone(db.keys), relationships: clone(db.relationships) });
      let affected = 0;
      for (const k of db.keys)
        if (aliases.includes(k.user_id)) {
          k.person_key = person_id;
          affected += k.rows;
        }
      for (const r of db.relationships) if (aliases.includes(r.user_id)) r.person_key = person_id;
      return { ok: true, backup_path: path, affected_rows: affected };
    },
    async rollback() {
      await wait(600);
      const b = db.backups.pop();
      if (!b) throw new AdapterError("server", "没有可回滚的备份");
      db.keys = b.keys;
      db.relationships = b.relationships;
      return { ok: true, backup_path: b.path };
    },
  };
}
