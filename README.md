# xianyusj-phonecontrol

这是一个将闲鱼专用 SOP 与通用 phonecontrol 控制规则合并的 Codex skill。

## 安装

将整个 `xianyusj-phonecontrol` 文件夹解压到：

```text
C:\Users\<用户名>\.codex\skills\xianyusj-phonecontrol
```

或当前环境的 `$CODEX_HOME/skills/xianyusj-phonecontrol`。

## 运行要求

- 接收方需要自行配置可用的 phonecontrol MCP 工具。
- 首次运行会在当前工作区自动创建 `.xianyusj/phonecontrol_memory.md` 和 `.xianyusj/task_execution_log.csv`；memory 使用包内脱敏基础经验种子，CSV 只写入表头。
- 图片中转功能使用 `scripts/xianyu_asset_gallery.py`；不需要电脑图片传输时可以不使用它。

不要把个人账号、密码、Cookie、验证码、历史执行日志或完整个人数据放入技能包。
