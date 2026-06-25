<div align="center">

# RA8P1 可插拔环境智控终端

**基于瑞萨 RA8P1 + ESP32-S3 + LVGL 的环境感知 · 本地 HMI · 云端 Agent 协同终端**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCU: RA8P1](https://img.shields.io/badge/MCU-Renesas%20RA8P1-blue)](https://www.renesas.com/)
[![UI: LVGL](https://img.shields.io/badge/UI-LVGL-34d058)](https://lvgl.io/)
[![Bridge: ESP32-S3](https://img.shields.io/badge/Bridge-ESP32--S3-e7352b)](https://www.espressif.com/)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

</div>

---

## 概述

本项目面向温室、实验室机柜、小型设备间等场景，以瑞萨 **RA8P1** 为核心主控，配合 **ESP32-S3** 网络协处理器，实现环境感知、本地人机交互（HMI）、安全动作执行与云端 Agent 协同。

RA8P1 负责核心采集、状态管理、规则判断和动作执行；ESP32-S3 仅作网络协处理器，负责 Wi-Fi、MQTT、NTP 与云端桥接。云端模型（Hermes / DeepSeek）仅生成候选计划，不能绕过板端白名单、参数范围与状态机。

> 系统边界：无新鲜传感器证据时，屏幕、网页和对话端不得伪造当前数值；SG90 为开环执行器，"已配置 / 已执行" 不等于检测到物理舵机在线。

---

## 目录

- [系统能力](#系统能力)
- [硬件组成](#硬件组成)
- [系统架构](#系统架构)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [凭证与配置](#凭证与配置)
- [文档导航](#文档导航)
- [路线图](#路线图)
- [贡献](#贡献)
- [许可证](#许可证)

---

## 系统能力

- **RA8P1 核心主控**：传感器驱动、设备注册表、触摸 HMI、规则判断、执行状态机。
- **显示与触摸**：320 × 480 ILI9488 屏 + FT6336 触摸，已接入 LVGL。
- **I2C 多通道感知**：`I2C-1 / i2c.s1` 经 PCA9548A 同时挂载 AHT20（温湿度，CH0）与 BH1750（光照，CH1）。
- **动态端口显示**：屏幕根据统一设备注册表动态显示已接入模块，不为不存在的模块伪造页面。
- **执行器**：`PWM-0` 驱动 SG90 舵机 0–180° 动作，统一能力模型保留蜂鸣告警能力。
- **网络协处理器**：ESP32-S3 经 115200 bit/s UART 与 RA8P1 通信，负责 Wi-Fi、MQTT、NTP 与云端桥接。
- **云端协同**：自然语言经 Hermes/DeepSeek 转换为受限 `rule_program.v1`，经校验后下发。
- **证据链**：`deploy_ack → execution_state → status/telemetry` 全链路可追溯；结构化动作序列支持 `ARMED → TRIGGERED → DONE`。

## 硬件组成

| 角色 | 型号 | 说明 |
|------|------|------|
| 主控 MCU | Renesas RA8P1 | 核心采集、HMI、状态机 |
| 显示屏 | ILI9488 320×480 | SPI 接口 |
| 触摸 | FT6336 | 电容触摸 |
| I2C 多路 | PCA9548A | 8 通道 I2C 切换 |
| 温湿度 | AHT20 | I2C CH0 |
| 光照 | BH1750 | I2C CH1 |
| 舵机 | SG90 | PWM-0，0–180° |
| 网络协处理器 | ESP32-S3 | Wi-Fi / MQTT / NTP / 云桥接 |

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                        云端 (Cloud)                           │
│   Hermes / DeepSeek  ──►  rule_program.v1  ──►  MQTT 下发      │
│   /api/devices/register   /agent/hermes/chat   /health        │
└────────────────────────────┬─────────────────────────────────┘
                             │ Wi-Fi / MQTT / HTTP
┌────────────────────────────┴─────────────────────────────────┐
│                     ESP32-S3 (网络协处理器)                    │
│        Wi-Fi · MQTT · NTP · UART 115200 bit/s 桥接            │
└────────────────────────────┬─────────────────────────────────┘
                             │ UART
┌────────────────────────────┴─────────────────────────────────┐
│                      RA8P1 (核心主控)                         │
│  ┌──────────┐  ┌───────────┐  ┌─────────┐  ┌──────────────┐  │
│  │ 传感器层  │  │ 设备注册表 │  │ 规则引擎 │  │ 执行状态机    │  │
│  │AHT20/BH1750│ │(动态端口) │  │(白名单)  │  │ARMED→TRIG→DONE│  │
│  └─────┬────┘  └─────┬─────┘  └────┬────┘  └──────┬───────┘  │
│        └────────────┴─────────────┴───────────────┘          │
│  ┌──────────────────────────────────────────────────────┐     │
│  │  HMI: LVGL (ILI9488 + FT6336) · SG90 (PWM-0)         │     │
│  └──────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
        I2C-1 (PCA9548A) ──► CH0: AHT20 · CH1: BH1750
```

## 目录结构

```
RA8P1_Viewing_Screen_ESP32_Link/
├── src/                  # RA8P1 应用、驱动、设备注册与 UI
│   ├── segger_rtt/       # SEGGER RTT 调试输出
│   ├── app_ui.c/.h       # LVGL HMI 实现
│   ├── device_registry.* # 统一设备注册表（动态端口）
│   ├── esp32_link.*      # UART 桥接协议
│   ├── aht20.* bh1750.*  # 传感器驱动
│   ├── sg90_servo.*      # 舵机驱动
│   └── ...
├── esp32-s3-uart-link-arduino/  # ESP32-S3 桥接固件 (Arduino)
│   └── esp32_s3_uart_link/esp32_s3_uart_link.ino
├── cloud/                # 云端服务（FastAPI + Web + MQTT + Agent）
│   ├── app/              # 后端：API 路由、Agent 编排、MQTT、设备状态
│   ├── web/              # 前端：原生 HTML/CSS/JS
│   ├── tests/            # Pytest 测试套件
│   ├── prompts/          # 系统提示词
│   ├── requirements.txt  # Python 依赖
│   └── README.md         # 云端详细文档
├── ra/ ra_gen/ ra_cfg/   # Renesas FSP 配置与生成代码
├── lvgl/                 # LVGL 源码（vendored）
├── docs/                 # 设计基线、接线、验收、故障复盘
├── tools/                # 构建检查、字体生成、联调工具
├── UI/                   # UI 设计稿与字体
├── script/               # 链接脚本
├── Debug/                # e2studio 构建系统（makefile / linker）
├── build_headless.sh     # 无头构建入口
├── configuration.xml     # FSP 配置
└── flash.jlink           # J-Link 烧录脚本
```

## 快速开始

### 依赖

- Renesas e² studio + FSP（RA8P1 工具链）
- Arduino CLI（ESP32-S3 编译）
- Python 3.10+（联调 / 校验工具）
- J-Link（烧录 RA8P1）

### 构建 RA8P1 固件

```bash
bash build_headless.sh
```

构建产物（已在 `.gitignore` 中排除，需本地生成）：

- `Debug/RA8P1_Viewing_Screen_ESP32_Link.elf`
- `Debug/RA8P1_Viewing_Screen_ESP32_Link.srec`

### 烧录 RA8P1

```bash
JLinkExe -device RA8P1 -if SWD -speed 4000 -autoconnect 1 -CommanderScript flash.jlink
```

### 构建 ESP32-S3 桥接固件

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 \
  esp32-s3-uart-link-arduino/esp32_s3_uart_link
arduino-cli upload -p <COM_PORT> --fqbn esp32:esp32:esp32s3 \
  esp32-s3-uart-link-arduino/esp32_s3_uart_link
```

### 运行云端服务（可选）

云端服务提供自然语言 → 规则下发、Web 控制台、设备注册与状态聚合。详见 [`cloud/README.md`](cloud/README.md)。

```bash
cd cloud
cp .env.example .env          # 按需填写 MQTT / DeepSeek / Hermes 凭证
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

默认 `MQTT_ENABLED=false`，接口会生成完整 MQTT 消息但不连接 broker；配置好 broker 后在 `.env` 中启用。

## 凭证与配置

> ⚠️ **本仓库不含任何真实凭证。** 所有 Wi-Fi、MQTT、云端 API Token 与服务器地址均已替换为占位符。

构建与烧录前，请替换以下占位符为你自己的真实值，详见
[`docs/cloud_integration_setup.md`](docs/cloud_integration_setup.md) 与
[`SECURITY.md`](SECURITY.md)：

| 占位符 | 位置 | 说明 |
|--------|------|------|
| `YOUR_WIFI_SSID` / `YOUR_WIFI_PASSWORD` | `esp32_..._link.ino` | 内置 Wi-Fi 凭证 |
| `your-mqtt-broker-host` | `esp32_..._link.ino` | MQTT Broker 主机 |
| `your-mqtt-username` / `your-mqtt-password` | `esp32_..._link.ino` | MQTT 凭证 |
| `your-cloud-host` | `esp32_..._link.ino` · `tools/validate_*.py` | 云端 HTTP 主机 |
| `your-cloud-api-token` | `esp32_..._link.ino` | 云端 API Token |
| `<your-domain>` | `cloud/README.md` | 云端公网域名 |

云端服务自身的配置（MQTT broker、DeepSeek API Key、QQBot、Hermes 网关等）通过
[`cloud/.env.example`](cloud/.env.example) 管理，复制为 `.env` 后填写真实值；
`.env` 与 `cloud/runtime/` 已在 `.gitignore` 中排除，不会被提交。

## 文档导航

- [`docs/README.md`](docs/README.md) — 文档总览
- [`docs/competition_solution_baseline_2026.md`](docs/competition_solution_baseline_2026.md) — 赛题方案基线
- [`docs/hardware_wiring_summary_2026-06-04.md`](docs/hardware_wiring_summary_2026-06-04.md) — 硬件接线
- [`docs/PCA9548A_AHT20_BH1750联调测试与验收标准_2026-06-19.md`](docs/PCA9548A_AHT20_BH1750联调测试与验收标准_2026-06-19.md) — 传感器联调验收
- [`docs/动态端口显示与统一状态链路测试文档_2026-06-19.md`](docs/动态端口显示与统一状态链路测试文档_2026-06-19.md) — 动态端口测试
- [`docs/agent_feedback_ledger.md`](docs/agent_feedback_ledger.md) — Agent 反馈与决策台账
- [`docs/cloud_integration_setup.md`](docs/cloud_integration_setup.md) — 云端集成与凭证配置

## 路线图

- [x] RA8P1 传感器链路（PCA9548A + AHT20 + BH1750）
- [x] LVGL HMI 与动态端口显示
- [x] ESP32-S3 UART 桥接与云端协同
- [x] Hermes/DeepSeek 自然语言 → 受限规则下发
- [x] SG90 舵机调度执行
- [ ] MQTT over TLS（生产硬化）
- [ ] 环境异常检测模型（长短期采样与训练）
- [ ] 设备级凭证隔离（每设备独立 MQTT 凭证）

## 贡献

欢迎提交 Issue 与 Pull Request。请先阅读：

- [贡献指南](CONTRIBUTING.md)
- [行为准则](CODE_OF_CONDUCT.md)
- [安全策略](SECURITY.md)

提交前请确认：**不要在代码或提交中包含真实凭证**，使用占位符并在文档中说明。

## 许可证

本项目自身代码采用 [MIT License](LICENSE) 开源。

仓库中 vendored 的第三方库保留各自许可证：
- LVGL — MIT
- Renesas FSP — BSD-3-Clause / Apache-2.0
- SEGGER RTT — SEGGER RTT License
- ESP32 Arduino Core — LGPL-2.1

---

<div align="center">

Made with ❤️ for embedded + cloud collaboration.

</div>
