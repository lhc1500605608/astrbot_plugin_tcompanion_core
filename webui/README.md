# Hearthlight · 守灯 WebUI

沿用 Lovable 首版设计并在本地补完的可交互新版界面。预览版本 `1.10.2-preview.2`。

## 运行

```sh
npm install --ignore-scripts
npm run dev
```

预览：http://127.0.0.1:8787/ （仅本机绑定）。

```sh
npm run build
npm test
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

本仓库版本为 Hearthlight v1.10.2；生产仍为 Hearthlight v1.10.1、WarmWhisper v2.13.3、tmemory v0.17.0。新版界面位于 webui/，尚未替换 pages/status/，部署到 AstrBot 前须完成真实宿主集成验证。

## 设计来源与验证

Lovable 项目 `9aa8e69e-e35f-47b4-9d74-38112b4cd682`，首稿 commit `e8f81bf09542346c96e1b6cb27ba1a98fdeb3c54`。Lovable 额度耗尽后，用户授权本地接手。移除不需要的云端 SSR/数据库依赖，保留组件、配色和适配架构；原 SSR 入口存放 `provenance/`。

类型检查/生产构建通过；4 个测试文件、9 项测试通过。浏览器已验证搜索隔离、详情、演示迁移双重确认/回滚、错误状态、主题切换和手机导航，见 LOCAL_VERIFICATION.md。验收截图保存在原工作区的 prototypes/hearthlight-lovable/screenshots/，未纳入本目录。
