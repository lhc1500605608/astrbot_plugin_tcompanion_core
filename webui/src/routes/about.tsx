import { createFileRoute } from "@tanstack/react-router";
import { Activity, Brain, Send, ShieldCheck } from "lucide-react";
import { PageHeader, Panel, Tag } from "@/components/hl/primitives";
import { Button } from "@/components/ui/button";
import { useHL } from "@/lib/hearthlight/context";
import type { DemoScenario } from "@/lib/hearthlight/demo";

type ConnectionStatus = "host" | "error" | "detecting" | "demo";

export const RELEASE_MATRIX = [
  { name: "Hearthlight · 守灯", version: "v1.10.3", role: "关系、生活、情绪与成长状态核心" },
  { name: "tmemory", version: "v0.17.0", role: "权威人物绑定与长期记忆" },
  { name: "WarmWhisper · 暖语", version: "v2.13.5", role: "主动联系的调度、生成与平台投递" },
] as const;

export function aboutDescription(status: ConnectionStatus): string {
  if (status === "host")
    return "已连接 AstrBot 宿主并读取守灯插件数据；陪伴功能由三个插件协同提供。";
  if (status === "demo") return "当前使用本地虚构演示数据，不连接插件服务或生产数据。";
  if (status === "error") return "宿主初始化失败，当前没有载入演示数据；可主动切换到本地演示模式。";
  return "正在检测 AstrBot 插件页面 SDK，连接状态确认后显示对应数据来源。";
}

export function pageScopeNotice(status: ConnectionStatus): string {
  if (status === "host")
    return "当前页面连接到守灯插件；WarmWhisper 与 tmemory 的版本是兼容参考，页面不会实时查询它们的运行版本。";
  if (status === "demo") return "当前为本地演示模式，示例数据与演示修改仅保存在内存中。";
  if (status === "error") return "宿主连接失败，演示数据尚未载入；切换演示模式前不会显示虚构内容。";
  return "连接检测期间暂不显示插件数据。";
}

export const Route = createFileRoute("/about")({ component: About });
function About() {
  const { connection, scenario, setScenario, refresh, enterDemo } = useHL();
  const demos: [DemoScenario, string, string][] = [
    ["normal", "正常数据", "人物、生活、情绪与回执完整展示"],
    ["empty", "无数据", "检查初次安装和空状态"],
    ["error", "接口失败", "仅部分接口失败，其余内容保持可用"],
    ["forbidden", "权限不足", "身份接口拒绝访问，操作不显示假成功"],
  ];
  return (
    <>
      <PageHeader
        title="关于与连接"
        desc={aboutDescription(connection.status)}
      />
      <div className="mb-6 grid gap-4 md:grid-cols-3">
        {RELEASE_MATRIX.map((p) => (
          <Panel
            key={p.name}
            title={p.name}
            icon={
              p.name === "Hearthlight · 守灯" ? (
                <Activity className="size-4" />
              ) : p.name === "tmemory" ? (
                <Brain className="size-4" />
              ) : (
                <Send className="size-4" />
              )
            }
            actions={<Tag>{p.version}</Tag>}
          >
            <p className="text-sm text-muted-foreground">{p.role}</p>
          </Panel>
        ))}
      </div>
      <p className="-mt-3 mb-6 text-xs text-muted-foreground">
        当前发布版本参考；WarmWhisper 与 tmemory 版本表示兼容矩阵，不由此页面实时查询。
      </p>
      <Panel title="当前连接" className="mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="font-medium">
              {connection.status === "host"
                ? "AstrBot 宿主模式"
                : connection.status === "error"
                  ? "宿主初始化失败"
                  : connection.status === "detecting"
                    ? "正在检测 SDK"
                    : "演示模式 · 虚构数据"}
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              {connection.status === "host"
                ? "宿主 SDK 已就绪。后续接口错误会如实显示，不会自动切换到演示数据。"
                : "只有真实 SDK ready() 成功才会进入宿主模式。接口失败不会切换成演示数据。"}
            </p>
          </div>
          <Button variant="outline" onClick={refresh}>
            刷新当前数据
          </Button>
        </div>
        {connection.status === "error" && (
          <Button className="mt-4" onClick={enterDemo}>
            主动选择演示模式
          </Button>
        )}
      </Panel>
      <Panel title="演示场景" className="mb-6">
        <p className="mb-4 text-sm text-muted-foreground">
          场景切换仅对演示模式有效，不会改变服务器配置或真实人物数据。
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {demos.map(([v, title, desc]) => (
            <button
              key={v}
              disabled={connection.status !== "demo"}
              aria-pressed={scenario === v}
              onClick={() => setScenario(v)}
              className={`rounded-xl border p-4 text-left transition hover:bg-muted disabled:opacity-50 ${scenario === v ? "border-primary bg-sage-soft" : "bg-card"}`}
            >
              <p className="text-sm font-medium">{title}</p>
              <p className="mt-2 text-xs text-muted-foreground">{desc}</p>
            </button>
          ))}
        </div>
      </Panel>
      <Panel title="数据与操作边界" icon={<ShieldCheck className="size-4" />}>
        <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>关系、生活、情绪、群聊、成长与主动记录只读。</li>
          <li>身份合并需要预览和双重确认；裸 ID 不自动判断归属，回滚单独确认。</li>
          <li>{pageScopeNotice(connection.status)}</li>
          <li>没有主动发送按钮，守灯不会代替暖语调度或绕过平台权限。</li>
        </ul>
      </Panel>
    </>
  );
}
