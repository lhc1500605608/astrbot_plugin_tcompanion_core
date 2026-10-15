import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Users } from "lucide-react";
import { PageHeader, Panel, QueryView, Tag, EmptyState } from "@/components/hl/primitives";
import { SearchField, Filter, Details, RawDetails } from "@/components/hl/records";
import { useGroups } from "@/lib/hearthlight/context";
import {
  activityLevelInfo,
  groupReasonLabel,
  fmtTime,
  fmtRel,
} from "@/lib/hearthlight/labels";
import type { GroupItem } from "@/lib/hearthlight/types";

export const Route = createFileRoute("/groups")({ component: Groups });

function topicAge(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "—";
  if (value < 1) return "刚刚";
  if (value < 60) return `${Math.round(value)} 分钟前`;
  if (value < 1440) return `${Math.floor(value / 60)} 小时前`;
  return `${Math.floor(value / 1440)} 天前`;
}

function Groups() {
  const q = useGroups();
  const [search, S] = useState("");
  const [activity, A] = useState("all");
  const [allow, V] = useState("all");
  const [selected, D] = useState<GroupItem | null>(null);

  return (
    <>
      <PageHeader
        title="群聊"
        desc="只展示群内轻量状态与参与建议，不包含私聊关系或人物画像。"
      />
      <div className="mb-5 flex flex-wrap gap-2">
        <SearchField value={search} onChange={S} placeholder="搜索完整 UMO 或话题" />
        <Filter
          label="活跃度"
          value={activity}
          onChange={A}
          options={[
            ["low", "安静"],
            ["medium", "中等"],
            ["high", "活跃"],
          ]}
        />
        <Filter
          label="建议"
          value={allow}
          onChange={V}
          options={[
            ["yes", "可以参与"],
            ["no", "暂缓参与"],
          ]}
        />
      </div>
      <QueryView q={q} isEmpty={(d) => !d.length}>
        {(data) => {
          const rows = data.filter(
            (g) =>
              (!search || [g.umo, g.topic].join(" ").includes(search)) &&
              (activity === "all" || g.activity_level === activity) &&
              (allow === "all" || (g.allow ? "yes" : "no") === allow),
          );
          return rows.length ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {rows.map((g) => {
                const activityInfo = activityLevelInfo(g.activity_level);
                return (
                  <Panel
                    key={g.umo}
                    title={
                      <button
                        className="max-w-full truncate text-left hover:underline"
                        onClick={() => D(g)}
                      >
                        {g.umo}
                      </button>
                    }
                    icon={<Users className="size-4" />}
                    actions={<Tag tone={g.allow ? "ok" : "warn"}>{groupReasonLabel(g.reason)}</Tag>}
                  >
                    <p className="mb-4 text-xs text-muted-foreground">
                      {activityInfo.label} · 最近活动 {fmtRel(g.last_activity)}
                    </p>
                    <p className="mb-4 text-sm">
                      话题：{g.topic ? <b>{g.topic}</b> : "暂无"}（{topicAge(g.topic_age_min)}）
                    </p>
                    <div className="mb-4 grid grid-cols-3 gap-2 text-sm">
                      <div>
                        <p className="text-xs text-muted-foreground">成员</p>
                        <b>{g.member_count}</b>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">本小时额度</p>
                        <b>{g.hourly_remaining}</b>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">冷却剩余</p>
                        <b>{g.cooldown_remaining_sec}s</b>
                      </div>
                    </div>
                    <p className="mt-4 text-xs text-muted-foreground">
                      建议由 core 提供，不代发消息；最后活动时间 {fmtTime(g.last_activity)}
                    </p>
                    <button
                      className="mt-4 text-xs text-primary underline underline-offset-4"
                      onClick={() => D(g)}
                    >
                      查看群详情
                    </button>
                  </Panel>
                );
              })}
            </div>
          ) : (
            <EmptyState title="没有匹配的群聊" />
          );
        }}
      </QueryView>
      <Details
        title={selected?.umo ?? "群聊详情"}
        open={!!selected}
        onClose={() => D(null)}
        subtitle="群聊活动与参与建议 · 不包含私聊字段"
      >
        {selected && <RawDetails record={selected as unknown as Record<string, unknown>} />}
      </Details>
    </>
  );
}
