import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Sprout } from "lucide-react";
import { PageHeader, Panel, QueryView, Meter, Tag, EmptyState } from "@/components/hl/primitives";
import { SearchField, Filter, Details, RawDetails } from "@/components/hl/records";
import { useGrowth, usePersonaName } from "@/lib/hearthlight/context";
import { phaseLabel, fmtTime } from "@/lib/hearthlight/labels";
import type { GrowthItem } from "@/lib/hearthlight/types";
export const Route = createFileRoute("/growth")({ component: Growth });
function Growth() {
  const q = useGrowth(),
    name = usePersonaName();
  const [search, S] = useState(""),
    [persona, P] = useState("all"),
    [selected, D] = useState<GrowthItem | null>(null);
  return (
    <>
      <PageHeader
        title="成长"
        desc="关系在日常互动中缓慢积累。只展示当前推导状态，不编造历史趋势。"
      />
      <div className="mb-5 flex gap-2">
        <SearchField value={search} onChange={S} />
        <Filter
          label="人格"
          value={persona}
          onChange={P}
          options={[...new Set((q.data ?? []).map((i) => i.persona_id))].map((i) => [i, name(i)])}
        />
      </div>
      <QueryView q={q} isEmpty={(d) => !d.length}>
        {(data) => {
          const rows = data.filter(
            (i) =>
              (persona === "all" || i.persona_id === persona) &&
              [i.user_id, i.persona_id, i.note].join(" ").includes(search),
          );
          return rows.length ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {rows.map((g, i) => (
                <Panel
                  key={g.persona_id + g.user_id + i}
                  title={name(g.persona_id)}
                  icon={<Sprout className="size-4" />}
                  actions={<Tag>{phaseLabel(g.phase)}</Tag>}
                >
                  <code className="block break-all text-xs text-muted-foreground">{g.user_id}</code>
                  <p className="my-4 min-h-10 text-sm">
                    {g.note ?? "尚无成长说明，保留当前记录。"}
                  </p>
                  {typeof g.trust === "number" && (
                    <div className="mb-3">
                      <p className="mb-1 text-xs text-muted-foreground">
                        信任 {Math.round(g.trust * 100)}%
                      </p>
                      <Meter label="信任" value={g.trust} />
                    </div>
                  )}
                  {typeof g.familiarity === "number" && (
                    <div>
                      <p className="mb-1 text-xs text-muted-foreground">
                        熟悉 {Math.round(g.familiarity * 100)}%
                      </p>
                      <Meter label="熟悉" value={g.familiarity} tone="amber" />
                    </div>
                  )}
                  <div className="mt-4 flex justify-between text-xs text-muted-foreground">
                    <span>{fmtTime(g.updated_at)}</span>
                    <button className="text-primary underline" onClick={() => D(g)}>
                      原始字段
                    </button>
                  </div>
                </Panel>
              ))}
            </div>
          ) : (
            <EmptyState title="没有匹配的成长记录" />
          );
        }}
      </QueryView>
      <Details title="成长记录" open={!!selected} onClose={() => D(null)}>
        {selected && <RawDetails record={selected} />}
      </Details>
    </>
  );
}
