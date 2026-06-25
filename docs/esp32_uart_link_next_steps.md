# ESP32 UART Link Current Status

## 当前结论

当前工程 `D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link` 已经完成以下整合：

- LCD 显示链路可工作
- LVGL 状态 UI 可显示
- `RA8P1 <-> ESP32` UART 链路可工作
- `ESP32 -> WiFi -> MQTT` 云端桥接可工作
- `Cloud -> MQTT -> ESP32 -> RA8P1 -> ACK -> Cloud` 可复测
- `AHT20 -> RA8P1 -> UART -> ESP32 -> MQTT` 可复测

这份文档不再是“待办清单”，而是当前工程的**联调基线与复测清单**。

## 关键代码入口

- [hal_entry.c](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/src/hal_entry.c)
  裸机入口
- [esp32_link.c](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/src/esp32_link.c)
  UART 链路状态机
- [app_ui.c](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/src/app_ui.c)
  屏幕上的联调状态显示
- [hal_data.c](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra_gen/hal_data.c)
  FSP 生成的 `g_uart_esp32` 实例

## 当前 RA8P1 UART 基线

- 实例名：`g_uart_esp32`
- 外设：`SCI0`
- Channel：`0`
- 波特率：`115200`
- 数据格式：`8N1`
- 回调：`esp32_uart_callback`
- 引脚：
  - `P603 = SCI0_TXD0`
  - `P602 = SCI0_RXD0`

当前工程里 FSP UART 已经存在，不再是“需要后补的栈”。

## 当前 ESP32 固件基线

配套固件目录：

- [esp32-s3-uart-link-arduino](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/esp32-s3-uart-link-arduino)

入口文件：

- [esp32_s3_uart_link.ino](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/esp32-s3-uart-link-arduino/esp32_s3_uart_link/esp32_s3_uart_link.ino)

默认参数：

- 板型：`ESP32S3 Dev Module`
- 串口：`UART1`
- 波特率：`115200`
- `TX = GPIO43`
- `RX = GPIO44`

## 接线基线

- `RA8P1 P603 -> ESP32 RX(GPIO44)`
- `RA8P1 P602 <- ESP32 TX(GPIO43)`
- `GND <-> GND`

只接三线：

- `TX`
- `RX`
- `GND`

不需要 `RTS/CTS`。

## 当前屏幕状态说明

上电并运行正常时，屏幕状态区应出现类似内容：

```text
即插即用平台
ESP32: online
WiFi: connected
MQTT: connected
AHT20: online
T/H: xx.xC yy.y%
Request: ...
Script: ...
Cmd: ...
ACK: accepted
```

关键状态含义：

- `waiting`
  RA8P1 已经打开 UART，但还没收到完整在线状态
- `online`
  已经收到 `pong` 或心跳，UART 链路在线
- `timeout`
  之前在线，后续在超时时间内没有再收到消息
- `uart error`
  UART 收到驱动层错误事件

## 当前协议行为

RA8P1 侧：

- 启动后发送：
  - `ra8p1-uart-link-boot`
  - `ra8p1-ready`
  - `ping`
- 周期发送：
  - `ping`
- 传感器上报：
  - `aht20:status=online;t=...;h=...;crc=...`
  - `aht20:status=offline`
- 收到云端转发后的 `intent:` 时回：
  - `ack:req=...;script=...;code=0;msg=accepted`

ESP32 侧：

- 启动时主动发送一次：
  - `esp32-ready`
- 收到 `ping` 时回复：
  - `pong`
- WiFi / MQTT 状态变化时发送：
  - `wifi:connected/disconnected`
  - `mqtt:connected/disconnected`
- 收到云端 `script` topic 后转发：
  - `req:<request_id>`
  - `script:<script_id>`
  - `cmd:<screen_text>`
  - `intent:<intent_type>`
- 收到 RA8P1 ACK 后发布：
  - MQTT `event` / `deploy_ack`

因此当前最小真实闭环是：

1. ESP32 上电发 `esp32-ready`
2. RA8P1 收到后建立 UART 在线状态
3. ESP32 连上 WiFi / MQTT，并把状态同步到 RA8P1 屏幕
4. Cloud 向 `cloudbridge/{device_id}/script` 下发脚本
5. ESP32 提取 `request_id / script_id / intent_type / lua_code`
6. ESP32 通过 UART 转发 `req: / script: / cmd: / intent:`
7. RA8P1 更新屏幕并回 `ack:req=...;script=...;code=0;msg=accepted`
8. ESP32 把 `deploy_ack` 发布回云端 `event`

当前 `request_id` / `script_id` 端到端建议不超过 `63` 个字符；RA8P1 与 ESP32 侧 ID 缓冲均按 64 字节级别配置。

当前工程加入了“单飞心跳”保护：

- 任一时刻只允许一个未应答的 `ping` 在路上
- 如果上一个 `pong` 还没回来，RA8P1 不会继续发新的 `ping`
- 只有收到这个 `ping` 对应的 `pong` 后，`RX Count` 和 `TX Count` 才会同时加 `1`

因此当前屏幕上的 `RX Count` / `TX Count` 不再表示“所有原始行数”，而是表示：

- 成功完成了多少次 `ping -> pong` 对称闭环

这样做的目的，是让你在屏幕上更容易直接观察数字是否同步流动。

## 当前云端桥接基线

- MQTT Broker：`<cloud-server-ip>:1883`
- Device ID：`ra8p1_demo_001`
- Topic：
  - `cloudbridge/ra8p1_demo_001/status`
  - `cloudbridge/ra8p1_demo_001/telemetry`
  - `cloudbridge/ra8p1_demo_001/event`
  - `cloudbridge/ra8p1_demo_001/script`

当前 ESP32 固件承担的是：

- WiFi 自动重连
- MQTT 自动重连
- `status` / `telemetry` 周期发布
- `script` 订阅
- `deploy_ack` 事件上报
- 从 `lua_code` 中提取 `screen_text(...)` / `print(...)` 给 RA8P1 屏幕展示

## 本次修复后的配置前提

当前工程已经恢复以下关键 BSP / FSP 前提：

- `C runtime init = enabled`
- `main_osc_populated = enabled`
- `subclock_populated = enabled`
- 时钟稳定相关延时已启用

根因详情见：

- [ra8p1_esp32_link_failure_root_cause_summary.md](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/docs/ra8p1_esp32_link_failure_root_cause_summary.md)

## 复测步骤

1. 烧录 RA8P1 当前工程输出：
   - [RA8P1_Viewing_Screen_ESP32_Link.srec](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/Debug/RA8P1_Viewing_Screen_ESP32_Link.srec)
2. 烧录 ESP32 固件：
   - [esp32_s3_uart_link.ino](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/esp32-s3-uart-link-arduino/esp32_s3_uart_link/esp32_s3_uart_link.ino)
3. 按接线基线连接
4. 打开 ESP32 USB 串口监视器，波特率 `115200`
5. 观察 RA8P1 屏幕与 ESP32 串口输出

## 预期现象

RA8P1 屏幕：

- `ESP32: online`
- `WiFi: connected`
- `MQTT: connected`
- `AHT20: online`
- `T/H: xx.xC yy.y%`
- `ACK: accepted`（触发下发后）

ESP32 串口监视器：

```text
esp32-ready
ra8p1-uart-link-boot
ra8p1-ready
tx:pong
```

后续还会持续看到：

- RA8P1 发来的 `ping`
- ESP32 回发 `tx:pong`
- WiFi / MQTT 状态行
- `req:` / `script:` / `cmd:` / `intent:`
- `ack:req=...;script=...;code=0;msg=accepted`

## 备注

旧版本这份文档曾写着“当前工程还没有生成 FSP UART stack”。  
这已经不符合当前代码状态，现已更新为当前可运行基线说明。

另外，旧版本如果仍把当前工程描述为“只有 LCD + UART”，也已经不再符合真实状态。  
当前应以 `Cloud + MQTT + ACK + AHT20` 联调基线来理解该工程。
