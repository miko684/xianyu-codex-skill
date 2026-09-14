# 闲鱼智能中心整合契约

## 四个项目的边界

| 组件 | 职责 | 智能中心如何调用 |
|---|---|---|
| `miko684/xianyu-codex-skill` | Agent 入口、任务分类、SOP、记忆和审计 | 读取 `SKILL.md`，运行 `scripts/xianyu_dispatch.py` |
| `cv-cat/XianYuApis` | 闲鱼 HTTP API、登录态刷新、商品接口、WebSocket 消息底座 | 通过 `XIANYU_APIS_ROOT` 动态加载 `goofish_apis.py` |
| `miko684/codex-control-android-mcp` | Android UI、截图、无障碍、文件和应用操作 | 通过 `POST /mcp` 的 JSON-RPC `tools/call` 调用 |
| `miko684/android-remote-control-mcp-custom` | Android MCP 的 P2P 快速触控和 HTTP 回退 | 作为 phonecontrol 端点提供 `android_batch_touch`/群控能力 |

项目不把 Android 源码、闲鱼逆向 JS 或个人 Cookie 复制进 Skill。这样既减少重复维护，也避免把账号凭据和运行时状态带进发布包。

## 分流原则

1. 结构化、可由接口直接完成的任务优先走 `XianYuApis`：商品详情、登录态刷新、媒体上传、发布接口准备/提交。
2. 必须观察屏幕、处理登录/验证码、选择双开实例、确认缩略图或验证发布结果时走 phonecontrol。
3. 一个任务同时需要接口和视觉确认时走 hybrid：接口负责准备或提交，手机负责必要的视觉步骤和结果确认。
4. API 与手机控制都不可用时停止并报告，不伪造已执行。

## 凭据与写操作

- `XIANYU_COOKIES_FILE` 只指向本机权限可控的 JSON Cookie 文件，不进入任务 JSON、日志或输出。
- `PHONECONTROL_MCP_TOKEN` 只在请求头中使用，不打印、不写入 `.xianyusj/`。
- `publish_listing`、`upload_media` 和手机写操作必须显式传 `--execute --confirm-write`。
- 默认只生成路由计划，不访问闲鱼、不调用手机、不发送消息。

## 当前不做的事

- 不把 XianYuApis 的逆向签名算法复制到 Kotlin。
- 不把 phonecontrol 的 MCP 工具伪装成闲鱼 API。
- 不把 P2P 当作通用 MCP 传输；P2P 失败仍走目标 URL 的 HTTP/内网穿透。
- WebSocket 长连接客服需要独立的消息 worker；当前分流核心先覆盖可验证的 HTTP API 和 Android MCP 工具。

## 版本基线

整合设计基于以下已核对版本：

- `xianyu-codex-skill`: `07c7d88`
- `XianYuApis`: `c6c87e6`
- `codex-control-android-mcp`: `0805b17`
- `android-remote-control-mcp-custom`: `f2c7fd9`
