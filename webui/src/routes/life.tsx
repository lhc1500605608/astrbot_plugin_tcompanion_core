import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { PageHeader, Panel, QueryView, Meter, Tag, ValenceBar } from "@/components/hl/primitives";
import { Filter, PagedTable } from "@/components/hl/records";
import { useLife, useEmotions, usePersonaName } from "@/lib/hearthlight/context";
import { emotionLabel, modeInfo, fmtTime } from "@/lib/hearthlight/labels";
export const Route = createFileRoute("/life")({ component: Life });
function Life() {
  const life = useLife(),
    emo = useEmotions(),
    name = usePersonaName();
  const [persona, P] = useState("all");
  return (
    <>
      <PageHeader
        title="生活与情绪"
        desc="生活节奏影响表达方式；这些状态是当前快照，不是人格配置。"
        actions={
          <Filter
            label="人格"
            value={persona}
            onChange={P}
            options={(life.data?.items ?? []).map((i) => [i.persona_id, name(i.persona_id)])}
          />
        }
      />
      <QueryView q={life} isEmpty={(d) => !d.items.length}>
        {(d) => (
          <div className="mb-6 grid gap-4 md:grid-cols-2">
            {d.items
              .filter((i) => persona === "all" || i.persona_id === persona)
              .map((i) => (
                <Panel
                  key={i.persona_id}
                  title={name(i.persona_id)}
                  actions={<Tag>{i.activity || "暂无活动"}</Tag>}
                >
                  <div className="mb-4 flex items-end justify-between">
                    <div>
                      <p className="font-display text-xl">{i.scene || "暂无场景"}</p>
                      <p className="mt-2 text-sm text-muted-foreground">
                        {i.summary || "暂无状态说明"}
                      </p>
                    </div>
                    <span className="font-display text-3xl">
                      {Math.round(i.energy * 100)}
                      <span className="text-sm">%</span>
                    </span>
                  </div>
                  <Meter label="能量" value={i.energy} tone="amber" />
                  <p className="mt-3 text-xs text-muted-foreground">更新于 {fmtTime(i.as_of)}</p>
                </Panel>
              ))}
          </div>
        )}
      </QueryView>
      <Panel title="情绪与表达" bodyClass="p-0">
        <QueryView q={emo} isEmpty={(d) => !d.length}>
          {(d) => (
            <PagedTable
              rows={d.filter((i) => persona === "all" || i.persona_id === persona)}
              rowKey={(i) => i.persona_id + i.user_id}
              columns={[
                {
                  label: "人格 / 身份",
                  cell: (i) => (
                    <>
                      <p>{name(i.persona_id)}</p>
                      <code className="text-xs text-muted-foreground">{i.user_id}</code>
                    </>
                  ),
                },
                { label: "情绪", cell: (i) => <Tag>{emotionLabel(i.state)}</Tag> },
                {
                  label: "效价",
                  cell: (i) => (
                    <div className="space-y-1">
                      <ValenceBar value={i.valence} />
                      <span className="text-xs">{i.valence.toFixed(2)}</span>
                    </div>
                  ),
                },
                {
                  label: "表达方式",
                  cell: (i) => (
                    <div>
                      <p>{modeInfo(i.mode).label}</p>
                      <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                        {modeInfo(i.mode).hint}
                      </p>
                    </div>
                  ),
                },
                { label: "最近事件", cell: (i) => i.last_event || "—" },
              ]}
            />
          )}
        </QueryView>
      </Panel>
    </>
  );
}
