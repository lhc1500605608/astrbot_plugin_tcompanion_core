import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, Undo2, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { PageHeader, Panel, QueryView, Tag, DemoTag, KV } from "@/components/hl/primitives";
import { SearchField, Filter, IdentityText, fieldClass } from "@/components/hl/records";
import { useHL, usePersonKeys, usePersonaName } from "@/lib/hearthlight/context";
import { identityKind, IDENTITY_LABEL } from "@/lib/hearthlight/labels";
import type { RekeyPlanEntry } from "@/lib/hearthlight/types";
export const Route = createFileRoute("/identity")({ component: Identity });
function Identity() {
  const q = usePersonKeys(),
    name = usePersonaName(),
    { adapter, connection, refresh } = useHL();
  const [search, S] = useState(""),
    [kind, K] = useState("all"),
    [aliases, A] = useState<string[]>([]),
    [target, T] = useState(""),
    [preview, V] = useState(false),
    [plans, L] = useState<RekeyPlanEntry[] | null>(null),
    [action, C] = useState<"merge" | "rollback" | null>(null),
    [step, B] = useState(1),
    [ack, E] = useState(false),
    [typed, Y] = useState(""),
    [busy, U] = useState(false),
    [backup, H] = useState<string | null>(null),
    [error, J] = useState("");
  const rows = q.data ?? [];
  const selected = rows.filter((r) => aliases.includes(r.user_id));
  const affected = selected.reduce((n, r) => n + Number(r.rows || 0), 0);
  const legacy = selected.some((r) => identityKind(r.user_id, r.person_key) === "legacy");
  function reset() {
    V(false);
    E(false);
    Y("");
    B(1);
    J("");
  }
  function toggle(id: string) {
    A((old) => (old.includes(id) ? old.filter((i) => i !== id) : [...old, id]));
    reset();
  }
  async function dryRun() {
    if (!adapter) return;
    U(true);
    J("");
    try {
      const r = await adapter.rekeyDryRun();
      L(r.plan ?? []);
      toast.success("只读迁移计划已生成");
    } catch (e) {
      J(e instanceof Error ? e.message : String(e));
    } finally {
      U(false);
    }
  }
  async function execute() {
    if (!adapter || busy) return;
    U(true);
    J("");
    try {
      const r =
        action === "rollback"
          ? await adapter.rollback()
          : await adapter.migrate(target.trim(), aliases);
      H(action === "rollback" ? null : String(r.backup_path ?? "备份由核心管理"));
      toast.success(connection.status === "demo" ? "演示操作完成，仅修改内存" : "操作已完成");
      C(null);
      A([]);
      reset();
      refresh();
    } catch (e) {
      J(e instanceof Error ? e.message : String(e));
    } finally {
      U(false);
    }
  }
  const options = [
    ...new Set(
      rows.map((r) => r.person_key).filter((v): v is string => !!v && v.startsWith("person:")),
    ),
  ];
  return (
    <>
      <PageHeader
        title="身份管理"
        desc="明确归属，再连接状态。裸 ID 不会自动绑定到任何平台或人物。"
        actions={
          <>
            <Button variant="outline" disabled={busy || !adapter} onClick={dryRun}>
              <ShieldCheck />
              只读迁移计划
            </Button>
            <Button
              variant="outline"
              disabled={busy || !adapter}
              onClick={() => {
                C("rollback");
                E(false);
                J("");
              }}
            >
              <Undo2 />
              回滚上次合并
            </Button>
          </>
        }
      />
      {connection.status === "demo" && (
        <div className="mb-5 flex items-center gap-3 rounded-lg border border-amber/40 bg-amber-soft p-3 text-sm text-amber-foreground">
          <DemoTag>演示操作</DemoTag>这里的合并与回滚只影响本页内存，刷新页面可重置。
        </div>
      )}
      {error && (
        <div
          role="alert"
          className="mb-4 rounded-lg border border-destructive/40 p-3 text-sm text-destructive"
        >
          {error}
        </div>
      )}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel title="身份来源" bodyClass="p-0">
          <div className="flex flex-wrap gap-2 border-b p-4">
            <SearchField value={search} onChange={S} />
            <Filter
              label="身份类型"
              value={kind}
              onChange={K}
              options={Object.entries(IDENTITY_LABEL)}
            />
          </div>
          <QueryView q={q} isEmpty={(d) => !d.length}>
            {(data) => {
              const filtered = data.filter(
                (r) =>
                  (kind === "all" || identityKind(r.user_id, r.person_key) === kind) &&
                  [r.nickname, r.user_id, r.person_key].join(" ").includes(search),
              );
              return (
                <div className="divide-y">
                  {filtered.length ? (
                    filtered.map((r, i) => (
                      <div
                        key={r.persona_id + r.user_id + i}
                        className="flex items-start gap-3 px-4 py-4"
                      >
                        <input
                          type="checkbox"
                          aria-label={`选择身份 ${r.user_id} 人格 ${r.persona_id}`}
                          checked={aliases.includes(r.user_id)}
                          onChange={() => toggle(r.user_id)}
                          disabled={busy}
                          className="mt-1 size-4 accent-primary"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-medium">{r.nickname ?? r.user_id}</span>
                            <Tag
                              tone={
                                identityKind(r.user_id, r.person_key) === "legacy"
                                  ? "warn"
                                  : "muted"
                              }
                            >
                              {IDENTITY_LABEL[identityKind(r.user_id, r.person_key)]}
                            </Tag>
                          </div>
                          <div className="mt-2">
                            <IdentityText value={r.user_id} />
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {name(r.persona_id)} · {r.rows} 行 · Person {r.person_key ?? "未确认"}
                          </p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="p-8 text-center text-sm text-muted-foreground">没有匹配的身份</p>
                  )}
                </div>
              );
            }}
          </QueryView>
        </Panel>
        <div className="space-y-4">
          <Panel title="迁移预览">
            <label className="mb-2 block text-sm font-medium" htmlFor="target-person">
              目标 canonical Person
            </label>
            <input
              id="target-person"
              list="person-options"
              placeholder="填写已确认的 Person ID"
              value={target}
              onChange={(e) => {
                T(e.target.value);
                reset();
              }}
              className={fieldClass + " w-full"}
            />
            <datalist id="person-options">
              {options.map((v) => (
                <option key={v} value={v} />
              ))}
            </datalist>
            <p className="mt-2 text-xs text-muted-foreground">
              归属由 tmemory 或人工确认，不根据名称、数字相同自动判断。
            </p>
            <div className="my-5">
              <KV
                items={[
                  ["已选别名", aliases.length],
                  ["涉及人格", new Set(selected.map((r) => r.persona_id)).size],
                  ["影响行数", affected],
                ]}
              />
            </div>
            {legacy && (
              <p className="mb-4 rounded-lg bg-amber-soft p-3 text-xs text-amber-foreground">
                包含未归属的旧裸 ID，必须人工确认平台与人物归属。操作会影响选中别名涉及的全部人格。
              </p>
            )}
            <Button
              className="w-full"
              variant="outline"
              disabled={
                !aliases.length || !target.trim() || aliases.includes(target.trim()) || busy
              }
              onClick={() => {
                V(true);
                E(false);
                Y("");
              }}
            >
              生成所选预览 <ArrowRight />
            </Button>
            {preview && (
              <div className="mt-4 space-y-3 rounded-lg bg-muted/60 p-3">
                <p className="text-xs text-muted-foreground">仅预览，尚未写入</p>
                <p className="break-all text-sm font-medium">
                  {aliases.join("、")} → {target}
                </p>
                <p className="text-xs">
                  共 {affected} 行，核心将先备份。不能自动验证所填 Person 的真实归属。
                </p>
                <Button
                  className="w-full"
                  disabled={busy}
                  onClick={() => {
                    C("merge");
                    B(1);
                    E(false);
                    Y("");
                  }}
                >
                  确认归属与影响范围
                </Button>
              </div>
            )}
          </Panel>
          {backup && (
            <Panel title="最近备份">
              <code className="block break-all text-xs">{backup}</code>
              <p className="mt-2 text-xs text-muted-foreground">
                需要恢复时，使用上方回滚入口并单独确认。
              </p>
            </Panel>
          )}
        </div>
      </div>
      {plans !== null && (
        <Panel title="权威映射给出的只读计划" className="mt-5">
          {plans.length ? (
            plans.map((p, i) => (
              <div key={i} className="mb-3 break-all rounded-lg border p-3 text-sm">
                <p className="font-medium">{p.person_id}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {p.persona_id} · {p.aliases.join("、")}
                </p>
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">
              当前没有可按权威映射迁移的记录。旧裸 ID 不自动推断。
            </p>
          )}
        </Panel>
      )}
      <Dialog open={!!action} onOpenChange={(v) => !v && !busy && C(null)}>
        <DialogContent>
          <DialogTitle>
            {action === "rollback"
              ? "确认回滚上次合并"
              : step === 1
                ? "确认人物归属与影响范围"
                : "最后确认迁移"}
          </DialogTitle>
          <DialogDescription>
            {action === "rollback"
              ? "核心将恢复上次备份的数据；这会改变关系状态和相关记录。"
              : `目标 ${target}，${aliases.length} 个别名，涉及 ${affected} 行。${connection.status === "demo" ? "当前为演示模式。" : "此操作会修改宿主数据。"}`}
          </DialogDescription>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {action === "rollback" || step === 1 ? (
            <label className="flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={ack}
                onChange={(e) => E(e.target.checked)}
                className="mt-1 size-4"
              />
              {action === "rollback"
                ? "我确认恢复上次备份，并理解当前合并结果将被撤销。"
                : "我已人工确认所有别名属于此人物，并确认跨人格影响与备份机制。"}
            </label>
          ) : (
            <label className="space-y-2 text-sm">
              <span>
                请输入完整目标 Person ID：<b className="break-all">{target}</b>
              </span>
              <input
                aria-label="输入目标 Person ID 进行最终确认"
                value={typed}
                onChange={(e) => Y(e.target.value)}
                className={fieldClass + " w-full"}
              />
            </label>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" disabled={busy} onClick={() => C(null)}>
              取消
            </Button>
            {action === "rollback" ? (
              <Button disabled={!ack || busy} onClick={execute}>
                {busy ? "回滚中…" : "确认回滚"}
              </Button>
            ) : step === 1 ? (
              <Button disabled={!ack || busy} onClick={() => B(2)}>
                下一步
              </Button>
            ) : (
              <Button disabled={typed !== target.trim() || busy} onClick={execute}>
                {busy ? "合并中…" : "执行合并"}
              </Button>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
