import type { UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy, Inbox, Lock, RotateCw } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AdapterError } from "@/lib/hearthlight/types";
import { cn } from "@/lib/utils";

export function Flame({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect x="9" y="25" width="14" height="3" rx="1.5" className="fill-primary" />
      <path
        d="M11 25 L12 14 H20 L21 25 Z"
        className="fill-primary/15 stroke-primary"
        strokeWidth="1.4"
      />
      <g className="flame-flicker">
        <path
          d="M16 6 C19 10 20.5 12.5 18.6 16 C17.8 17.6 14.2 17.6 13.4 16 C11.5 12.5 13 10 16 6 Z"
          className="fill-amber"
        />
        <path
          d="M16 11 C17.2 12.8 17.6 14 16.8 15.3 C16.4 15.9 15.6 15.9 15.2 15.3 C14.4 14 14.8 12.8 16 11 Z"
          className="fill-amber-soft"
        />
      </g>
    </svg>
  );
}

export function PageHeader({
  title,
  desc,
  actions,
}: {
  title: string;
  desc?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="font-display text-2xl font-semibold text-foreground sm:text-[28px]">
          {title}
        </h1>
        {desc && <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">{desc}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Panel({
  title,
  icon,
  actions,
  children,
  className,
  bodyClass,
}: {
  title?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={cn("hl-card flex min-w-0 flex-col", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b px-5 py-3.5">
          <h2 className="flex min-w-0 items-center gap-2 text-sm font-semibold text-foreground">
            {icon && <span className="shrink-0 text-sage">{icon}</span>}
            <span className="truncate">{title}</span>
          </h2>
          {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
        </header>
      )}
      <div className={cn("flex-1 p-5", bodyClass)}>{children}</div>
    </section>
  );
}

export function Meter({
  value,
  tone = "sage",
  label,
  className,
}: {
  value: number;
  tone?: "sage" | "amber" | "primary";
  label?: string;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0)) * 100;
  const bar = tone === "amber" ? "bg-amber" : tone === "primary" ? "bg-primary" : "bg-sage";
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      aria-label={label}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-700", bar)}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function ValenceBar({ value }: { value: number }) {
  const v = Math.max(-1, Math.min(1, value || 0));
  const left = v < 0 ? 50 + v * 50 : 50;
  const width = Math.abs(v) * 50;
  return (
    <div
      className="relative h-1.5 w-24 rounded-full bg-muted"
      role="meter"
      aria-valuemin={-1}
      aria-valuemax={1}
      aria-valuenow={v}
      aria-label="情绪效价"
    >
      <div className="absolute top-0 h-full w-px bg-border" style={{ left: "50%" }} />
      <div
        className={cn("absolute top-0 h-full rounded-full", v >= 0 ? "bg-sage" : "bg-amber")}
        style={{ left: `${left}%`, width: `${width}%` }}
      />
    </div>
  );
}

const toneCls = {
  ok: "bg-sage-soft text-success border-transparent",
  warn: "bg-amber-soft text-amber-foreground border-transparent",
  muted: "bg-muted text-muted-foreground border-border",
  bad: "bg-destructive/10 text-destructive border-transparent",
  outline: "bg-transparent text-foreground border-border",
};
export function Tag({
  tone = "muted",
  children,
  className,
}: {
  tone?: keyof typeof toneCls;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        toneCls[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function DemoTag({ children = "演示数据" }: { children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber/40 bg-amber-soft px-2.5 py-0.5 text-xs font-medium text-amber-foreground">
      <span className="size-1.5 rounded-full bg-amber" aria-hidden />
      {children}
    </span>
  );
}

export function CopyButton({ value, label = "复制" }: { value: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-7"
      aria-label={`${label} ${value}`}
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          toast.success("已复制", { description: value });
          setTimeout(() => setDone(false), 1500);
        } catch {
          toast.error("复制失败，请手动选择文本");
        }
      }}
    >
      {done ? <Check className="text-success" /> : <Copy />}
    </Button>
  );
}

export function EmptyState({
  title = "暂无数据",
  desc,
  action,
}: {
  title?: string;
  desc?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <Inbox className="size-8 text-muted-foreground/60" aria-hidden />
      <p className="text-sm font-medium text-foreground">{title}</p>
      {desc && <p className="max-w-sm text-xs text-muted-foreground">{desc}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const forbidden = error instanceof AdapterError && error.kind === "forbidden";
  if (forbidden)
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center" role="alert">
        <Lock className="size-8 text-amber-foreground" aria-hidden />
        <p className="text-sm font-medium">权限不足</p>
        <p className="max-w-sm text-xs text-muted-foreground">
          {(error as Error).message}。请在宿主中确认当前账号具有管理员权限。
        </p>
      </div>
    );
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center" role="alert">
      <AlertTriangle className="size-8 text-destructive" aria-hidden />
      <p className="text-sm font-medium">这部分数据没有加载成功</p>
      <p className="max-w-sm text-xs text-muted-foreground">
        {error instanceof Error ? error.message : String(error)}
      </p>
      <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
        <RotateCw /> 重试
      </Button>
    </div>
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="加载中">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function QueryView<T>({
  q,
  children,
  skeleton,
  isEmpty,
  empty,
}: {
  q: UseQueryResult<T>;
  children: (d: T) => ReactNode;
  skeleton?: ReactNode;
  isEmpty?: (d: T) => boolean;
  empty?: ReactNode;
}) {
  if (q.isPending) return <>{skeleton ?? <SkeletonRows />}</>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (isEmpty?.(q.data)) return <>{empty ?? <EmptyState />}</>;
  return <>{children(q.data)}</>;
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="min-w-0 break-all text-foreground">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function rawValue(v: unknown): ReactNode {
  if (v === undefined || v === null || v === "")
    return <span className="text-muted-foreground">—</span>;
  if (typeof v === "number") return Number.isInteger(v) ? v : v.toFixed(2);
  if (typeof v === "object") return <code className="text-xs">{JSON.stringify(v)}</code>;
  return String(v);
}
