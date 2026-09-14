# xianyusj-phonecontrol

这是一个面向闲鱼管理的 Codex skill 编排层：结构化任务优先走 XianYuApis，需要屏幕事实或 UI 写入时才走 phonecontrol，混合任务采用 API + 手机核验。

## 安装

将整个 `xianyusj-phonecontrol` 文件夹解压到：

```text
C:\Users\<用户名>\.codex\skills\xianyusj-phonecontrol
```

或当前环境的 `$CODEX_HOME/skills/xianyusj-phonecontrol`。

## 运行要求

- 接收方按需配置 XianYuApis 和可用的 phonecontrol MCP 工具；Skill 不捆绑 Android APK、逆向 JS、Cookie 或个人运行日志。
- 分流器只使用 Python 标准库；XianYuApis 运行时依赖其自身的 `requirements.txt`。
- 首次运行会在当前工作区自动创建 `.xianyusj/phonecontrol_memory.md` 和 `.xianyusj/task_execution_log.csv`；memory 使用包内脱敏基础经验种子，CSV 只写入表头。
- 图片中转功能使用 `scripts/xianyu_asset_gallery.py`；不需要电脑图片传输时可以不使用它。

## 分流计划

只生成计划（默认不会访问外部服务）：

```bash
python scripts/xianyu_dispatch.py --task-json '{"operation":"get_item_info","item_id":"123"}'
```

执行需要外部写入的任务时，必须显式增加 `--execute --confirm-write`。适配器环境变量和四个项目的边界见 [references/integration_contract.md](references/integration_contract.md)。

常见路由：

- `get_item_info`、`refresh_token`、`upload_media`、`publish_listing`：优先 XianYuApis，不启动手机控制。
- `screen_state`、`find_node`、`tap`、`type_text`：走 phonecontrol。
- `publish_listing` 加 `requires_visual_confirmation: true`：先调用 API，再用 `phone_stage` 做屏幕核验。
- `group_broadcast_touch`：走定制 Android MCP 的群控工具；工具内部先尝试 STUN/P2P，失败后回退 HTTP/内网穿透。

混合任务示例（默认仍只生成计划）：

```json
{
  "operation": "publish_listing",
  "title": "二手相机",
  "images": ["/safe/path/camera.jpg"],
  "price": 1200,
  "requires_visual_confirmation": true,
  "phone_stage": {
    "tool": "android_get_screen_state",
    "arguments": {"include_screenshot": true}
  }
}
```

真正执行混合任务时，API 阶段和手机核验阶段会按顺序执行，并且仍要求 `--confirm-write`。

不要把个人账号、密码、Cookie、验证码、历史执行日志或完整个人数据放入技能包。
