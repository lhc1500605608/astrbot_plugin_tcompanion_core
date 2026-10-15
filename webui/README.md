# Hearthlight · 守灯 WebUI

沿用 Lovable 首版设计并在本地补完的可交互新版界面。源码版本 `1.10.3-preview.2`。

## 运行

```sh
npm install --ignore-scripts
npm run dev
```

预览：http://127.0.0.1:8787/ （仅本机绑定）。

```sh
npm run build
npm test
npm run sync:plugin-page
```

构建输出 `dist/` 为静态资源；独立部署需要为前端路由配置 index.html fallback。当前并未嵌入或部署到生产 AstrBot。

## 已完成

- 总览：人格选择、当前生活状态、关系/主动记录摘要、演示标记、刷新。
- 关系：搜索、阶段/人格/平台筛选、排序、分页、详情抽屉、完整身份和复制。
- 生活与情绪、群聊、成长、主动记录：只读视图、筛选、详情与错误/空状态。
- 身份管理：来源选择、跨人格影响行数、只读迁移计划、选择预览、双重确认、独立回滚确认。
- 关于/连接：三插件职责、版本矩阵、正常/空数据/接口失败/权限不足场景。
- 暖象牙/墨绿/琥珀配色、暗色偏好、桌面侧栏、手机导航、低频轮询清理。

## 数据与宿主

无 SDK 时使用明确标注的虚构演示数据。演示合并只修改内存，整页刷新重置。

发现 `window.AstrBotPluginPage` 时需 ready() 成功才进入宿主模式；初始化失败显示错误，用户主动选择后才能进入演示。宿主 API 失败不偷偷回退到演示。

真实宿主适配代码在 `src/lib/hearthlight/host.ts`，支持现有 life-state、relationships、emotion-state、group-state、growth-state、motivation-log、person/keys 和迁移/回滚端点，并检查响应结构；未做真实宿主集成验收。界面中的昵称、部分群活跃度/成长字段是演示可选字段，宿主没有时显示原始 ID/缺省状态，不制造数据。

构建后通过 `sync:plugin-page` 将静态文件复制到插件实际页面目录 `pages/status/`。在本地 AstrBot 中以有权限的管理会话打开 `/api/plugin/page/content/astrbot_plugin_tcompanion_core/status/`；宿主注入的 `window.AstrBotPluginPage` 就绪后，页面会使用真实插件 API。hash 路由让八个子页面和刷新/深链都留在这一静态页面内。独立打开时才会显示演示模式；若检测到 SDK 但 `ready()` 失败，页面会显示连接错误并要求用户主动选择演示模式。

插件版本 v1.10.3 对应此本地集成；生产仍为 Hearthlight v1.10.1、WarmWhisper v2.13.4、tmemory v0.17.0。静态包已集成进插件文件树，但尚未在真实本地 AstrBot 宿主中完成页面验收，也未部署生产。

## 设计来源与验证

Lovable 项目 `9aa8e69e-e35f-47b4-9d74-38112b4cd682`，首稿 commit `e8f81bf09542346c96e1b6cb27ba1a98fdeb3c54`。Lovable 额度耗尽后，用户授权本地接手。移除不需要的云端 SSR/数据库依赖，保留组件、配色和适配架构；原 SSR 入口存放 `provenance/`。

类型检查/生产构建通过；源 UI 的交互验收记录见 LOCAL_VERIFICATION.md。宿主字段映射、hash 路由和 SDK 响应由 Vitest 覆盖；插件页静态构建由 `npm run sync:plugin-page` 生成并纳入版本控制。浏览器中的本地独立预览不等于 AstrBot 宿主验收。
