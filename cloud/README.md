# Cloud

云端 Agent、API、MQTT 服务目录。

## 2026-06-06 正式网页基线

公网网页现在是服务器工作台，不再是设备模拟控制台：

- 网页：`https://<your-domain>/`
- 登录：服务器用户 + Argon2 密码 + 服务端 SQLite 会话
- 浏览器凭据：`HttpOnly`、`Secure`、`SameSite=Lax` Cookie
- 写操作保护：CSRF Token
- 对话入口：`POST /web/chat`
- 对话历史：`GET /web/chat/history`
- 服务器资料：`GET /web/context`
- Hermes：FastAPI 通过 `127.0.0.1:8642` 调用官方 Hermes API Server
- Hermes 内部密钥不下发到浏览器
- 用户之间使用独立 Hermes conversation
- 网页管理员可通过 `WEB_HARDWARE_CONTROL_ENABLED=true` 开启硬件下发；即时 SG90 指令继续走既有 `manual_action -> MQTT -> ESP32 -> RA8P1 -> execution_state` 链路
- Hermes/模型先结合对话上下文、设备能力和最新上报数据判断请求，再由服务端校验并执行；模型不能绕过动作白名单直接生成板端代码
- 温度、湿度、光照条件任务使用独立的云端持久化任务层，可同时存在且互不覆盖；满足条件后复用既有 SG90 `manual_action` 链路
- Web 与 QQBot 共用同一任务服务，支持一次性环境汇报、每日环境汇报、任务列表和任务取消
- I2C 在网页模型中以 `SDA/SCL -> 已识别硬件端点` 组织，不再以某个传感器作为第一层级
- 平台化能力层已开始接入：云端将旧 `AHT20.temp` 兼容映射为 `env.temperature`，将 `SG90.servo_set` 映射为 `motor.servo.angle`；当前下发协议仍保持 `rule_program.v1`，无需立即重刷硬件固件

`/agent/*`、MQTT、ACK 和设备状态接口暂时保留为工程兼容层，但不再是公网网页的交互入口。

当前已配置第一版本地云端服务骨架：

- FastAPI 入口：`cloud.app.main:app`
- 健康检查：`GET /health`
- Hermes 正式自然语言入口：`POST /agent/hermes/chat`
- 语音转写：`POST /agent/speech/transcribe`
- 语音意图解析：`POST /agent/speech/interpret`
- 语音解析并下发：`POST /agent/speech/deploy`
- 自然语言意图解析：`POST /agent/interpret`
- 自然语言解析并下发：`POST /agent/interpret/deploy`
- 云端知识状态：`GET /agent/knowledge/status`
- 固定模板编译：`POST /agent/compile`
- 编译并下发脚本：`POST /agent/deploy`
- MQTT Topic：`cloudbridge/{device_id}/script`
- MQTT 状态订阅：`cloudbridge/+/status`、`cloudbridge/+/telemetry`、`cloudbridge/+/event`、`cloudbridge/+/log`
- 设备注册：`POST /devices/register` / `POST /api/devices/register`
- 网页设备列表：`GET /web/devices`
- 硬件档案：`GET /hardware/catalog`
- 设备诊断/能力：`GET /devices/{device_id}/diagnostics`

量产设备识别链路：

1. RA8P1 固件读取 `R_BSP_UniqueIdGet()` 并通过 UART 发给 ESP32。
2. ESP32 使用 `ra8p1_uid + esp32_mac + esp32_chip_id` 向云端注册。
3. 云端在 `DEVICE_REGISTRY_DB_PATH` 指向的 SQLite 表中生成/保存 `device_id`、设备标签和 `device_secret`。
4. 网页顶部设备选择器决定当前会话、信号通道和控制下发使用哪个 `device_id`。
5. 下发仍发布到 `cloudbridge/{device_id}/script`；状态接入使用通配订阅以容纳多台设备。

建议模块：

- `app/api`: FastAPI 路由。
- `app/agent_service`: 意图识别、编排、LLM 调用。
- `app/registry`: 硬件能力注册表和 Lua API 白名单。
- `app/template_compiler`: `intent JSON -> Lua`。
- `app/mqtt_service`: MQTT 收发、ACK、重试。
- `app/log_service`: request_id 贯穿的链路日志。
- `prompts`: 系统提示词、few-shot、模板规则。
- `tests`: 协议、模板编译、回归样例。

## LLM Wiki / GBrain 运行时接入

云端 Agent 现在会在运行时读取本地知识资产：

- LLM Wiki：`docs/`
- GBrain：`mcp/resources/gbrain/`
- Manifest：`mcp/resources/project_manifest.json`、`protocol_manifest.json`、`hardware_manifest.json`

接入点：

- `cloud.app.knowledge_base` 读取 Wiki/GBrain/manifest，并提供云端等价校验。
- `POST /agent/interpret` 生成 intent 后，会根据 GBrain capability 和 manifest 约束校验。
- `POST /agent/compile` 返回 `knowledge_validation` 和 `mqtt_validation`。
- `POST /agent/deploy`、`POST /agent/interpret/deploy`、`POST /agent/speech/deploy` 在 MQTT 下发前执行知识校验和协议校验。
- `GET /agent/knowledge/status` 返回当前云端可见的 Wiki/GBrain 资源状态。

第一阶段仍采用 Markdown + JSON 作为离线基线，不依赖外部 RAG、数据库或 Dify/Flowise。服务器部署时如果使用裁剪包，必须同时包含 `docs/` 和 `mcp/resources/`，否则云端知识校验无法启动。

## 平台硬件档案与能力注册

云端现在包含第一版平台硬件档案模块 `cloud.app.hardware_catalog`，用于把项目专用硬件字段逐步升级为平台级能力：

```text
legacy: AHT20.temp       -> capability: env.temperature
legacy: AHT20.humidity   -> capability: env.humidity
legacy: SG90.servo_set   -> capability: motor.servo.angle
```

第一批 I2C 档案覆盖：

- `AHT20/AHT21` 类温湿度传感器
- `SHT3x` 温湿度传感器
- `BME280/BMP280` 环境传感器
- `SSD1306` OLED 显示
- `MPU6050` IMU
- `PCA9685` PWM/舵机扩展
- `ADS1115` ADC
- `PCF8574/MCP23017` IO 扩展

当前阶段是云端兼容式升级：

- 设备状态仍兼容旧字段 `aht20`、`i2c`、`hardware_list`。
- `/devices/{device_id}/state` 会额外返回 `diagnostics`。
- `/devices/{device_id}/diagnostics` 会返回 `hardware_registry` 和 `platform_capabilities`。
- `/hardware/catalog` 会返回云端可识别的硬件档案和能力别名。
- `rule_program.v1` 下发给 ESP32/RA8P1 时仍使用 `AHT20.temp`，以保持当前固件兼容。

后续需要重刷固件时，再把 RA8P1/ESP32 上报升级成原生：

```json
{
  "buses": [
    {
      "id": "i2c.s1",
      "type": "i2c",
      "diag": "ok",
      "devices": [
        {
          "address": "0x38",
          "type": "AHT20",
          "confidence": "exact",
          "capabilities": ["env.temperature", "env.humidity"]
        }
      ]
    }
  ]
}
```

这样平台可以逐步从“当前参考硬件”过渡到“任意用户设备的能力发现与自然语言控制”。

## 状态图编排与 DeepSeek

云端部署链路由 `cloud.app.agent_service.graph.AgentGraph` 执行。当前是无外部依赖的 LangGraph-style 状态图，节点包括设备解析、知识装载、intent 校验、Lua 编译、MQTT 校验、发布、ACK 等待和记录。API 响应中的 `graph_trace` 会返回本次执行经过的节点。

当前正式网页自然语言入口应优先走 `POST /agent/hermes/chat`。旧的 `/agent/interpret/deploy` 与 `/agent/program/interpret/deploy` 只保留兼容职责；当 `LLM_PROVIDER=hermes_official` 时，它们必须回退委托给 Hermes，而不是绕过 Hermes 直接走历史解析器。

自然语言 intent 生成默认仍使用规则解析器。配置 `LLM_PROVIDER=deepseek`、`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL=deepseek-v4-pro` 后，云端会调用 DeepSeek 生成 intent JSON；DeepSeek 不允许直接生成 Lua 或 MQTT payload，输出仍必须经过 GBrain、manifest、Pydantic、Lua 和 MQTT 校验。

## 本地启动

```powershell
cd D:\Embedded-agent
Copy-Item cloud\.env.example cloud\.env
.\.venv\Scripts\python.exe -m pip install -r cloud\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn cloud.app.main:app --host 0.0.0.0 --port 8000
```

默认 `MQTT_ENABLED=false`，接口会生成完整 MQTT 消息但不连接 broker。等本地或云端 MQTT Broker 准备好后，在 `cloud\.env` 中填写：

```env
MQTT_ENABLED=true
MQTT_BROKER_URL=你的broker地址
MQTT_PORT=1883
MQTT_USERNAME=你的用户名
MQTT_PASSWORD=你的密码
MQTT_SCRIPT_SECRET=与ESP32一致的长随机签名密钥
MQTT_TLS_ENABLED=false
MQTT_CA_CERT_PATH=
DEVICE_ID=ra8p1_demo_001
LOG_DB_PATH=:temp:
ASR_PROVIDER=mock
ASR_MODEL=gpt-4o-mini-transcribe
WEB_HARDWARE_CONTROL_ENABLED=false
WEB_HARDWARE_CONTROL_ROLES=admin
WEB_HARDWARE_WAIT_FOR_ACK=false
QQBOT_HARDWARE_CONTROL_ENABLED=false
AUTOMATION_TASK_DB_PATH=runtime/automation_tasks.sqlite3
```

安全相关补充：

- `MQTT_SCRIPT_SECRET` 用于给 `deploy_script` 生成签名，ESP32 会校验 `target_device_id + checksum + auth_signature`。
- 切到 TLS 后把 `MQTT_PORT` 改成 broker 的 TLS 端口，并填写 `MQTT_CA_CERT_PATH`。
- API 默认增加了应用层限流；生产环境仍建议同时保留 `nginx` 限流和主机防火墙。
- `WEB_HARDWARE_CONTROL_ENABLED=false` 是安全默认值；需要网页对话直接控制硬件时，先确认 MQTT、设备 ID、ESP32/RA8P1 固件和外设接线，再改为 `true`。
- `WEB_HARDWARE_WAIT_FOR_ACK=false` 可避免网页在设备离线时长时间等待；连板验收阶段可临时设为 `true` 来让响应等待 ACK。
- 生产环境不得同时启用 `embedded-agent-mock-device.service` 和真实设备自动化；模拟遥测会污染模型上下文和触发条件判断。

支持的对话示例：

- `让 SG90 向左和向右各转动 2 次，30 度`
- `当温度达到 32 度时，舵机向左和向右各转动 2 次，30 度`
- `当湿度达到 60% 时，舵机持续向左转动 2 次，60 度`
- `当光照低于 50 lux 时，舵机持续向右转动 3 次，30 度`
- `晚上九点十分向我汇报温湿度和光照情况`
- `每天早上八点向我汇报温湿度和光照情况`
- `查看任务`、`取消 task_xxxxxxxxxxxx`

定时与舵机语义：

- 只说 `21点26分` 而未说明今天或每天时，系统必须先追问，不创建任务。
- `今天/短期/一次性` 任务默认绑定当前对话；删除对话时一并停用。
- `每天/长期/永久` 属于明确的长久意图，可在原对话删除后继续存在。
- SG90 默认保持最后目标角度；只有明确说 `自动复位/回中`，或在当前对话设置 `以后都自动复位` 时才回到 90 度。
- 设备新版遥测通过 `payload.clock.local_iso` 上报完整日期时间，`/web/context` 返回与 Web 服务时间的偏差。

`LOG_DB_PATH=:temp:` 会把本地开发日志库放到系统临时目录。部署到服务器时可改成持久化路径，例如 `runtime/cloud/embedded_agent.sqlite3`。
`ASR_PROVIDER=mock` 用于无硬件、无 API key 的本地闭环；切到真实云端转写时设置 `ASR_PROVIDER=openai` 并填写 `OPENAI_API_KEY`。

## 示例请求

```powershell
$body = @{
  request_id = "req_local_001"
  intent = @{
    intent_type = "threshold_control"
    target_devices = @("AHT20", "SG90", "BUZZER")
    conditions = @{ sensor = "AHT20.temp"; operator = ">"; value = 30 }
    actions = @(
      @{ device = "SG90"; method = "servo_set"; params = @{ angle = 180 } },
      @{ device = "BUZZER"; method = "buzzer"; params = @{ freq = 2000; ms = 300 } }
    )
    loop_interval_ms = 1000
  }
  need_confirm = $true
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Uri http://127.0.0.1:8000/agent/deploy -Method Post -ContentType "application/json" -Body $body
```

## 自然语言软件闭环

无硬件阶段可以先用规则解析器验证 `自然语言 -> Intent -> Lua -> MQTT payload`：

```powershell
$body = @{
  text = "温度超过30度时让舵机转到180度并蜂鸣，每1秒检查一次"
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Uri http://127.0.0.1:8000/agent/interpret -Method Post -ContentType "application/json" -Body $body
```

直接生成并下发 payload：

```powershell
$body = @{
  request_id = "req_voice_001"
  text = "temperature > 28 servo 90 degrees and buzzer 1500Hz 500ms"
  wait_for_ack = $false
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Uri http://127.0.0.1:8000/agent/interpret/deploy -Method Post -ContentType "application/json" -Body $body
```

## 语音软件闭环

无硬件阶段使用 `mock` ASR，上传任意音频字节，并通过 `X-Mock-Transcript` 模拟转写结果：

```powershell
$audio = [System.Text.Encoding]::UTF8.GetBytes("mock audio")

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/agent/speech/interpret?filename=mock.wav" `
  -Method Post `
  -ContentType "audio/wav" `
  -Headers @{ "X-Mock-Transcript-Base64" = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("温度超过30度时让舵机转到180度并蜂鸣")) } `
  -Body $audio
```

语音解析并生成下发 payload：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/agent/speech/deploy?request_id=req_speech_001&wait_for_ack=false" `
  -Method Post `
  -ContentType "audio/wav" `
  -Headers @{ "X-Mock-Transcript-Base64" = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("温度超过30度时让舵机转到180度并蜂鸣")) } `
  -Body $audio
```
