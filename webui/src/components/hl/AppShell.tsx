import { Link, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  Fingerprint,
  HeartHandshake,
  Info,
  LayoutDashboard,
  Menu,
  Moon,
  Send,
  Sprout,
  Sun,
  Users,
  RotateCw,
  ExternalLink,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { useHL, useHLFetching } from "@/lib/hearthlight/context";
import { fmtTime } from "@/lib/hearthlight/labels";
import { cn } from "@/lib/utils";
import { DemoTag, Flame } from "./primitives";

const NAV = [
  { to: "/", label: "总览", icon: LayoutDashboard },
  { to: "/relationships", label: "关系", icon: HeartHandshake },
  { to: "/life", label: "生活与情绪", icon: Activity },
  { to: "/groups", label: "群聊", icon: Users },
  { to: "/growth", label: "成长", icon: Sprout },
  { to: "/motivation", label: "主动记录", icon: Send },
  { to: "/identity", label: "身份管理", icon: Fingerprint },
  { to: "/about", label: "关于与连接", icon: Info },
] as const;

function NavList({ onNavigate }: { onNavigate?: (() => void) | undefined }) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  return (
    <nav aria-label="主导航" className="flex flex-col gap-0.5">
      {NAV.map((n) => {
        const active = n.to === "/" ? path === "/" : path.startsWith(n.to);
        return (
          <Link
            key={n.to}
            to={n.to}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
              active
                ? "bg-sidebar-accent font-medium text-foreground"
                : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
            )}
          >
            <n.icon className={cn("size-4 shrink-0", active ? "text-primary" : "text-sage")} />
            {n.label}
            {active && <span className="ml-auto size-1.5 rounded-full bg-amber" aria-hidden />}
          </Link>
        );
      })}
    </nav>
  );
}

function SidebarBody({ onNavigate }: { onNavigate?: (() => void) | undefined }) {
  return (
    <div className="flex h-full flex-col">
      <Link to="/" onClick={onNavigate} className="flex items-center gap-2.5 px-4 pt-5 pb-6">
        <Flame className="size-8" />
        <div className="leading-tight">
          <div className="font-display text-base font-semibold text-foreground">Hearthlight</div>
          <div className="text-xs text-muted-foreground">守灯 · 陪伴状态</div>
        </div>
      </Link>
      <div className="flex-1 overflow-y-auto px-3">
        <NavList onNavigate={onNavigate} />
      </div>
      <div className="space-y-3 border-t border-sidebar-border px-4 py-4 text-xs">
        <div className="flex items-center justify-between text-muted-foreground">
          <span>仓库 v1.10.2</span>
          <span className="rounded bg-amber-soft px-1.5 py-0.5 text-amber-foreground">
            新版界面预览
          </span>
        </div>
        <div className="space-y-1">
          <div className="text-muted-foreground">生态</div>
          <Link
            to="/about"
            onClick={onNavigate}
            className="flex items-center gap-1.5 text-foreground hover:text-primary"
          >
            WarmWhisper · tmemory <ExternalLink className="size-3" />
          </Link>
        </div>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const {
    connection,
    theme,
    toggleTheme,
    refresh,
    lastUpdated,
    autoRefresh,
    setAutoRefresh,
    enterDemo,
  } = useHL();
  const fetching = useHLFetching();
  const [now, setNow] = useState<string>("");
  useEffect(() => {
    setNow(
      new Date().toLocaleDateString("zh-CN", {
        year: "numeric",
        month: "long",
        day: "numeric",
        weekday: "long",
      }),
    );
  }, []);

  return (
    <div className="min-h-screen bg-background">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-card focus:px-3 focus:py-2"
      >
        跳到主要内容
      </a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[220px] border-r border-sidebar-border bg-sidebar lg:block">
        <SidebarBody />
      </aside>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-[260px] bg-sidebar p-0">
          <SheetTitle className="sr-only">导航</SheetTitle>
          <SidebarBody onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="lg:pl-[220px]">
        <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-2 px-4 sm:px-6 lg:px-8">
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              onClick={() => setOpen(true)}
              aria-label="打开导航"
            >
              <Menu />
            </Button>
            <div className="flex min-w-0 items-center gap-2">
              <span className="hidden truncate text-sm text-muted-foreground sm:inline">{now}</span>
              {connection.status === "host" ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-sage-soft px-2.5 py-0.5 text-xs font-medium text-success">
                  <span className="size-1.5 rounded-full bg-success" /> 宿主模式
                </span>
              ) : connection.status === "demo" ? (
                <DemoTag>演示模式</DemoTag>
              ) : connection.status === "error" ? (
                <span role="alert" className="text-xs text-destructive">
                  宿主连接失败
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">正在检测宿主…</span>
              )}
            </div>
            <div className="ml-auto flex items-center gap-1 sm:gap-2">
              <span className="hidden text-xs text-muted-foreground md:inline">
                更新于 {lastUpdated ? fmtTime(lastUpdated) : "—"}
              </span>
              <label className="hidden items-center gap-1.5 text-xs text-muted-foreground md:flex">
                <Switch
                  checked={autoRefresh}
                  onCheckedChange={setAutoRefresh}
                  aria-label="每 60 秒自动刷新"
                />
                60s 轮询
              </label>
              <Button
                variant="outline"
                size="sm"
                onClick={refresh}
                disabled={!!fetching}
                aria-label="刷新数据"
              >
                <RotateCw className={cn(fetching && "animate-spin")} />
                <span className="hidden sm:inline">刷新</span>
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={toggleTheme}
                aria-label={theme === "dark" ? "切换到浅色模式" : "切换到暗色模式"}
              >
                {theme === "dark" ? <Sun /> : <Moon />}
              </Button>
            </div>
          </div>
        </header>
        {connection.status === "error" && (
          <div className="mx-auto max-w-[1400px] px-4 pt-4 sm:px-6 lg:px-8">
            <div
              className="rounded-lg border border-amber/40 bg-amber-soft px-4 py-2 text-sm text-amber-foreground"
              role="status"
            >
              检测到宿主 SDK，但 ready() 失败（{connection.message}），未加载演示数据。
              <Button variant="outline" className="ml-3" onClick={enterDemo}>
                主动选择演示模式
              </Button>
            </div>
          </div>
        )}
        <main id="main" className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
