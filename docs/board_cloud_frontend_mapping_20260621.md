# 本工程能力到云端前端/服务器映射核对（2026-06-21）

## 结论摘要

当前 `RA8P1_Viewing_Screen_ESP32_Link` 的核心云端链路已经统一到一条明确的数据模型上：

`RA8P1 platform_ports / samples -> ESP32 status / telemetry MQTT -> cloud /web/context + signal_topology -> web app renderSignals`

也就是说，`AHT20`、`BH1750`、`SG90`、`UART/WiFi/MQTT` 这些真实硬件/通道状态，已经不是分别靠旧字段或手写页面在传，而是主要通过 `ports + samples + module metadata` 在向上贯通。

但这次核对也确认了几处仍然存在的“显示层/能力层漂移”：

1. 板端 `PORTS` 页会把 `BH1750` 逻辑上映射到 `I2C-2` 卡片显示，但云端真实数据模型里它仍然属于 `i2c.s1` 这条复用总线。
2. 板端本地能力里有 `FT6336` 触摸、`ILI9488` LCD、顶部时钟、本地 WiFi 弹层，这些并没有完整映射到网页。
3. `buzzer.active` 已经在板端/状态模型里存在，但服务器的硬件能力目录和网页 Agent 控制路径还没有把它当成一等能力。
4. 网页前端能显示实时信号拓扑，但对 `env.light`、`i2c.mux` 这类模块类名的中文标签还不完整。
5. 板端预留了自然语言下发入口，但当前屏幕 UI 并没有实际提交文本；自然语言控制目前真正可用的是网页 `chat -> web_hardware_agent -> deploy_rule_program`。

## 1. 当前工程真实能力

### 1.1 板端主循环与能力入口

- `src/hal_entry.c:150-224`
  初始化 `LCD + LVGL + Touch + platform_ports + app_ui + SG90 + esp32_link`，并在主循环里轮询：
  - `AHT20`
  - `BH1750`
  - `I2C` 扫描
  - `device_registry`
  - `esp32_link`
  - `rule_tick`

- `src/platform_ports.c:351-405`
  板端统一维护 4 个标准口：
  - `i2c.s1`
  - `i2c.s2`
  - `pwm.0`
  - `uart.bridge`

- `src/platform_ports.c:185-230`
  `i2c.s1` 支持按真实探测结果挂接：
  - `AHT20 -> env.temperature / env.humidity`
  - `BH1750 -> env.light.lux`
  - `9548A-MUX -> i2c.mux`

- `src/platform_ports.c:565-603`
  `pwm.0` 当前暴露两个写能力：
  - `motor.servo.angle`
  - `buzzer.active`

### 1.2 板端本地 UI 能力

- `src/app_ui.c:1-140`
  当前板端 UI 是 4 页结构：
  - `HOME`
  - `LIST`
  - `DETAIL`
  - `PORTS`
  外加 1 个 `WiFi` 弹层。

- `src/app_ui.c:921-927`
  点击顶栏 WiFi 会触发 `esp32_link_request_wifi_scan()`，说明板端屏幕具备“本地请求扫描 WiFi”的入口。

- `src/app_ui.c:1681-1726`
  板端会维护一份本地 WiFi 网络列表，并可在屏上选择网络。

- `src/app_ui.c:1137-1159` 与 `src/app_ui.c:1681-1686`
  板端顶部时钟使用 `ESP32` 下发的 `time:HH:MM:SS` 作为同步基准，然后在本地继续走时。

- `src/app_ui.c:1456-1557`
  板端 `PORTS` 页有一个“逻辑视图”：
  - `I2C-1` 显示温湿度
  - `I2C-2` 逻辑上映射为 `BH1750`
  - `PWM-0` 显示执行器
  - `UART-BRIDGE` 显示 WiFi / MQTT

注意：这个 `I2C-2 = BH1750` 只是板端 UI 逻辑映射，不是底层真实端口定义。

### 1.3 板端当前未真正打通到云端的能力

- `src/device_registry.c:67-104`
  板端本地注册表里有静态设备：
  - `ESP32-S3 网桥`
  - `LCD 显示屏`
  - `FT6336 触摸控制器`

这些设备目前主要服务于板端 UI，不属于云端 `signal_topology` 的主消费对象。

- `src/app_ui.c:1659`
  `app_ui_take_input_submission()` 当前直接返回 `false`。
  这说明虽然 `hal_entry.c:219-221` 还保留了 `esp32_link_submit_nl_text()` 的调用点，但当前板端屏幕并没有真正把自然语言文本提交到云端。

## 2. 板端到服务器的数据映射

### 2.1 RA8P1 -> ESP32

- `src/esp32_link.c:406-491`
  RA8P1 会把 `platform_ports` 和 `platform_samples` 逐项通过 UART 发给 ESP32。

- `src/esp32_link.c:1417-1443`
  规则执行状态会以 `exec:req=...;script=...;state=...` 的形式回传，同时刷新 `pwm.0` 的执行反馈并再次发布平台快照。

- `src/esp32_link.c:1092-1110`
  ESP32 返回的 `wifi:`、`wifi-ssid:`、`time:` 会直接回写到板端 UI。

### 2.2 ESP32 -> Cloud

- `esp32_s3_uart_link.ino:1464-1535`
  ESP32 会优先把板端上送的 `ports` 结构写入 MQTT `status` 负载。

- `esp32_s3_uart_link.ino:1536-1588`
  ESP32 会把板端上送的 `samples` 结构写入 MQTT `telemetry` 负载。

- `esp32_s3_uart_link.ino:2217-2249`
  `publish_status()` 会发布：
  - `device_id`
  - `identity`
  - `script_state`
  - `ports`
  - `last_script_id`

- `esp32_s3_uart_link.ino:2325-2347`
  `publish_telemetry()` 会发布：
  - `device_id`
  - `identity`
  - `ports`
  - `samples`

- `esp32_s3_uart_link.ino:2375-2549`
  `deploy_ack` 与 `execution_state` 事件会单独走 `event` 主题上报。

- `esp32_s3_uart_link.ino:671-747`
  设备注册会走 `POST /api/devices/register`，拿回真实 `device_id / device_secret` 并本地持久化。

### 2.3 Cloud Server 消费板端状态

- `cloud/app/api/web_routes.py:276-321`
  `/web/context` 是网页的总上下文入口，返回：
  - 当前 `device_id`
  - 设备列表
  - `signal_topology`
  - `module_bindings`
  - `diagnostics`
  - `model_config`
  - `device_state`

- `cloud/app/server_context.py:198-276`
  服务器优先从 `ports + samples` 生成 `signal_topology.v3`，这是当前最关键的统一消费层。

- `cloud/app/server_context.py:225-245`
  服务器会保留并透传这些模块元数据：
  - `activation`
  - `diag`
  - `driver`
  - `confidence`
  - `module_class`
  - `model_state`
  - `binding_source`
  - `device_key`

这与板端 `platform_ports`、ESP32 `status/telemetry` 的字段已经是对齐的。

## 3. 当前工程能力到网页的映射

### 3.1 网页的主要页面/入口

- `cloud/web/app.js:1159-1170`
  网页目前有 5 个主要视图：
  - `chat`
  - `signals`
  - `models`
  - `provision`
  - `account`

### 3.2 信号通道页（最直接映射板端能力）

- `cloud/web/app.js:189-223`
  前端进入页面后会先调用 `/web/context`，并自动选择在线设备。

- `cloud/web/app.js:258-335`
  `renderSignals()` 和 `renderEndpoint()` 会把服务器给出的 `signal_topology` 显示成网页上的信号卡片、端点卡片、读数和能力标签。

因此下面这些板端能力已经映射到网页：

| 板端能力 | 板端来源 | 服务器消费 | 网页表现 |
| --- | --- | --- | --- |
| `AHT20` 温度/湿度 | `platform_ports_set_i2c_s1_aht20_sample()` | `server_context._readings_from_port()` | `signals` 页读数卡 |
| `BH1750` 光照 | `platform_ports_set_i2c_s1_bh1750_sample()` | 同上 | `signals` 页读数卡 |
| `SG90` 执行反馈 | `platform_ports_set_pwm0_execution_feedback()` | `signal_topology.v3` 中 `pwm.0` | `signals` 页端点卡 |
| `UART/WiFi/MQTT` | `uart.bridge` | `signal_topology.v3` 中 `uart.bridge` | `signals` 页桥接卡 |
| `activation/module_class/device_key` | `platform_ports.module` | `server_context.py` 元数据透传 | `signals` 页元信息/确认面板 |

### 3.3 模块确认（module binding）

- `cloud/web/app.js:338-412`
  网页支持对可确认模块做“用户确认”。

- `cloud/app/api/web_routes.py:339-381`
  服务器提供 `/web/module-bindings/confirm` 把确认结果写入 `module_bindings` 存储。

这说明：

- 板端负责上报“真实观察到的端口/模块候选信息”
- 服务器负责保存“用户确认绑定”
- 网页负责把确认结果叠加显示到同一个端点卡片上

### 3.4 聊天与自然语言控制

- `cloud/app/api/web_routes.py:452-631`
  网页聊天 `POST /web/chat` 已经接入：
  - 对话历史
  - `signal_model`
  - `latest_device_state`
  - `diagnostics`
  - `module_bindings`
  - `web_hardware_agent`

- `cloud/web/app.js:759-777`
  前端聊天发送时会把当前 `device_id` 一并提交给服务器。

所以当前“自然语言 -> 硬件控制”的正式入口是网页，不是板端屏幕。

### 3.5 配网页面

- `cloud/web/app.js:944-1157`
  网页配网用的是 `Web Serial` 直连 `ESP32 USB`，支持：
  - `wifi.status`
  - `wifi.scan`
  - `wifi.set`
  - `wifi.clear`

- `esp32_s3_uart_link.ino:581-596`
  ESP32 也确实会向 USB 串口输出 `wifi.status` JSON。

这条链路是：

`网页浏览器 <-> Web Serial <-> ESP32 USB`

不是：

`网页 -> 云服务器 -> MQTT -> 设备`

## 4. 已确认的对齐点

### 4.1 已经对齐

1. `ports + samples + module metadata` 已成为板端、ESP32、服务器、网页共同使用的主状态模型。
2. `AHT20 / BH1750 / SG90 / UART-BRIDGE` 已经能从板端一路映射到网页 `signals` 视图。
3. 设备注册、设备切换、在线判断、聊天上下文，都已经与真实 `device_id` 体系对齐。
4. 服务器已经把 `activation / module_class / model_state / binding_source / device_key` 这一组字段接进 `signal_topology`，网页也会显示这些字段。

## 5. 已确认的偏差与缺口

### 5.1 板端 `PORTS` 页与云端真实拓扑不完全同构

- 板端 UI：`src/app_ui.c:1518-1534`
  会把 `BH1750` 逻辑上映射到 `I2C-2` 卡片。

- 云端真实状态：`src/platform_ports.c:368-385`、`esp32_s3_uart_link.ino:1400-1418`
  `i2c.s2` 仍然是 `reserved / empty / not_supported`。

结论：板端 `PORTS` 页是“人机展示视图”，云端 `signal_topology` 是“协议真值视图”。这两者当前不是 1:1 结构镜像。

### 5.2 板端本地设备没有全部上云

本地 UI/注册表里有：

- `ILI9488`
- `FT6336`
- 本地时钟
- 板端 WiFi 弹层

但网页/服务器当前主要消费的是标准口与模块，不会完整呈现这些本地 HMI 组件。

### 5.3 `BH1750` 已有实时状态，但服务器知识目录还没完整接住

- 板端/状态链路：已经有 `env.light.lux`
- 服务器实时拓扑：`server_context.py` 可以显示 `BH1750` 读数
- 但 `cloud/app/hardware_catalog.py` 当前没有 `BH1750` 目录项

这意味着：

- 网页 `signals` 页能看见 `BH1750`
- 但网页硬件 Agent 的“标准硬件知识目录”并没有把 `BH1750` 当成正式条目管理

### 5.4 `buzzer.active` 只打通到状态层，未完全打通到 Agent 能力层

- 板端 `platform_ports.c:573-574`、`586-595` 已暴露 `buzzer.active`
- ESP32 `status/telemetry` 也会透传该能力
- 但 `cloud/app/agent_service/web_hardware_tools.py:207-259` 的能力目录里只显式补了 `SG90`

结论：`buzzer.active` 当前更像“状态上已存在、网页可见，但控制侧未作为正式自然语言硬件能力建模”的半接入状态。

### 5.5 网页模块中文标签还不完整

- `cloud/web/app.js:436-447`
  `moduleClassLabel()` 当前只明确映射了：
  - `env.th`
  - `env.multi`
  - `act.servo`
  - `bridge.uart`
  - `reserved / none / unknown`

缺少：

- `env.light`
- `i2c.mux`
- `display.i2c`
- `storage.eeprom`
- `motion_time`

所以某些真实模块虽然已经能显示出来，但标题/标签会偏技术内部名。

### 5.6 板端自然语言入口当前未启用

- `hal_entry.c:219-221` 仍保留提交通道
- `app_ui.c:1659` 实际不提交输入

结论：当前“自然语言到规则程序”的正式入口是网页 `chat`，不是板端屏幕。

## 6. 建议把当前系统理解成三层

### 6.1 板端本地交互层

负责：

- LCD / Touch
- 本地页切换
- 本地 WiFi 选择弹层
- 本地时钟显示
- 设备列表和端口页的人机可视化

### 6.2 统一状态上报层

负责：

- `platform_ports`
- `samples`
- `activation/module_class/model_state/binding_source/device_key`
- `deploy_ack / execution_state`

这是当前真正的“板端事实来源”。

### 6.3 云端产品层

负责：

- `/web/context`
- `signal_topology`
- `module_bindings`
- `chat + web_hardware_agent`
- `Web Serial` 配网页

## 7. 这次核对后的最重要一句话

如果后续要继续把本工程能力往网页和服务器扩展，最应该坚持的基线是：

**以 `platform_ports + samples + module metadata` 作为唯一事实模型，板端 UI 允许有“展示视图重排”，但不要再让网页或服务器绕开这套模型重新发明一套硬件语义。**
