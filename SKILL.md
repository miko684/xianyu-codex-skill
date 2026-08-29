---
name: xianyusj-phonecontrol
description: "通过 phonecontrol 安全执行闲鱼商品创建、编辑和发布，并在项目本地维护可复用的手机控制记忆与逐动作计时日志。"
---

# 闲鱼 Phonecontrol 综合技能

本技能把闲鱼专用流程和通用 phonecontrol 控制规范合并为一个可移植入口。它适用于用户明确要求在闲鱼创建、编辑、完善或发布商品的任务；其中通用控制规则也覆盖浏览器、相册和其他手机应用的辅助操作。

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

闲鱼任务的图片顺序、普通闲置商品、服务商品、价格输入、发布核验和停止条件全部按 `references/xianyu_sop.md` 执行。

- 用户只要求准备或编辑时，不擅自点击最终发布。
- 只有用户明确要求上架或发布时才提交。
- 发布后必须进入商品详情或看到平台成功提示，才能记录为成功。
- 电脑端图片任务优先使用包内的 `scripts/xianyu_asset_gallery.py`；图片身份无法核验时停止后续发布，不重复下载同一 `asset_id`。

## 外部依赖与可移植性

本技能不捆绑 phonecontrol MCP 服务器，也不假设特定手机、账号、网络地址或浏览器登录状态。接收方需要自行配置可用的 phonecontrol 工具；图片中转脚本只处理本地工作区文件，端口和访问地址以运行时输出为准。

不要把旧的 `phonecontrol_memory.md`、`task_execution_log.csv`、日志或历史商品草稿复制进发布包。若需要迁移经验，只提炼并脱敏后放入参考文件。
