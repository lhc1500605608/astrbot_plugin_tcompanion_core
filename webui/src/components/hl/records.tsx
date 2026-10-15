import { useState, type ReactNode } from "react";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { CopyButton, EmptyState, KV, rawValue } from "./primitives";
export const fieldClass =
  "h-10 min-w-0 rounded-lg border bg-card px-3 text-sm outline-none focus:ring-2 focus:ring-ring";
export function SearchField({
  value,
  onChange,
  placeholder = "搜索人物、身份或人格",
}: {
  value: string;
  onChange: (s: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="relative min-w-[180px] flex-1">
      <Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={fieldClass + " w-full pl-9"}
      />
    </label>
  );
}
export function Filter({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (s: string) => void;
  options: [string, string][];
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={fieldClass}
    >
      <option value="all">全部{label}</option>
      {options.map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </select>
  );
}
export function Details({
  title,
  subtitle,
  open,
  onClose,
  children,
}: {
  title: string;
  subtitle?: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent className="w-full overflow-y-auto p-6 sm:max-w-lg">
        <SheetTitle className="font-display text-xl">{title}</SheetTitle>
        <SheetDescription>{subtitle ?? "只读详情 · 保留原始身份与来源"}</SheetDescription>
        <div className="mt-6 space-y-6">{children}</div>
      </SheetContent>
    </Sheet>
  );
}
export function RawDetails({ record }: { record: Record<string, unknown> }) {
  return <KV items={Object.entries(record).map(([k, v]) => [k, rawValue(v)])} />;
}
export function IdentityText({ value }: { value: string }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1">
      <code className="break-all text-xs">{value}</code>
      <CopyButton value={value} />
    </span>
  );
}
export function PagedTable<T>({
  rows,
  columns,
  rowKey,
  onRow,
}: {
  rows: T[];
  columns: { label: string; cell: (r: T) => ReactNode }[];
  rowKey: (r: T) => string;
  onRow?: (r: T) => void;
}) {
  const [page, setPage] = useState(1);
  const pages = Math.max(1, Math.ceil(rows.length / 6));
  const current = Math.min(page, pages);
  if (!rows.length)
    return <EmptyState title="没有符合条件的结果" desc="试试其他关键词，或清空筛选。" />;
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              {columns.map((c) => (
                <th key={c.label} className="whitespace-nowrap px-4 py-3 font-medium">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice((current - 1) * 6, current * 6).map((r) => (
              <tr key={rowKey(r)} className="border-b last:border-0 hover:bg-muted/40">
                {columns.map((c, i) => (
                  <td key={c.label} className="px-4 py-4">
                    {i === 0 && onRow ? (
                      <button
                        className="text-left font-medium underline-offset-4 hover:underline"
                        onClick={() => onRow(r)}
                      >
                        {c.cell(r)}
                      </button>
                    ) : (
                      c.cell(r)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between gap-3 border-t px-4 py-3 text-xs text-muted-foreground">
        <span>
          共 {rows.length} 条 · {current} / {pages} 页
        </span>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={current === 1}
            onClick={() => setPage(current - 1)}
          >
            上一页
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={current === pages}
            onClick={() => setPage(current + 1)}
          >
            下一页
          </Button>
        </div>
      </div>
    </>
  );
}
