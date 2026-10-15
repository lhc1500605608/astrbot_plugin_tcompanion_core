import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { PageHeader, Panel, QueryView, Meter, Tag, KV } from "@/components/hl/primitives";
import {
  Details,
  SearchField,
  Filter,
  PagedTable,
  IdentityText,
  fieldClass,
} from "@/components/hl/records";
import {
  useRelationships,
  usePersonaName,
  useEmotions,
  useGrowth,
} from "@/lib/hearthlight/context";
import {
  stageLabel,
  platformOf,
  platformLabel,
  fmtTime,
  identityKind,
  IDENTITY_LABEL,
  modeInfo,
  phaseLabel,
} from "@/lib/hearthlight/labels";
import type { RelationshipItem } from "@/lib/hearthlight/types";
export const Route = createFileRoute("/relationships")({ component: Relationships });
function Relationships() {
  const q = useRelationships(),
    emo = useEmotions(),
    growth = useGrowth(),
    personaName = usePersonaName();
  const [search, S] = useState(""),
    [stage, T] = useState("all"),
    [persona, P] = useState("all"),
    [platform, F] = useState("all"),
    [sort, O] = useState("recent"),
    [selected, D] = useState<RelationshipItem | null>(null);
  const all = (q.data ?? []).filter((r) => !r.is_group);
  const rows = useMemo(
    () =>
      all
        .filter(
          (r) =>
            (!search ||
              [r.nickname, r.user_id, r.person_key, r.persona_id]
                .join(" ")
                .toLowerCase()
                .includes(search.toLowerCase())) &&
            (stage === "all" || r.stage === stage) &&
            (persona === "all" || r.persona_id === persona) &&
            (platform === "all" || platformOf(r.user_id) === platform),
        )
        .sort((a, b) =>
          sort === "affinity"
            ? b.affinity - a.affinity
            : sort === "name"
              ? (a.nickname ?? a.user_id).localeCompare(b.nickname ?? b.user_id)
              : Date.parse(b.updated_at) - Date.parse(a.updated_at),
        ),
    [all, search, stage, persona, platform, sort],
  );
  const emotion = emo.data?.find(
      (e) => e.user_id === selected?.user_id && e.persona_id === selected?.persona_id,
    ),
    gr = growth.data?.find(
      (e) => e.user_id === selected?.user_id && e.persona_id === selected?.persona_id,
    );
  return (
    <>
      <PageHeader
        title="关系"
        desc="看见每一段关系的距离与温度。相同原生 ID 的不同平台身份保持独立。"
      />
      <Panel title="关系档案" bodyClass="p-0">
        <div className="flex flex-wrap gap-2 border-b p-4">
          <SearchField
            value={search}
            onChange={(v) => {
              S(v);
              D(null);
            }}
          />
          <Filter
            label="阶段"
            value={stage}
            onChange={T}
            options={[...new Set(all.map((r) => r.stage))].map((v) => [v, stageLabel(v)])}
          />
          <Filter
            label="人格"
            value={persona}
            onChange={P}
            options={[...new Set(all.map((r) => r.persona_id))].map((v) => [v, personaName(v)])}
          />
          <Filter
            label="平台"
            value={platform}
            onChange={F}
            options={[...new Set(all.map((r) => platformOf(r.user_id)))].map((v) => [
              v,
              platformLabel(v),
            ])}
          />
          <select
            aria-label="排序"
            value={sort}
            onChange={(e) => O(e.target.value)}
            className={fieldClass}
          >
            <option value="recent">最近更新</option>
            <option value="affinity">好感度优先</option>
            <option value="name">按名称</option>
          </select>
          <Button
            variant="ghost"
            onClick={() => {
              S("");
              T("all");
              P("all");
              F("all");
            }}
          >
            清空筛选
          </Button>
        </div>
        <QueryView q={q} isEmpty={(d) => !d.length}>
          {() => (
            <PagedTable
              rows={rows}
              rowKey={(r) => r.persona_id + "|" + r.user_id}
              onRow={D}
              columns={[
                {
                  label: "人物",
                  cell: (r) => (
                    <>
                      <span>{r.nickname ?? r.user_id}</span>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {platformLabel(platformOf(r.user_id))} ·{" "}
                        {IDENTITY_LABEL[identityKind(r.user_id, r.person_key)]}
                      </div>
                    </>
                  ),
                },
                { label: "人格", cell: (r) => personaName(r.persona_id) },
                { label: "关系阶段", cell: (r) => <Tag>{stageLabel(r.stage)}</Tag> },
                {
                  label: "好感度",
                  cell: (r) => (
                    <div className="w-24">
                      <span className="text-xs">{Math.round(r.affinity * 100)}%</span>
                      <Meter value={r.affinity} />
                    </div>
                  ),
                },
                { label: "羁绊", cell: (r) => (r.bond ? <Tag tone="ok">已建立</Tag> : "—") },
                {
                  label: "更新",
                  cell: (r) => (
                    <span className="whitespace-nowrap text-xs text-muted-foreground">
                      {fmtTime(r.updated_at)}
                    </span>
                  ),
                },
              ]}
            />
          )}
        </QueryView>
      </Panel>
      <Details title={selected?.nickname ?? "关系详情"} open={!!selected} onClose={() => D(null)}>
        {selected && (
          <>
            <KV
              items={[
                ["人格", personaName(selected.persona_id)],
                ["关系阶段", stageLabel(selected.stage)],
                ["好感度", `${Math.round(selected.affinity * 100)}%`],
                ["原始身份", <IdentityText value={selected.user_id} />],
                [
                  "Person",
                  identityKind(selected.user_id, selected.person_key) === "confirmed" ? (
                    <IdentityText value={selected.person_key ?? selected.user_id} />
                  ) : (
                    "未确认，按来源身份隔离"
                  ),
                ],
                ["更新", fmtTime(selected.updated_at)],
              ]}
            />
            <Panel title="陪伴状态">
              <KV
                items={[
                  ["表达模式", emotion ? modeInfo(emotion.mode).label : "暂无记录"],
                  ["成长阶段", phaseLabel(gr?.phase)],
                  ["成长说明", String(gr?.note ?? "暂无说明")],
                ]}
              />
            </Panel>
            <p className="text-xs text-muted-foreground">
              关系数据只读。身份归属和迁移请前往身份管理；不会根据相同裸 ID 自动归并。
            </p>
          </>
        )}
      </Details>
    </>
  );
}
