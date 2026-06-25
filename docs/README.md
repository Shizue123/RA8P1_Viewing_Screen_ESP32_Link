# 文档索引

## 当前基线

- `competition_solution_baseline_2026.md`：竞赛定位、真实能力、系统边界和演示场景。
- `board_cloud_frontend_mapping_20260621.md`：板端、ESP32、云端和网页字段映射。
- `动态端口显示与统一状态链路测试文档_2026-06-19.md`：屏幕到网页的统一状态验收。
- `PCA9548A_AHT20_BH1750联调测试与验收标准_2026-06-19.md`：多传感器接线和验收。
- `环境异常检测模型_快速采样与训练方案_2026-06-21.md`：后续边缘异常检测的数据方案。
- `统一状态载荷示例_2026-06-16.md`：`ports` 与 `samples` 数据契约。
- `即插即用模块识别与激活规则_V1.md`：模块识别、能力注册和激活规则。

## 控制与云端闭环

- `rule_program_execution_baseline.md`：受限动作序列真实执行基线。
- `threshold_execution_baseline.md`：阈值控制链路。
- `final_control_panel_delivery_baseline.md`：板端控制面板与交付口径。
- `esp32_uart_link_next_steps.md`：UART、MQTT 和 ACK 协议说明。
- `cloud_agent_orchestration_baseline.md`：云端 Agent 与板端安全边界。
- `sg90_hermes_automation_baseline_20260622.md`：Web/QQBot 舵机控制、多传感器联动和长短期任务基线。

## 硬件与故障复盘

- `hardware_wiring_summary_2026-06-04.md`
- `FT6336_LVGL_输入页命中恢复复盘_2026-06-02.md`
- `ra8p1_lvgl_screen_bringup_summary.md`
- `lvgl_black_screen_failure_summary.md`
- `ra8p1_esp32_link_failure_root_cause_summary.md`
- `chinese_font_generation_and_usage.md`

## 维护规则

- 当前事实以源码、可烧录产物和 `agent_feedback_ledger.md` 为准。
- 阶段计划完成后不继续留在主索引；可从 Git 检查点恢复历史版本。
- 不把浏览器会话、日志、临时烧录脚本、第三方完整仓库或重复源码快照放入工程。
