import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { PageHeader, Panel, QueryView, Tag } from "@/components/hl/primitives";
import { SearchField, Filter, PagedTable, IdentityText } from "@/components/hl/records";
import { useMotivation, usePersonaName } from "@/lib/hearthlight/context";
import { RESULTS, reasonLabel, fmtTime, KINDS } from "@/lib/hearthlight/labels";
export const Route = createFileRoute("/motivation")({ component: Motivation });
function Motivation() {
  const q = useMotivation(),
    name = usePersonaName();
  const [search, S] = useState(""),
    [status, T] = useState("all"),
    [persona, P] = useState("all");
  return (
    <>
      <PageHeader
        title="主动记录"
        desc="Hearthlight 保存状态与结果回执；主动生成和投递由 WarmWhisper 负责。这里只展示元数据。"
      />
      <Panel title="最近 100 条记录" bodyClass="p-0">
        <div className="flex flex-wrap gap-2 border-b p-4">
          <SearchField value={search} onChange={S} placeholder="搜索身份、原因码或回执 ID" />
          <Filter
            label="结果"
            value={status}
            onChange={T}
            options={Object.entries(RESULTS).map(([v, i]) => [v, i.label])}
          />
          <Filter
            label="人格"
            value={persona}
            onChange={P}
            options={[...new Set((q.data ?? []).map((i) => i.persona_id))].map((i) => [i, name(i)])}
          />
        </div>
        <QueryView q={q} isEmpty={(d) => !d.length}>
          {(data) => (
            <PagedTable
              rows={data
                .filter(
                  (i) =>
                    (status === "all" || i.result === status) &&
                    (persona === "all" || i.persona_id === persona) &&
                    [i.user_id, i.reason_code, i.receipt_key].join(" ").includes(search),
                )
                .sort((a, b) => Date.parse(b.created_at ?? "") - Date.parse(a.created_at ?? ""))}
              rowKey={(i) => i.persona_id + i.user_id + i.receipt_key}
              columns={[
                {
                  label: "时间 / 类型",
                  cell: (i) => (
                    <>
                      <p className="whitespace-nowrap">{fmtTime(i.created_at)}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {KINDS[i.kind] ?? i.kind}
                      </p>
                    </>
                  ),
                },
                {
                  label: "人物 / 人格",
                  cell: (i) => (
                    <>
                      <p>{name(i.persona_id)}</p>
                      <code className="text-xs text-muted-foreground">{i.user_id}</code>
                    </>
                  ),
                },
                {
                  label: "结果",
                  cell: (i) => (
                    <Tag tone={RESULTS[i.result ?? ""]?.tone ?? "muted"}>
                      {RESULTS[i.result ?? ""]?.label ?? i.result ?? "未提供"}
                    </Tag>
                  ),
                },
                {
                  label: "原因",
                  cell: (i) => (
                    <div>
                      <p>{reasonLabel(i.reason_code)}</p>
                      <code className="text-xs text-muted-foreground">{i.reason_code}</code>
                    </div>
                  ),
                },
                { label: "回执 ID", cell: (i) => <IdentityText value={i.receipt_key} /> },
              ]}
            />
          )}
        </QueryView>
      </Panel>
    </>
  );
}
