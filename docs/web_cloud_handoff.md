# 网页端与云服务器接手资料

> 2026-06-06 更新：本文后半部分保留了旧设备控制台的工程背景，但网页登录和公开页面已经重构。当前权威基线是：
>
> - `Browser -> FastAPI session -> Hermes API Server`
> - 网页不再使用浏览器 API Token
> - 页面只保留 Hermes 对话、服务器资料、SDA/SCL 信号通道和账户管理
> - 当前网页阶段不下发硬件命令
> - 设备控制 API 只作为兼容工程接口保留

## 1. 这份文档解决什么问题

这份文档给后续接手网页开发的人使用，目标不是介绍全部嵌入式细节，而是让对方能快速回答下面几件事：

1. 当前项目的网页端代码到底在哪。
2. 当前云服务器的后端入口、接口、鉴权和数据流是什么。
3. 网页应该接 FastAPI 还是直接接 MQTT。
4. `threshold_control` 和 `rule_program` 两条链路分别到什么成熟度。
5. 有哪些已知坑会让前端把“执行成功”误判成“失败”。

结论先写在前面：

- 网页不要直接连 MQTT，应该走 `Browser -> FastAPI -> MQTT -> ESP32 -> RA8P1`。
- 当前“实际在跑的云端网页”代码真源在 `D:\Embedded-agent\cloud\web`。
- 当前仓库里的 `UI/RA8P1_UI.html` 是高保真静态原型，不是线上控制台代码。
- 当前板端/ESP32/协议行为真源在本仓库 `D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link`。
- 当前云端服务代码真源在 `D:\Embedded-agent\cloud`，线上对应目录是 `/home/admin/embedded-agent/cloud`。

---

## 2. 真源和目录划分

### 2.1 本仓库内与网页/云端最相关的目录

| 路径 | 作用 | 是否真正在跑 |
|---|---|---|
| `UI/RA8P1_UI.html` | 本项目的交互原型页，包含板端 HMI 和 Cloud Console 视觉方案 | 否，原型 |
| `docs/ui_operation_interface_plan.md` | 板端与云端 Web 的页面规划 | 否，设计说明 |
| `docs/esp32_uart_link_next_steps.md` | 当前 MQTT/UART/ACK 联调基线 | 是，板端协议真相文档 |
| `docs/threshold_execution_baseline.md` | 传统 `threshold_control` 真实闭环基线 | 是 |
| `docs/rule_program_execution_baseline.md` | 结构化 `rule_program` 真实闭环基线 | 是 |
| `tools/validate_threshold_loop.py` | 传统阈值链路验收脚本 | 是 |
| `tools/validate_rule_program_loop.py` | `rule_program` 链路验收脚本 | 是 |
| `src/esp32_link.c` | RA8P1 侧 UART 协议处理、ACK、执行状态上报 | 是 |
| `esp32-s3-uart-link-arduino/esp32_s3_uart_link/esp32_s3_uart_link.ino` | ESP32 WiFi/MQTT bridge 真正实现 | 是 |

### 2.2 云端代码真源

| 路径 | 作用 |
|---|---|
| `D:\Embedded-agent\cloud\app` | FastAPI、Agent、MQTT、日志、设备状态 |
| `D:\Embedded-agent\cloud\web` | 当前实际网页控制台，纯静态 HTML/CSS/JS |
| `D:\Embedded-agent\cloud\tests` | API/协议/编译/知识校验测试 |

### 2.3 接手时应该优先看谁

- 网页开发接手先看：`D:\Embedded-agent\cloud\web`
- 接口接入先看：`D:\Embedded-agent\cloud\app\api\routes.py`
- MQTT/ACK 判断先看：`D:\Embedded-agent\cloud\app\device_state\store.py`
- 板端真正会收到什么命令先看：`esp32-s3-uart-link-arduino/esp32_s3_uart_link/esp32_s3_uart_link.ino`
- 为什么某些请求 `ack_received=false` 但板子其实动了，先看：`docs/rule_program_execution_baseline.md`

---

## 3. 当前网页端现状

## 3.1 原型页

`UI/RA8P1_UI.html` 是静态高保真原型，适合做：

- 页面结构参考
- 模块命名参考
- 演示动线参考

不适合直接当生产前端的原因：

- 没有实际 API 封装
- 没有鉴权逻辑
- 没有和 FastAPI 的真实字段完全对齐
- 混合了板端 HMI 和云端 Web 的展示概念

## 3.2 当前实际网页

当前真实网页在 `D:\Embedded-agent\cloud\web`，是一个非常轻量的静态控制台：

- `index.html`
- `styles.css`
- `app.js`

技术栈不是 React/Vue，也没有打包器，直接由 FastAPI 挂载：

- `/` 返回 `index.html`
- `/assets/*` 返回 `web` 目录里的静态资源

当前页面已经接了这些后端接口：

- `GET /health`
- `GET /devices/{device_id}/state`
- `GET /devices/{device_id}/messages`
- `GET /deployments?limit=10`
- `POST /agent/interpret`
- `POST /agent/interpret/deploy`

### 3.3 当前网页的局限

当前控制台能用，但要明确它还偏“演示/运维页”，不是完整业务前端：

- 只接了老的自然语言意图链路 `/agent/interpret*`
- 还没有把 `/agent/program/*` 做成正式页面
- 还没有把事件流、历史详情、ACK 异常分层展示完整
- 没有区分“发布失败”“ACK 缺失”“执行成功但 ACK 丢失”

---

## 4. 云服务器与后端现状

## 4.1 后端技术栈

当前后端是 FastAPI，入口：

- `D:\Embedded-agent\cloud\app\main.py`
- 启动对象：`cloud.app.main:app`

核心行为：

- FastAPI 提供 HTTP API
- 启动时拉起 MQTT 状态订阅器
- 订阅 `cloudbridge/{device_id}/status|telemetry|event`
- 把最新设备状态和事件缓存到内存状态仓库
- 网页和验收脚本都通过 HTTP 查状态，不直接查 MQTT

## 4.2 配置文件

本地配置文件：

- `D:\Embedded-agent\cloud\.env`
- 模板：`D:\Embedded-agent\cloud\.env.example`

关键配置项：

| 配置 | 作用 |
|---|---|
| `API_TOKEN` | 受保护接口的鉴权令牌 |
| `MQTT_ENABLED` | 是否真的向 broker 发布 |
| `MQTT_BROKER_URL` / `MQTT_PORT` | MQTT 地址 |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | MQTT 账号 |
| `MQTT_SCRIPT_SECRET` | 下发签名用密钥 |
| `DEVICE_ID` | 默认设备 ID，当前默认 `ra8p1_demo_001` |
| `DEPLOY_ACK_TIMEOUT_SEC` | 等待 ACK 超时，当前默认 `5` 秒 |
| `DEEPSEEK_MODEL` | 当前规则程序解释目标模型，默认 `deepseek-v4-pro` |

## 4.3 鉴权规则

当前规则很简单：

- `GET /health` 公开
- `/` 和 `/assets/*` 公开
- 其他实际操作接口默认都要 `X-API-Token`

前端现在也是这样实现的：

- Token 存浏览器 `localStorage`
- 受保护接口统一带 `X-API-Token`
- 如果返回 `401`，弹出 Token 对话框

---

## 5. 推荐的数据流理解方式

当前项目网页接入时，建议始终按下面这条链路理解：

```text
Web Page
-> FastAPI
-> Agent Graph / Program Graph
-> MQTT publish to cloudbridge/{device_id}/script
-> ESP32 解析 payload
-> UART 发给 RA8P1
-> RA8P1 回 ack / exec
-> ESP32 发布 event/status/telemetry
-> FastAPI MQTT subscriber 更新设备状态
-> Web 再通过 HTTP 查询 state/events/messages/deployments
```

重点：

- 前端不需要知道串口细节，但必须知道 ACK/状态是“异步回流”的。
- 前端不要拿“部署接口返回值”当最终执行结果，尤其是 `rule_program`。

---

## 6. HTTP API 速查

## 6.1 公共接口

| 方法 | 路径 | 作用 | 鉴权 |
|---|---|---|---|
| `GET` | `/health` | 健康检查、默认设备、MQTT 是否启用、知识库状态 | 否 |

`/health` 返回值里前端目前最常用字段：

- `ok`
- `device_id`
- `mqtt_enabled`
- `knowledge`

## 6.2 传统意图链路

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/agent/interpret` | 自然语言 -> `intent` |
| `POST` | `/agent/compile` | `intent` -> Lua + MQTT payload 预览 |
| `POST` | `/agent/deploy` | 直接用结构化 `intent` 下发 |
| `POST` | `/agent/interpret/deploy` | 自然语言 -> `intent` -> 下发 |

`/agent/deploy` 请求体核心结构：

```json
{
  "request_id": "req_xxx",
  "device_id": "ra8p1_demo_001",
  "need_confirm": true,
  "wait_for_ack": true,
  "intent": {
    "intent_type": "threshold_control",
    "target_devices": ["AHT20", "SG90"],
    "conditions": {
      "sensor": "AHT20.temp",
      "operator": ">",
      "value": 30
    },
    "actions": [
      {
        "device": "SG90",
        "method": "servo_set",
        "params": {
          "angle": 180
        }
      }
    ],
    "loop_interval_ms": 1000
  }
}
```

## 6.3 `rule_program` 链路

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/agent/program/interpret` | 自然语言 -> 结构化 `rule_program` |
| `POST` | `/agent/program/interpret/deploy` | 自然语言 -> `rule_program` -> 下发 |
| `POST` | `/agent/program/deploy` | 直接下发结构化 `rule_program` |

`/agent/program/deploy` 请求体核心结构：

```json
{
  "request_id": "rpv_xxx",
  "device_id": "ra8p1_demo_001",
  "need_confirm": true,
  "wait_for_ack": true,
  "program": {
    "program_id": "temp_sg90_demo",
    "version": "rule_program.v1",
    "trigger": {
      "sensor": "AHT20.temp",
      "operator": ">=",
      "value": 35
    },
    "actions": [
      {
        "device": "SG90",
        "method": "servo_set",
        "params": {
          "angle": 0,
          "duration_ms": 350
        }
      },
      {
        "device": "SG90",
        "method": "servo_set",
        "params": {
          "angle": 90,
          "duration_ms": 350
        }
      }
    ],
    "loop_interval_ms": 1000,
    "cooldown_ms": 30000,
    "description": "当温度到35度时，舵机来回旋转两次"
  }
}
```

## 6.4 状态与历史接口

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/devices/{device_id}/state` | 当前设备快照 |
| `GET` | `/devices/{device_id}/events?limit=20` | 最近事件流 |
| `GET` | `/devices/{device_id}/messages?limit=50` | 最近 MQTT 消息历史 |
| `GET` | `/deployments?limit=20` | 最近部署记录 |
| `GET` | `/deployments/{request_id}` | 某次部署详情 |

前端最常用的状态字段路径：

- `state.last_status.payload.script_state`
- `state.last_status.payload.last_request_id`
- `state.last_status.payload.last_intent_type`
- `state.last_status.payload.aht20.temp`
- `state.last_status.payload.aht20.humidity`
- `state.last_status.payload.last_execution`
- `state.last_event`
- `state.last_deploy_ack`

---

## 7. MQTT 与设备协议速查

## 7.1 MQTT Topic

当前设备 `device_id=ra8p1_demo_001` 时：

- `cloudbridge/ra8p1_demo_001/script`
- `cloudbridge/ra8p1_demo_001/status`
- `cloudbridge/ra8p1_demo_001/telemetry`
- `cloudbridge/ra8p1_demo_001/event`

### 7.2 云端发给设备的 MQTT 包

云端发布类型固定为：

- `type = deploy_script`

核心 envelope：

```json
{
  "request_id": "req_xxx",
  "type": "deploy_script",
  "timestamp": 1710000000,
  "payload": {
    "script_id": "script_xxx",
    "intent_type": "threshold_control or rule_program or screen_text",
    "version": "v1",
    "lua_code": "...",
    "need_confirm": true,
    "checksum": "sha256:...",
    "target_device_id": "ra8p1_demo_001",
    "auth_signature": "...",
    "rule_program": {}
  }
}
```

说明：

- `rule_program` 只在结构化链路时出现。
- 即使是 `rule_program`，云端仍会同时生成 `lua_code`。
- ESP32 当前优先解析 `rule_program`，其次解析 `threshold_control` 风格 Lua，最后才退化为 `screen_text/print` 文本展示。

## 7.3 ESP32 转给 RA8P1 的 UART 行协议

基础状态类：

- `esp32-ready`
- `wifi:connected` / `wifi:disconnected`
- `mqtt:connected` / `mqtt:disconnected`
- `pong`

任务类：

- `req:<request_id>`
- `script:<script_id>`
- `cmd:<display_text>`
- `intent:<intent_type>`

规则执行类：

- `rule:sensor=temp;op=>;value=300`
- `seq:clear`
- `seq:add;angle=90;ms=350`
- `cooldown:ms=30000`

RA8P1 回传类：

- `ack:req=...;script=...;code=0;msg=accepted`
- `exec:req=...;script=...;state=...;reason=...;sample=...;t=...;op=...;value=...;action=SG90;angle=...`
- `aht20:status=online;t=26.4;h=50.3;crc=1`

---

## 8. 前端必须知道的当前能力边界

## 8.1 已稳定可用

- 健康检查 `/health`
- Token 鉴权
- 设备状态查询 `/devices/{device_id}/state`
- 传统 `threshold_control` 下发与 ACK
- `screen_text` 文本展示与 ACK
- AHT20 温湿度状态查询
- 历史部署和消息查询

## 8.2 已能跑通，但前端要特殊处理

- `rule_program` 真实执行已跑通
- 结构化 SG90 序列执行已跑通
- `TRIGGERED -> DONE` 事件链已跑通
- 但 `rule_program` 的 HTTP 下发当前仍可能 `ack_received=false`

这意味着：

- `rule_program` 的前端结果页不能只看 `ack_received`
- 应同时检查：
  - `/devices/{device_id}/state`
  - `last_intent_type == rule_program`
  - `script_state`
  - `last_execution.state`
  - 最近 `execution_state` 事件

## 8.3 还不能对外承诺的事

- 不能对外说“RA8P1 已经是完整 Lua 运行时”
- 不能对外说“所有外设都可通过网页任意编排”
- 不能把 `rule_program` 的 ACK 问题说成“执行失败”

---

## 9. 已知坑和接手注意事项

## 9.1 `request_id` 长度限制

当前 RA8P1/ESP32 侧 `request_id/script_id` 缓冲区支持 `64` 字节级别，验收文档要求：

- `request_id` 最好控制在 `63` 个字符以内

否则可能出现：

- 板子实际执行了
- `execution_state` 也回来了
- 但 `deploy_ack` 对不上，云端显示 `ack_received=false`

前端建议：

- 自己生成短 ID，例如 `web_时间戳`
- 不要直接用超长 UUID 拼字符串

## 9.2 不要把浏览器直接接到 MQTT

原因：

- 当前系统已经有签名、知识校验、Lua 校验、部署日志、ACK 追踪
- 直接 MQTT 会绕过这些保护
- 浏览器也不适合持有 MQTT 用户名、密码、签名规则

## 9.3 当前静态网页只接了旧链路

`D:\Embedded-agent\cloud\web\app.js` 目前调用的是：

- `/agent/interpret`
- `/agent/interpret/deploy`

如果新接手人要做“动态动作计划/结构化程序”，必须新增：

- `/agent/program/interpret`
- `/agent/program/interpret/deploy`
- `/agent/program/deploy`

## 9.4 `screen_text` 适合做 smoke，不适合做复杂业务

当前 `screen_text` 很适合：

- 联调 smoke
- 设备在线确认
- 演示基础闭环

不适合：

- 当成复杂动作编排入口
- 承担完整业务指令结构

---

## 10. 对接网页时的建议实现顺序

### 第 1 步：先复用现有 FastAPI，不改协议

建议新前端第一版只做 HTTP 封装，不碰下面这些东西：

- MQTT topic 结构
- ACK 等待逻辑
- `deploy_script` envelope
- `auth_signature`

### 第 2 步：页面至少分成 4 个模块

建议直接按下面的功能拆：

1. `系统状态`
   - `/health`
   - 默认设备
   - MQTT 是否启用
2. `设备快照`
   - `/devices/{device_id}/state`
   - 温湿度
   - 最近执行状态
3. `部署中心`
   - `screen_text`
   - `threshold_control`
   - `rule_program`
4. `历史与事件`
   - `/deployments`
   - `/devices/{device_id}/events`
   - `/devices/{device_id}/messages`

### 第 3 步：把结果状态分成 3 层

前端展示不要只给一个“成功/失败”，而是至少分三层：

- `发布层`
  - HTTP 成功没有
  - MQTT 发布成功没有
- `ACK 层`
  - `ack_received` 是不是 true
- `执行层`
  - `last_execution.state`
  - `execution_state` 事件有没有出现

对 `rule_program` 特别重要：

- 可能 `ACK 层` 失败
- 但 `执行层` 成功

### 第 4 步：先保留双链路

现阶段不要把老链路删掉：

- 保留 `threshold_control`
- 新增 `rule_program`

原因：

- `threshold_control` 目前 ACK 更稳定，适合 smoke
- `rule_program` 适合做下一阶段主入口

---

## 11. 新接手人最小自测清单

### 11.1 只测云端服务是否活着

1. 打开 `GET /health`
2. 确认 `ok=true`
3. 确认 `device_id=ra8p1_demo_001`

### 11.2 只测前端鉴权和状态页

1. 准备 `X-API-Token`
2. 调 `GET /devices/ra8p1_demo_001/state`
3. 页面能看到 `aht20/temp/humidity/last_execution`

### 11.3 测最稳 smoke

优先用 `screen_text` 或老的 `threshold_control`，不要一上来就只测 `rule_program`。

### 11.4 测 `rule_program`

测试通过标准不要只看 `ack_received`，还要看：

- `last_intent_type == rule_program`
- `last_execution.state == DONE` 或至少看到 `TRIGGERED`
- 最近事件中有 `execution_state`

---

## 12. 建议交接时明确告诉接手人的一句话

如果只给接手人一句话，建议直接告诉他：

> 当前网页应该基于 `D:\Embedded-agent\cloud\web` 和 `D:\Embedded-agent\cloud\app\api\routes.py` 接 FastAPI；设备协议与 ACK 真相以本仓库 `docs/`、`src/esp32_link.c`、`esp32_s3_uart_link.ino` 为准；`threshold_control` 是稳定基线，`rule_program` 已可执行但 ACK 还未完全对齐。

---

## 13. 推荐先读的文件

按阅读顺序建议：

1. `docs/web_cloud_handoff.md`
2. `D:\Embedded-agent\cloud\app\api\routes.py`
3. `D:\Embedded-agent\cloud\web\app.js`
4. `docs/esp32_uart_link_next_steps.md`
5. `docs/threshold_execution_baseline.md`
6. `docs/rule_program_execution_baseline.md`
7. `esp32-s3-uart-link-arduino/esp32_s3_uart_link/esp32_s3_uart_link.ino`
8. `src/esp32_link.c`
