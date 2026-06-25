# 云端 Agent 编排基线（以当前工程为准）

## 目的

这份文档不是重新定义整个项目，而是把下一阶段云端 Agent 工作和当前真实板端能力对齐。

截至 `2026-05-31`，`D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link` 已经证明：

- `Cloud -> MQTT -> ESP32 -> RA8P1 -> ACK -> Cloud`
- `AHT20 -> RA8P1 -> UART -> ESP32 -> MQTT`
- `Cloud threshold_control -> SG90 servo_set -> execution_state`

所以下一阶段可以启动云端 Agent 编排。  
但编排必须围绕当前真实能力展开，不能假设板端已经是完整 Lua 执行器。

## 当前真实架构

### 板端工作区

当前工作区：

- `D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link`

它是以下内容的真实基准：

- RA8P1 屏幕状态面板
- ESP32 UART bridge
- AHT20 采样与上报
- `deploy_ack` 联调闭环
- `threshold_control` 的首条真实动作闭环

### 云端代码真源

当前云端代码仍以这里为准：

- `D:\Embedded-agent\cloud`

线上运行环境对应：

- `/home/admin/embedded-agent/cloud`

当前已确认的真实云端骨架包括：

- `app/agent_service`
- `app/api`
- `app/mqtt_service`
- `app/device_state`
- `app/log_service`
- `app/template_compiler`
- `app/registry`
- `tests`
- `web`

这意味着：

- 板端真实状态以本工作区为准
- 云端实现真源以 `D:\Embedded-agent\cloud` 为准
- 下一阶段要做的是两边围绕同一条真实闭环收口，而不是复制出第二份长期维护的云端代码

## 当前真实能力边界

### 已成立

- ESP32 已能连接 WiFi 和 MQTT broker
- 云端已能向 `cloudbridge/{device_id}/script` 下发脚本消息
- ESP32 已能解析 `request_id`、`script_id`、`intent_type`、`lua_code`
- ESP32 已能通过 UART 向 RA8P1 转发 `req:`、`script:`、`cmd:`、`intent:`
- RA8P1 已能更新屏幕状态并回 `ack:req=...;script=...;code=0;msg=accepted`
- ESP32 已能把 `deploy_ack` 发布到 `event`
- AHT20 状态已能走 `telemetry/status` 回云端
- RA8P1 已能基于 `threshold_control` 进入本地阈值判断并回传 `execution_state`

### 尚未成立

- RA8P1 本地完整解析和执行 Lua
- 多外设并行调度和运行时沙箱
- 已定型且可扩展的板端 `intent -> action` 执行模型

所以当前项目不能被描述成：

- 完整板端脚本运行时
- 已完成即插即用外设平台

更准确的描述是：

- 云端编排基线已通
- 板端显示/ACK/传感上报基线已通
- 第一条真实板端动作执行闭环已通
- 下一阶段是收口执行模型，而不是立刻增加更多外设

## 云端 Agent 下一阶段目标

当前最合理的目标不是扩功能面，而是把部署链路做成稳定编排：

```text
resolve_device
-> load_runtime_knowledge
-> validate_intent
-> compile_template_or_lua
-> validate_payload
-> publish_mqtt
-> wait_for_ack
-> record_trace
```

最小要求：

- 每次下发都保留 `request_id`
- 每次下发都能关联 `script_id`
- 结果里能看到 ACK、失败原因和状态轨迹
- 不能绕过 manifest / Lua API / MQTT payload 校验

## 板端对云端的约束

云端编排必须尊重当前板端现实，不要超前假设：

1. 当前 RA8P1 更像状态终端，不是通用脚本解释器。
2. 云端下发的 `lua_code` 目前主要由 ESP32 提取文本或摘要，再映射成屏幕展示和 ACK。
3. 真正的执行动作如果要落到板端，必须先在 RA8P1 增加明确的动作入口，而不是默认“脚本已经能执行”。

## 推荐的阶段顺序

### 阶段 1：围绕现有 SG90 基线做云端编排收口

- 固定一次部署的状态图
- 补齐 `request_id / script_id / graph_trace`
- 让 `deploy_ack` 进入统一日志和设备状态视图
- 对齐本地云端代码和线上兼容层差异
- 让 `execution_state`、`deploy_ack` 和设备状态视图形成统一证据链

### 阶段 2：板端执行模型和主仓映射收口

建议优先顺序：

1. 固定 `threshold_control` 的板端状态机和动作落点。
2. 固定 `execution_state` 的字段、状态码和验证口径。
3. 把真实工作区代码、主仓 `firmware/` 映射层和文档资源保持一致。

这样可以先证明：

```text
Cloud rule
-> MQTT
-> ESP32 bridge
-> RA8P1 constrained action
-> ACK / execution_state / state view
```

### 阶段 3：再评估是否扩展动作面或新增硬件

等第一个动作闭环成立后，再决定是否继续推进：

- 扩展到 `BUZZER / RGB LED / HC-SR04P`
- 受限 `intent -> action` 映射的进一步泛化
- 轻量脚本解释或更完整的板端运行时

## 当前不建议做的事

- 在当前工作区复制一份长期维护的云端代码副本
- 在角色边界未定前大改 UART / MQTT 协议
- 在没有模型定型前宣传“本地 Lua 已可执行”
- 在当前阶段同时引入多个新外设

## 结论

下一阶段可以正式开始云端 Agent 编排。  
但这件事的前提不是“再做一套新架构”，而是：

- 以本工作区作为真实板端基线
- 以 `D:\Embedded-agent\cloud` 作为真实云端代码基线
- 先把当前已打通的链路编排成可追踪、可验证、可回放的部署系统
