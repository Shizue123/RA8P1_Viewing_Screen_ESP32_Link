# 阈值执行基线

## 目标

把当前工程的第一条真实执行链固定成可重复验收的基线：

```text
Cloud threshold_control
-> MQTT
-> ESP32 提取规则
-> RA8P1 本地阈值判断
-> 板端动作反馈
-> execution_state / status / deploy_ack 回云端
```

## 当前成立的事实

截至 `2026-05-31`，以下链路已经在真实硬件上成立：

- `deploy_ack` 可回传
- `threshold_control` 可触发板端本地执行路径
- `threshold_control -> SG90 servo_set` 已形成真实执行器闭环
- `script_state` 可进入 `TRIGGERED`
- `execution_state` 可包含真实温度值
- `execution_state` 已开始携带 `reason / operator / threshold / action / angle / sample` 等执行证据字段
- `status` 视图可承载最近一次 `last_execution` 摘要，避免只靠事件流回看

真实复测请求示例：

- `req_threshold_plan_a_1779781005`
- `req_threshold_retest_1779781201`

## 本地构建

### RA8P1

可烧录产物：

- [RA8P1_Viewing_Screen_ESP32_Link.srec](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/Debug/RA8P1_Viewing_Screen_ESP32_Link.srec)
- [RA8P1_Viewing_Screen_ESP32_Link.elf](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/Debug/RA8P1_Viewing_Screen_ESP32_Link.elf)

### ESP32

在当前工作区运行：

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
.\tools\build_esp32_bridge.ps1
```

输出目录：

- [esp32 build](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/esp32-s3-uart-link-arduino/esp32_s3_uart_link/build/esp32.esp32.esp32s3)

## 真实验收

运行：

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
python .\tools\validate_threshold_loop.py --json
```

注意：

- 当前 `request_id` 需要保持在 RA8P1/ESP32 UART 协议上限内，建议不超过 `63` 个字符
- 默认脚本会自动生成短 ID，避免 `deploy_ack` 因 ID 截断而无法匹配

## 通过标准

至少同时满足以下条件：

1. `deploy_ack_received = true`
2. `graph_trace` 包含 `publish_mqtt -> wait_for_ack -> record_ack`
3. `device_last_request_id` 等于本次请求 ID
4. `device_script_state = TRIGGERED`
5. `last_event.type = execution_state`
6. `last_event.payload.state = TRIGGERED`
7. `last_event.payload.temp > 0`
8. `device_temp` 与 `event.temp` 在同一时段合理接近
9. `last_status.payload.last_execution.state = TRIGGERED`
10. `last_status.payload.last_execution.action = SG90`

## 这阶段还不代表什么

当前成立的是“第一条真实执行基线”，不代表：

- 已完成蜂鸣器真实闭环
- 已完成 RGB LED 真实闭环
- RA8P1 已成为完整受限 Lua 解释执行端
- 已定型可复用的完整板端执行模型

## 下一步建议

在这条基线稳定后，当前优先继续做：

1. 文档、manifest、主仓代码映射对齐
2. 板端 `intent -> action` 状态机、事件字段和验证口径定型
3. 等模型定型后，再评估是否恢复 `BUZZER / RGB LED` 等新增外设闭环
