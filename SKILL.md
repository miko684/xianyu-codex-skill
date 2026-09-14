---
name: xianyusj-phonecontrol
description: "作为闲鱼管理智能中心，优先用 XianYuApis 处理结构化任务，必要时分流到 phonecontrol，并维护可复用的手机控制记忆与逐动作计时日志。"
---

# 闲鱼管理智能中心

本技能是四个项目之间的编排层：结构化闲鱼能力优先走 `XianYuApis`，只有需要真实屏幕、无障碍或视觉核验时才调用 phonecontrol。它适用于查询、商品管理、消息处理和需要手机 UI 的闲鱼任务；通用控制规则也覆盖浏览器、相册和其他手机应用的辅助操作。

## 自动分流

任务开始先根据目标和所需证据选择执行后端，不要因为安装了 phonecontrol 就默认使用手机：

- `api`：商品详情、登录态刷新、媒体上传、接口发布等结构化任务，使用 `scripts/xianyu_dispatch.py` 的 XianYuApis 适配器。
- `phonecontrol`：读取当前屏幕、处理验证码/双开实例、选择相册、验证缩略图或确认最终页面，使用 Android MCP 的 `/mcp` 接口。
- `hybrid`：API 负责准备或提交，phonecontrol 负责必须的视觉步骤和成功核验。

先生成计划：

```text
python scripts/xianyu_dispatch.py --task-json '{"operation":"get_item_info","item_id":"..."}'
```

默认只输出计划，不访问闲鱼或手机。执行外部写操作必须显式使用 `--execute --confirm-write`，并继续遵守用户是否明确授权发布/发送的判断。完整边界、环境变量和组件版本见 [references/integration_contract.md](references/integration_contract.md)。

## 首次运行与运行状态

所有运行状态都放在当前工作区的 `.xianyusj/`，不要写入技能安装目录，也不要依赖创建者电脑上的绝对路径。

任务开始时，先执行：

```text
python scripts/ensure_runtime_state.py --runtime-dir .xianyusj
```

如果 Python 不可用，使用当前环境等价的目录创建与文件初始化方法。随后读取：

- `.xianyusj/phonecontrol_memory.md`
- `.xianyusj/task_execution_log.csv`
- 当前任务需要的参考文件；闲鱼任务读取 `references/xianyu_sop.md`，通用控制问题读取 `references/controlimprove.md`

脚本只在文件不存在时创建初始状态：`phonecontrol_memory.md` 会从包内脱敏种子复制，日志只创建表头；已有记忆或日志绝不覆盖。接收方不会继承创建者的个人历史记录。

## phonecontrol 前置条件

- 必须使用当前环境中实际可用的 phonecontrol MCP 工具操作手机界面；工具不可用时，停止并说明，不能假装完成点击、输入或发布。
- 第一次 phonecontrol 调用前，必须已经生成稳定的 `task_id`，并记录任务和第一个动作的开始时间。
- 每个动作都记录开始、结束、耗时、方法、结果、成功信号和重试次数；没有计时数据时明确写 `timing_status=missing`，不伪造耗时。
- 不记录密码、验证码、Bearer Token、Cookie、完整账号信息或其他不必要的个人数据。

## 通用控制规则

读取当前页面状态后再操作。页面跳转、弹窗关闭、应用切换后重新读取节点，不复用旧 `node_id`。优先使用语义节点，其次使用已验证坐标；一次无效动作最多按恢复策略重试一次，连续无效时停止并报告。

每个写操作都必须有页面状态变化作为成功信号；工具返回“点击完成”不等于业务成功。新发现先写入待分类经验，只有在至少两个不同任务或应用中成功复用后，才晋升为公共动作卡。应用包名、业务字段、商品信息和具体坐标留在专用 SOP 中。

## 闲鱼任务入口

手机 UI 路径下，闲鱼任务的图片顺序、普通闲置商品、服务商品、价格输入、发布核验和停止条件全部按 `references/xianyu_sop.md` 执行。API 路径不跳过用户授权、写操作确认和必要的结果核验。

- 用户只要求准备或编辑时，不擅自点击最终发布。
- 只有用户明确要求上架或发布时才提交。
- 发布后必须进入商品详情或看到平台成功提示，才能记录为成功。
- 电脑端图片任务优先使用包内的 `scripts/xianyu_asset_gallery.py`；图片身份无法核验时停止后续发布，不重复下载同一 `asset_id`。

## 外部依赖与可移植性

本技能不捆绑 XianYuApis、phonecontrol MCP 服务器或 Android APK，也不假设特定手机、账号、网络地址或浏览器登录状态。接收方按环境配置 XianYuApis 项目路径、受保护的 Cookie 文件和 phonecontrol MCP 端点；图片中转脚本只处理本地工作区文件，端口和访问地址以运行时输出为准。

不要把旧的 `phonecontrol_memory.md`、`task_execution_log.csv`、日志或历史商品草稿复制进发布包。若需要迁移经验，只提炼并脱敏后放入参考文件。
