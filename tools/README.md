# 工具说明

## 当前可用工具

- `build_esp32_bridge.ps1`
  - 使用当前工作区内置的 `.tools/arduino-cli/arduino-cli.exe`
  - 重新编译 `esp32_s3_uart_link.ino`
  - 输出目录固定到 `esp32-s3-uart-link-arduino/esp32_s3_uart_link/build/esp32.esp32.esp32s3/`

- `validate_threshold_loop.py`
  - 通过 SSH 连接云端服务器
  - 在服务器本机调用 `127.0.0.1:8000`
  - 真实下发一次 `threshold_control`
  - 回查 `deploy_ack`、`script_state`、`execution_state` 和温度值

- `validate_rule_program_loop.py`
  - 通过 SSH 连接云端服务器
  - 真实下发一次 `rule_program`
  - 回查 `deploy_ack`、`script_state`、`last_execution` 和事件证据链

- `validate_delivery_baseline.py`
  - 顺序跑完 `rule_program + threshold_control`
  - 自动等待 `rule_program` 冷却窗口，避免立刻覆盖板端状态
  - 输出单份交付基线 JSON 结果，可直接落盘保存

## 常用命令

### 重新编译 ESP32 bridge

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
.\tools\build_esp32_bridge.ps1
```

### 复测真实阈值闭环

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
python .\tools\validate_threshold_loop.py --json
```

### 复测真实 rule_program 闭环

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
python .\tools\validate_rule_program_loop.py --json --text "当温度到25度时，舵机来回旋转两次" --expected-threshold 25 --wait-seconds 20
```

### 一键复测最终交付基线

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
python .\tools\validate_delivery_baseline.py --json --report-file .\tools\last_delivery_baseline.json
```

注意：

- 当前验证脚本会自动生成短 `request_id`
- 如果手动传 `--request-id`，请控制在 `63` 个字符以内
- `validate_delivery_baseline.py` 会默认先跑 `rule_program`，再等待冷却后跑 `threshold_control`
