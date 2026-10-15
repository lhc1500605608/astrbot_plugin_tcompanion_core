import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Users } from "lucide-react";
import { PageHeader, Panel, QueryView, Tag, Meter, EmptyState } from "@/components/hl/primitives";
import { SearchField, Filter, Details, RawDetails } from "@/components/hl/records";
import { useGroups, usePersonaName } from "@/lib/hearthlight/context";
import { ADVISORY, fmtRel } from "@/lib/hearthlight/labels";
import type { GroupItem } from "@/lib/hearthlight/types";
export const Route = createFileRoute("/groups")({ component: Groups });
function Groups() {
  const q = useGroups(),
    name = usePersonaName();
  const [search, S] = useState(""),
    [advice, A] = useState("all"),
    [selected, D] = useState<GroupItem | null>(null);
  return (
    <>
      <PageHeader
        title="群聊"
        desc="观察群内节奏，提供参与建议。建议不代表投递授权，也不包含私聊关系数据。"
      />
      <div className="mb-5 flex flex-wrap gap-2">
        <SearchField value={search} onChange={S} placeholder="搜索群名称或完整 UMO" />
        <Filter
          label="建议"
          value={advice}
          onChange={A}
          options={Object.entries(ADVISORY).map(([v, i]) => [v, i.label])}
        />
      </div>
      <QueryView q={q} isEmpty={(d) => !d.length}>
        {(data) => {
          const rows = data.filter(
            (g) =>
              (!search || [g.group_name, g.group_id].join(" ").includes(search)) &&
              (advice === "all" || g.advisory === advice),
          );
          return rows.length ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {rows.map((g, i) => (
                <Panel
                  key={g.group_id ?? i}
                  title={
                    <button className="text-left hover:underline" onClick={() => D(g)}>
                      {g.group_name ?? g.group_id ?? "未知群聊"}
                    </button>
                  }
                  icon={<Users className="size-4" />}
                  actions={
                    <Tag tone={ADVISORY[g.advisory ?? ""]?.tone ?? "muted"}>
                      {ADVISORY[g.advisory ?? ""]?.label ?? "暂无建议"}
                    </Tag>
                  }
                >
                  <p className="mb-4 text-xs text-muted-foreground">
                    {name(g.persona_id)} · {fmtRel(g.last_active_at)}
                  </p>
                  <div className="mb-4 flex justify-between text-sm">
                    <span>
                      活跃成员 <b>{g.active_members ?? "—"}</b>
                    </span>
                    <span>
                      消息 / 小时 <b>{g.messages_per_hour ?? "—"}</b>
                    </span>
                  </div>
                  {typeof g.activity === "number" && <Meter value={g.activity} label="群活跃度" />}
                  <p className="mt-4 text-sm text-muted-foreground">
                    {g.advisory_reason ?? "暂无建议原因"}
                  </p>
                  <button
                    className="mt-4 text-xs text-primary underline underline-offset-4"
                    onClick={() => D(g)}
                  >
                    查看群详情
                  </button>
                </Panel>
              ))}
            </div>
          ) : (
            <EmptyState title="没有匹配的群聊" />
          );
        }}
      </QueryView>
      <Details
        title={selected?.group_name ?? "群聊详情"}
        open={!!selected}
        onClose={() => D(null)}
        subtitle="群聊活动与参与建议 · 不包含私聊字段"
      >
        {selected && <RawDetails record={selected} />}
      </Details>
    </>
  );
}
