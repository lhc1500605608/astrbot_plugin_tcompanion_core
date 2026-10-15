// Typed contracts mirroring the existing Hearthlight plugin HTTP endpoints.
// Optional fields are tolerated; unknown extra fields are preserved.

export interface LifeItem {
  persona_id: string;
  activity: string;
  scene: string;
  energy: number; // 0..1
  summary: string;
  as_of: string;
  persona_name?: string;
}
export interface LifeState {
  day: string;
  items: LifeItem[];
}

export interface RelationshipItem {
  user_id: string;
  persona_id: string;
  stage: string;
  affinity: number; // 0..1
  bond: boolean | 0 | 1;
  updated_at: string;
  person_key: string | null;
  is_group: boolean;
  nickname?: string;
}

export interface EmotionItem {
  persona_id: string;
  user_id: string;
  state: string;
  valence: number; // -1..1
  last_event: string;
  mode: string;
  as_of: string;
}

export type GroupActivityLevel = "low" | "medium" | "high";

/** Flat projection returned by the host's `group-state` endpoint. */
export interface GroupItem {
  umo: string;
  member_count: number;
  activity_level: GroupActivityLevel;
  topic: string;
  topic_age_min: number | null;
  last_activity: string;
  allow: boolean;
  reason: string;
  cooldown_remaining_sec: number;
  hourly_remaining: number;
}

/** Flat projection returned by the host's `growth-state` endpoint. */
export interface GrowthItem {
  persona_id: string;
  user_id: string;
  level: number;
  progress: number;
  max_level: number;
  traits: string[];
}

export interface MotivationItem {
  persona_id: string;
  user_id: string;
  kind: string;
  reason_code: string;
  receipt_key: string;
  result?: string;
  created_at?: string;
  selected_reason?: string;
  blocked_reason?: string;
  adopted?: boolean | 0 | 1;
  reason?: string;
  value?: number;
  [k: string]: unknown;
}

export interface PersonKeyItem {
  persona_id: string;
  user_id: string;
  rows: number;
  person_key: string | null;
  nickname?: string;
  [k: string]: unknown;
}

export interface RekeyPlanEntry {
  persona_id: string;
  person_id: string;
  aliases: string[];
}
export interface RekeyResult {
  ok: boolean;
  dry_run: boolean;
  plan: RekeyPlanEntry[];
  results?: unknown;
}
export interface MigrateResult {
  ok: boolean;
  backup_path?: string;
  affected_rows?: number;
  [k: string]: unknown;
}

export type AdapterMode = "demo" | "host";

export interface HearthlightAdapter {
  mode: AdapterMode;
  getLifeState(): Promise<LifeState>;
  getRelationships(): Promise<RelationshipItem[]>;
  getEmotionState(): Promise<EmotionItem[]>;
  getGroupState(): Promise<GroupItem[]>;
  getGrowthState(): Promise<GrowthItem[]>;
  getMotivationLog(): Promise<MotivationItem[]>;
  getPersonKeys(): Promise<PersonKeyItem[]>;
  rekeyDryRun(): Promise<RekeyResult>;
  migrate(person_id: string, aliases: string[]): Promise<MigrateResult>;
  rollback(): Promise<MigrateResult>;
}

export type AdapterErrorKind = "network" | "forbidden" | "invalid" | "server";

export class AdapterError extends Error {
  kind: AdapterErrorKind;
  constructor(kind: AdapterErrorKind, message: string) {
    super(message);
    this.kind = kind;
    this.name = "AdapterError";
  }
}
