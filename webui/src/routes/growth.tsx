import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Sprout } from "lucide-react";
import { PageHeader, Panel, QueryView, Meter, Tag, EmptyState } from "@/components/hl/primitives";
import { SearchField, Filter, Details, RawDetails, IdentityText } from "@/components/hl/records";
import { useGrowth, usePersonaName } from "@/lib/hearthlight/context";
import type { GrowthItem } from "@/lib/hearthlight/types";

export const Route = createFileRoute("/growth")({ component: Growth });

function Growth() {
  const q = useGrowth();
  const name = usePersonaName();
  const [search, S] = useState("");
  const [persona, P] = useState("all");
  const [selected, D] = useState<GrowthItem | null>(null);

  return (
    <>
      <PageHeader
        title="成长"
        desc="由既有关系账目确定性派生的等级与短标签；无趋势回放，也不引入新写入。"
      />
      <div className="mb-5 flex gap-2">
        <SearchField value={search} onChange={S} placeholder="搜索身份或人格" />
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
              [i.user_id, i.persona_id, ...i.traits].join(" ").includes(search),
          );
          return rows.length ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {rows.map((g) => (
                <Panel
                  key={g.persona_id + "|" + g.user_id}
                  title={name(g.persona_id)}
                  icon={<Sprout className="size-4" />}
                  actions={
                    <Tag>
                      Lv {g.level} / {g.max_level}
                    </Tag>
                  }
                >
                  <IdentityText value={g.user_id} />
                  <div className="mt-4">
                    <div className="mb-1 flex justify-between text-xs text-muted-foreground">
                      <span>本级进度</span>
                      <span>{Math.round(g.progress * 100)}%</span>
                    </div>
                    <Meter value={g.progress} label="本级进度" />
                  </div>
                  <div className="mt-4 flex flex-wrap gap-1.5">
                    {g.traits.length ? (
                      g.traits.map((trait) => <Tag key={trait}>{trait}</Tag>)
                    ) : (
                      <span className="text-xs text-muted-foreground">暂无标签</span>
                    )}
                  </div>
                  <button
                    className="mt-4 text-xs text-primary underline underline-offset-4"
                    onClick={() => D(g)}
                  >
                    查看原始字段
                  </button>
                </Panel>
              ))}
            </div>
          ) : (
            <EmptyState title="没有匹配的成长记录" />
          );
        }}
      </QueryView>
      <Details title="成长记录" open={!!selected} onClose={() => D(null)}>
        {selected && <RawDetails record={selected as unknown as Record<string, unknown>} />}
      </Details>
    </>
  );
}
