export const STAGES: Record<string, { label: string; rank: number }> = {
  stranger: { label: "陌生", rank: 0 },
  acquaintance: { label: "相识", rank: 1 },
  friend: { label: "朋友", rank: 2 },
  close: { label: "亲近", rank: 3 },
  intimate: { label: "亲密", rank: 4 },
};
export const stageLabel = (s: string) => STAGES[s]?.label ?? s;
export const isCloseStage = (s: string) =>
  ["亲近", "亲密"].includes(s) || (STAGES[s]?.rank ?? 0) >= 3;

export const EMOTIONS: Record<string, string> = {
  calm: "平静",
  content: "满足",
  joyful: "愉悦",
  wistful: "怅然",
  anxious: "不安",
  tired: "倦怠",
};
export const emotionLabel = (s: string) => EMOTIONS[s] ?? s;

export const MODES: Record<string, { label: string; hint: string }> = {
  gentle: { label: "温柔陪伴", hint: "语气放缓，以倾听和回应为主" },
  playful: { label: "轻松俏皮", hint: "可以开玩笑，节奏更轻快" },
  quiet: { label: "安静简短", hint: "回复简短，减少打扰" },
  supportive: { label: "支持鼓励", hint: "优先共情与肯定，不急于给建议" },
  reserved: { label: "克制保留", hint: "保持礼貌距离，不主动深入" },
};
export const modeInfo = (m: string) =>
  MODES[m] ?? { label: m || "未知", hint: "未收录的表达模式，原样显示" };

export const ACTIVITY_LEVELS: Record<string, { label: string; tone: "ok" | "warn" | "muted" }> = {
  high: { label: "活跃", tone: "warn" },
  medium: { label: "中等", tone: "muted" },
  low: { label: "安静", tone: "ok" },
};
export const activityLevelInfo = (v: string) =>
  ACTIVITY_LEVELS[v] ?? { label: v || "未知", tone: "muted" as const };

export const GROUP_REASONS: Record<string, string> = {
  ok: "可以参与",
  cooldown: "冷却中",
  hourly_limit: "本小时额度已用完",
  group_busy: "群消息过密，建议稍后",
  disabled: "群聊参与建议已关闭",
};
export const groupReasonLabel = (v: string) => GROUP_REASONS[v] ?? `未知原因（${v}）`;

export const RESULTS: Record<string, { label: string; tone: "ok" | "warn" | "muted" | "bad" }> = {
  sent: { label: "已发送", tone: "ok" },
  skipped: { label: "已跳过", tone: "muted" },
  deferred: { label: "已延后", tone: "warn" },
  failed: { label: "失败", tone: "bad" },
};

export const REASONS: Record<string, string> = {
  delivered: "WarmWhisper 已确认送达",
  quiet_hours: "处于安静时段，延后处理",
  cooldown: "距上次主动联系过近，冷却中",
  affinity_below_threshold: "好感度未达主动联系阈值",
  user_recently_active: "对方近期刚活跃，无需打扰",
  channel_error: "投递通道返回错误",
  deferred_by_scheduler: "调度器排队延后",
};
export const reasonLabel = (c: string) => REASONS[c] ?? (c || "未记录原因");

export const KINDS: Record<string, string> = {
  greeting: "问候",
  follow_up: "后续关怀",
  care_check: "状态关心",
  share: "分享",
  proactive_outcome: "主动结果回执",
};


export const PLATFORMS: Record<string, string> = {
  aiocqhttp: "QQ",
  telegram: "Telegram",
  discord: "Discord",
};
export function platformOf(userId: string) {
  const umo = userId.startsWith("p:") ? userId.slice(2) : userId;
  if (!umo.includes(":")) return "legacy";
  return umo.split(":")[0] ?? "unknown";
}
export const platformLabel = (p: string) => (p === "legacy" ? "旧裸 ID" : (PLATFORMS[p] ?? p));
export const nativeId = (userId: string) => userId.split(":").at(-1) ?? userId;

export type IdentityKind = "confirmed" | "umo" | "legacy";
export function identityKind(userId: string, personKey: string | null): IdentityKind {
  if (
    personKey?.startsWith("person:") ||
    (personKey && personKey !== userId && !personKey.startsWith("p:"))
  )
    return "confirmed";
  if (userId.includes(":")) return "umo";
  return "legacy";
}
export const IDENTITY_LABEL: Record<IdentityKind, string> = {
  confirmed: "已确认人物",
  umo: "完整 UMO 隔离身份",
  legacy: "旧裸 ID 待归属",
};

export function fmtRel(iso?: string) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const d = Math.round((Date.now() - t) / 60000);
  if (d < 0) return `${Math.abs(d)} 分钟后`;
  if (d < 1) return "刚刚";
  if (d < 60) return `${d} 分钟前`;
  if (d < 1440) return `${Math.floor(d / 60)} 小时前`;
  return `${Math.floor(d / 1440)} 天前`;
}
export function fmtTime(iso?: string | number) {
  if (iso === undefined) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
export function isToday(iso?: string) {
  if (!iso) return false;
  const d = new Date(iso);
  const n = new Date();
  return d.toDateString() === n.toDateString();
}
