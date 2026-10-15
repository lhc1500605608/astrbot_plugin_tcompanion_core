import { createFileRoute, Link } from "@tanstack/react-router";
import { Filter } from "@/components/hl/records";
import { Button } from "@/components/ui/button";
import {
  Panel,
  PageHeader,
  QueryView,
  Meter,
  DemoTag,
  EmptyState,
} from "@/components/hl/primitives";
import {
  useHL,
  useLife,
  useRelationships,
  useMotivation,
  usePersonKeys,
  useEmotions,
} from "@/lib/hearthlight/context";
import {
  stageLabel,
  isCloseStage,
  isToday,
  fmtRel,
  emotionLabel,
  modeInfo,
  reasonLabel,
  RESULTS,
} from "@/lib/hearthlight/labels";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "总览 · Hearthlight 守灯" },
      { name: "description", content: "陪伴关系、生活状态与主动记录总览（演示数据）。" },
      { property: "og:title", content: "总览 · Hearthlight 守灯" },
      { property: "og:description", content: "陪伴关系、生活状态与主动记录总览。" },
    ],
  }),
  component: Overview,
});

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="hl-card px-5 py-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-display text-2xl font-semibold">{value}</div>
    </div>
  );
}

function Overview() {
  const { connection, persona, setPersona } = useHL();
  const life = useLife(),
    rel = useRelationships(),
    mot = useMotivation(),
    keys = usePersonKeys(),
    emo = useEmotions();
  const priv = (rel.data ?? []).filter(
    (r) => !r.is_group && (persona === "all" || r.persona_id === persona),
  );
  return (
    <div>
      <PageHeader
        title="让陪伴，有迹可循。"
        desc="Hearthlight 汇总各人格的关系、生活与情绪状态。"
        actions={
          <>
            {connection.status === "demo" && <DemoTag />}
            <Filter
              label="人格"
              value={persona}
              onChange={setPersona}
              options={(life.data?.items ?? []).map((i) => [
                i.persona_id,
                i.persona_name ?? i.persona_id,
              ])}
            />
          </>
        }
      />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat
          label="关系人数"
          value={rel.data ? new Set(priv.map((r) => r.person_key || r.user_id)).size : "—"}
        />
        <Stat
          label="亲密关系"
          value={rel.data ? priv.filter((r) => isCloseStage(r.stage)).length : "—"}
        />
        <Stat
          label="今日主动记录"
          value={
            mot.data
              ? mot.data.filter(
                  (m) => isToday(m.created_at) && (persona === "all" || m.persona_id === persona),
                ).length
              : "—"
          }
        />
        <Stat
          label="待确认身份"
          value={
            keys.data
              ? keys.data.filter(
                  (k) => !k.user_id.includes(":") && (!k.person_key || k.person_key === k.user_id),
                ).length
              : "—"
          }
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="人物生活状态" className="lg:col-span-2">
          <QueryView q={life} isEmpty={(d) => !d.items.length}>
            {(d) => (
              <div className="grid gap-4 sm:grid-cols-2">
                {d.items
                  .filter((i) => persona === "all" || i.persona_id === persona)
                  .map((i) => (
                    <div key={i.persona_id} className="rounded-lg border p-4">
                      <div className="flex justify-between">
                        <span className="font-medium">{i.persona_name ?? i.persona_id}</span>
                        <span className="text-xs text-muted-foreground">{fmtRel(i.as_of)}</span>
                      </div>
                      <div className="mt-1 text-sm">
                        {i.activity} · <span className="text-muted-foreground">{i.scene}</span>
                      </div>
                      <Meter value={i.energy} tone="amber" className="mt-3" label="能量" />
                      <p className="mt-2 text-xs text-muted-foreground">{i.summary}</p>
                    </div>
                  ))}
              </div>
            )}
          </QueryView>
        </Panel>
        <Panel title="情绪与表达模式">
          <QueryView q={emo} isEmpty={(d) => !d.length}>
            {(d) => (
              <ul className="space-y-2 text-sm">
                {d
                  .filter((e) => persona === "all" || e.persona_id === persona)
                  .map((e, i) => (
                    <li key={i} className="flex justify-between">
                      <span>{emotionLabel(e.state)}</span>
                      <span className="text-muted-foreground">{modeInfo(e.mode).label}</span>
                    </li>
                  ))}
              </ul>
            )}
          </QueryView>
        </Panel>
        <Panel
          title="关系预览"
          className="lg:col-span-2"
          actions={
            <Button asChild variant="ghost" size="sm">
              <Link to="/relationships">查看全部</Link>
            </Button>
          }
        >
          <QueryView q={rel} isEmpty={(d) => !d.filter((r) => !r.is_group).length}>
            {() => (
              <ul className="divide-y text-sm">
                {priv.slice(0, 5).map((r) => (
                  <li key={r.persona_id + r.user_id} className="flex justify-between py-2">
                    <span>{r.nickname ?? r.user_id}</span>
                    <span className="text-muted-foreground">
                      {stageLabel(r.stage)} · {fmtRel(r.updated_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </QueryView>
        </Panel>
        <Panel
          title="最近主动记录"
          actions={
            <Button asChild variant="ghost" size="sm">
              <Link to="/motivation">查看全部</Link>
            </Button>
          }
        >
          <QueryView q={mot} isEmpty={(d) => !d.length} empty={<EmptyState />}>
            {(d) => (
              <ul className="space-y-2 text-sm">
                {d
                  .filter((m) => persona === "all" || m.persona_id === persona)
                  .slice(0, 5)
                  .map((m) => (
                    <li key={m.receipt_key}>
                      <div>
                        {RESULTS[m.result ?? ""]?.label ?? m.result} · {fmtRel(m.created_at)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {reasonLabel(m.reason_code)}
                      </div>
                    </li>
                  ))}
              </ul>
            )}
          </QueryView>
        </Panel>
      </div>
    </div>
  );
}
