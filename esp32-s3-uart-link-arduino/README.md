# ESP32-S3 UART + MQTT Bridge

## 作用

这份 Arduino 工程是当前项目 `RA8P1_Viewing_Screen_ESP32_Link` 的配套 ESP32 固件。

入口文件：

- [esp32_s3_uart_link.ino](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/esp32-s3-uart-link-arduino/esp32_s3_uart_link/esp32_s3_uart_link.ino)

它现在不是最小 `ping/pong` 对端，而是完整桥接这几条链路：

- `RA8P1 <-> ESP32 UART`
- `ESP32 -> WiFi`
- `ESP32 -> MQTT`
- `Cloud deploy -> RA8P1 screen_text -> deploy_ack`
- `AHT20 sample -> MQTT status / telemetry`

## 默认参数

- 板型：`ESP32S3 Dev Module`
- 板间 UART：`UART1`
- 波特率：`115200`
- `TX = GPIO43`
- `RX = GPIO44`
- 已知 WiFi 列表：`YOUR_WIFI_SSID`
- MQTT Broker：`<cloud-server-ip>:1883`
- Device ID：首次启动使用 `ra8p1_demo_001` 兜底；收到 RA8P1 UID 并完成云端注册后，会保存云端分配的动态 `device_id`

## 接线

- `ESP32 RX(GPIO44) <- RA8P1 P603`
- `ESP32 TX(GPIO43) -> RA8P1 P602`
- `ESP32 GND <-> RA8P1 GND`

## UART 协议摘要

ESP32 发给 RA8P1：

- `esp32-ready`
- `esp32-heartbeat`
- `wifi:connected/disconnected`
- `wifi-ssid:<ssid-or-->`
- `mqtt:connected/disconnected`
- `req:<request_id>`
- `script:<script_id>`
- `cmd:<display_text>`
- `intent:<intent_type>`

RA8P1 发给 ESP32：

- `ping`
- `ra8p1_uid:<32-hex-uid>`
- `ack:req=...;script=...;code=0;msg=accepted`
- `aht20:status=online;t=26.4;h=50.3;crc=1`
- `aht20:status=offline`

协议约束：

- `request_id` / `script_id` 当前最大建议长度为 `63` 个字符，超过后需要先扩大 RA8P1/ESP32 UART 行缓冲。

## 设备注册与 MQTT 主题

- RA8P1 上电后通过 UART 发送 `ra8p1_uid:<32-hex-uid>`。
- ESP32 组合 `ra8p1_uid + esp32_mac + esp32_chip_id` 请求 `POST /api/devices/register`。
- 云端返回 `device_id` 和 `device_secret`；ESP32 将它们保存到 NVS。
- 后续 MQTT 主题按云端分配的 `device_id` 生成：
  - `cloudbridge/{device_id}/status`
  - `cloudbridge/{device_id}/telemetry`
  - `cloudbridge/{device_id}/event`
  - `cloudbridge/{device_id}/script`

## 构建产物

- [esp32_s3_uart_link.ino.merged.bin](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/esp32-s3-uart-link-arduino/esp32_s3_uart_link/build/esp32.esp32.esp32s3/esp32_s3_uart_link.ino.merged.bin)

## 里程碑目标

这份固件对应的目标状态是：

- 屏幕显示 `WiFi: connected` / `MQTT: connected`
- 屏幕显示 `AHT20: online` 和实时 `T/H`
- 屏幕 `Last TX` 只显示摘要，如 `aht20 sample`
- 云端 `status` 和 `telemetry` 能看到 `payload.aht20`
- 云端 `screen text ...` 下发后，RA8P1 屏幕显示 `Cmd: ...` 且回 `deploy_ack`

## 当前 WiFi 行为

- ESP32 上电后会优先读取 Flash/NVS 中保存的网页配网 SSID 和密码
- 如果没有保存过网页配网信息，ESP32 会扫描附近可见网络
- 如果扫描结果里存在已知 SSID，就优先连接信号更强的那个
- 当前内置兜底网络有：
  - `YOUR_WIFI_SSID`
- 如果当前没扫到任何已知网络，会回退尝试列表中的第一个配置

## USB 网页配网

网页的“设备配网”页面通过浏览器 Web Serial 直接连接 ESP32 USB 串口，WiFi 密码不会经过云端。

测试步骤：

1. 用数据线连接 ESP32。
2. 打开云端网页，进入“设备配网”。
3. 点击“连接 USB”，选择 ESP32 对应串口。
4. 可先点“扫描”确认热点可见。
5. 输入 SSID 和密码，点击“写入并连接”。
6. 等待状态显示 `WiFi 已连接`，再回到“信号通道”确认设备恢复在线。

USB 串口 JSON-lines 命令：

- `{"type":"wifi.status"}`
- `{"type":"wifi.scan"}`
- `{"type":"wifi.set","ssid":"...","password":"..."}`
- `{"type":"wifi.clear"}`
