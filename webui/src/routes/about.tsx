import { createFileRoute } from "@tanstack/react-router";
import { Activity, Brain, Send, ShieldCheck } from "lucide-react";
import { PageHeader, Panel, Tag } from "@/components/hl/primitives";
import { Button } from "@/components/ui/button";
import { useHL } from "@/lib/hearthlight/context";
import type { DemoScenario } from "@/lib/hearthlight/demo";
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
        desc="三个插件各司其职，陪伴保持连贯。新版界面采用本地演示，不接触生产数据。"
      />
      <div className="mb-6 grid gap-4 md:grid-cols-3">
        {[
          {
            name: "Hearthlight · 守灯",
            version: "v1.10.2",
            role: "关系、生活、情绪与成长状态核心",
            Icon: Activity,
          },
          { name: "tmemory", version: "v0.17.0", role: "权威人物绑定与长期记忆", Icon: Brain },
          {
            name: "WarmWhisper · 暖语",
            version: "v2.13.3",
            role: "主动联系的调度、生成与平台投递",
            Icon: Send,
          },
        ].map((p) => (
          <Panel
            key={p.name}
            title={p.name}
            icon={<p.Icon className="size-4" />}
            actions={<Tag>{p.version}</Tag>}
          >
            <p className="text-sm text-muted-foreground">{p.role}</p>
          </Panel>
        ))}
      </div>
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
              只有真实 SDK ready() 成功才会进入宿主模式。接口失败不会切换成演示数据。
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
          <li>演示修改仅保存在内存中；整页刷新会重置。</li>
          <li>没有主动发送按钮，守灯不会代替暖语调度或绕过平台权限。</li>
          <li>这是待集成的新界面，本地预览不会改变已部署插件版本。</li>
        </ul>
      </Panel>
    </>
  );
}
