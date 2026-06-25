# 在线编译调试复现手册（Agent 版）

更新时间：2026-05-31

## 1. 这份手册解决什么问题

这份手册不是单纯讲“怎么编译一个工程”，而是讲如何把下面这整条链路复现在另一台电脑、并交给另一个 agent 执行：

```text
本地代码修改
-> 本地编译
-> 烧录 RA8P1 / ESP32
-> 云端服务联调
-> MQTT 下发
-> 板端执行
-> 回查 ACK / status / execution_state
```

本手册的目标是让另一个 agent 在没有上下文记忆的情况下，也能按固定流程完成：

- 编译
- 烧录
- 验收
- 定位失败点

## 2. 关键认知

这里的“在线编译调试”本质上不是远程 IDE 单步调试，而是一个脚本化、分层验证的闭环：

1. 本地 Windows 机器负责编译和烧录
2. 阿里云服务器负责运行 FastAPI、MQTT、日志和设备状态接口
3. ESP32 是唯一网络桥
4. RA8P1 负责本地执行
5. 最终是否成功，不靠“感觉”，而靠状态接口和事件证据链判断

也就是说，这个能力可复制的关键不是某个 IDE 按钮，而是：

- 明确的目录约定
- 固定的命令顺序
- 可验证的输出
- 出错时能快速判断是哪一层坏了

## 3. 最小架构

```text
另一台电脑
  -> PowerShell / Python / make / J-Link / arduino-cli
  -> 修改代码
  -> 编译 RA8P1
  -> 编译 ESP32 bridge
  -> 烧录到板子

云端服务器
  -> nginx
  -> FastAPI
  -> Mosquitto
  -> 设备状态 / 部署日志

真实硬件
  -> ESP32-S3
  -> RA8P1
  -> AHT20
  -> SG90
```

## 4. 目录与变量约定

为了让流程可迁移，不要把路径硬编码在 agent 的描述里。先定义变量，再把变量替换到命令中。

### 4.1 当前项目默认值

```text
RA8P1 工作区: D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
主项目: D:\Embedded-agent
RA8P1 构建目录: D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link\Debug
ESP32 sketch: D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link\esp32-s3-uart-link-arduino\esp32_s3_uart_link
ESP32 产物目录: D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link\esp32-s3-uart-link-arduino\esp32_s3_uart_link\build\esp32.esp32.esp32s3
云端项目根目录: /home/admin/embedded-agent
SSH 私钥: D:\Embedded-agent\codex_aliyun_ed25519
公网地址: <cloud-server-ip>
默认 device_id: ra8p1_demo_001
```

### 4.2 在别的电脑上必须重新确认的变量

- `WORKSPACE_ROOT`
- `MAIN_PROJECT_ROOT`
- `JLINK_EXE`
- `ARDUINO_CLI_EXE`
- `SSH_KEY_PATH`
- `SERVER_HOST`
- `SERVER_USER`
- `DEVICE_ID`
- `ESP32_UPLOAD_PORT`

## 5. 先决条件

另一台电脑上至少要具备：

- Windows PowerShell
- Python 3
- `make`
- ARM GCC 工具链
- J-Link Commander
- Arduino CLI
- 能访问公网服务器
- 能访问真实板子 USB/J-Link

真实板子侧至少要具备：

- RA8P1 已连接 J-Link
- ESP32 可通过 USB 烧录
- AHT20 在线
- SG90 已接好
- 板子供电正常

云端至少要具备：

- `http://<cloud-server-ip>/health` 可访问
- FastAPI 服务活着
- Mosquitto 正常
- API token 可用

## 6. agent 必须遵守的执行顺序

另一个 agent 不要自由发挥，必须按下面顺序执行。

### 6.1 第一步：确认当前层级状态

先判断不是所有层一起坏了。

最少检查：

```powershell
Invoke-WebRequest http://<cloud-server-ip>/health
```

如果云端健康检查失败，不要立刻烧录，不要误判成固件问题。

### 6.2 第二步：本地代码测试

云端代码修改后先跑测试：

```powershell
cd D:\Embedded-agent
.\.venv\Scripts\python.exe -m pytest cloud\tests
```

通过标准：

- 全部测试通过

### 6.3 第三步：编译 ESP32

固定使用工作区内置脚本：

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
.\tools\build_esp32_bridge.ps1
```

通过标准：

- 生成 `esp32_s3_uart_link.ino.merged.bin`
- 没有 compile error

### 6.4 第四步：编译 RA8P1

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
make -C Debug -j4 all
```

通过标准：

- 生成 `Debug\RA8P1_Viewing_Screen_ESP32_Link.elf`
- 生成 `Debug\RA8P1_Viewing_Screen_ESP32_Link.srec`

### 6.5 第五步：烧录 RA8P1

推荐非交互命令方式，不依赖 IDE 按钮：

J-Link 脚本示例：

```text
device R7KA8P1KF_CPU0
si SWD
speed 4000
connect
r
h
loadfile D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/Debug/RA8P1_Viewing_Screen_ESP32_Link.elf
r
g
exit
```

执行方式：

```powershell
& 'D:\Renseas-RFPV3\JLink_V916a\JLink.exe' `
  -device R7KA8P1KF_CPU0 `
  -if SWD `
  -speed 4000 `
  -CommanderScript 'D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link\Debug\codex_flash_ra8p1_runtime.jlink'
```

通过标准：

- `loadfile ... O.K.`
- 没有 flash download error

### 6.6 第六步：烧录 ESP32

如果自动上传端口可用：

```powershell
& '.\.tools\arduino-cli\arduino-cli.exe' upload `
  -p COMx `
  --fqbn esp32:esp32:esp32s3 `
  --input-dir '.\esp32-s3-uart-link-arduino\esp32_s3_uart_link\build\esp32.esp32.esp32s3' `
  '.\esp32-s3-uart-link-arduino\esp32_s3_uart_link'
```

如果端口不稳定，直接让人工用下面文件手动烧：

- `esp32_s3_uart_link.ino.merged.bin`

通过标准：

- ESP32 成功重启
- 云端状态接口能看到设备重新上线

### 6.7 第七步：先做兼容回归

不要一上来测新功能，先验证旧链路没坏。

旧阈值链路验证：

- 高阈值应进入 `ARMED`
- 低阈值应进入 `TRIGGERED`

判断证据来自：

- `/agent/deploy`
- `/devices/{device_id}/state`
- `/devices/{device_id}/events`

### 6.8 第八步：再测新链路

当前新阶段是结构化 `rule_program`。

正确顺序：

1. 先发一个高阈值计划
2. 期待进入 `ARMED`
3. 再发一个低阈值计划
4. 期待 `TRIGGERED -> DONE`

如果云端 HTTP 新接口已部署，用：

- `/agent/program/interpret`
- `/agent/program/deploy`
- `/agent/program/interpret/deploy`

如果云端 HTTP 还没部署，但 MQTT 正常，可以临时直接发 `deploy_script(rule_program)` 到：

```text
cloudbridge/{device_id}/script
```

## 7. 成功判据

### 7.1 旧链路成功

至少满足：

- `ack_received = true`
- `device_last_request_id` 等于本次请求
- `script_state = ARMED` 或 `TRIGGERED`
- `last_event.type = execution_state`

### 7.2 新 `rule_program` 链路成功

至少满足：

- `last_intent_type = rule_program`
- 高阈值计划进入 `ARMED`
- 低阈值计划进入 `TRIGGERED`
- 随后进入 `DONE`
- `last_execution.reason = PROGRAM_DONE`
- `last_execution.action = SG90`
- `last_execution.angle = 90`

## 8. 失败定位矩阵

### 8.1 云端健康检查失败

优先怀疑：

- nginx
- FastAPI
- 服务器网络

不要先怀疑板子。

### 8.2 云端健康检查正常，但没有新接口

优先怀疑：

- 服务器代码未同步
- systemd 服务未重启
- SSH 不通导致发布失败

### 8.3 MQTT 发布成功，但设备状态不更新

优先怀疑：

- ESP32 没刷新固件
- 板子没连上 MQTT
- UART 桥异常

### 8.4 设备状态更新了，但 `last_intent_type` 不是 `rule_program`

优先怀疑：

- ESP32 仍在跑旧桥接固件
- 发布 payload 没带 `rule_program`

### 8.5 `rule_program` 进入 `ARMED` 但不触发

优先怀疑：

- 阈值高于当前温度
- AHT20 数据没刷新
- 冷却时间还没结束

### 8.6 能触发但不进入 `DONE`

优先怀疑：

- RA8P1 序列执行逻辑异常
- SG90 时序问题
- 板端状态上报漏掉结束事件

## 9. 给别的 agent 的固定操作协议

如果把任务交给另一个 agent，建议直接给它以下规则：

### 9.1 它必须先做

- 读取本手册
- 先做健康检查
- 先跑本地测试
- 先编译，再烧录，再验收

### 9.2 它不能跳过

- 不能跳过兼容回归
- 不能只看编译成功就宣称完成
- 不能只看屏幕或串口现象，不看云端证据链

### 9.3 它必须输出

- 用了哪些命令
- 编译产物位置
- 烧录是否成功
- 当前云端接口是否已更新
- 最终成功证据
- 如果失败，失败层级在哪一层

## 10. 最小可复现命令集

### 云端测试

```powershell
cd D:\Embedded-agent
.\.venv\Scripts\python.exe -m pytest cloud\tests
```

### ESP32 编译

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
.\tools\build_esp32_bridge.ps1
```

### RA8P1 编译

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
make -C Debug -j4 all
```

### 旧阈值闭环验收

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
python .\tools\validate_threshold_loop.py --json
```

### 新 `rule_program` 验收

```powershell
cd D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link
python .\tools\validate_rule_program_loop.py --json
```

注意：

- 当前 `validate_rule_program_loop.py` 依赖云端已经暴露 `/agent/program/interpret/deploy`
- 如果服务器还没更新，而 MQTT 仍可用，可临时改用直接 MQTT 发布法

## 11. 当前已知限制

- 当前服务器不是 Git 工作流，而是文件覆盖式部署
- 当前 `request_id` 仍然建议短于 `31` 个字符
- 当前公网 SSH 可能间歇性不可用
- 当前真正“官方上线”的新阶段，仍取决于服务器代码同步成功

## 12. 推荐在另一台电脑上先做的准备

1. 把本地路径整理成和本手册一致的变量形式
2. 配好 Python、make、J-Link、arduino-cli
3. 验证能访问 `http://<cloud-server-ip>/health`
4. 验证能读取 API token
5. 验证 RA8P1 和 ESP32 端口都能被系统识别
6. 先跑一次“只编译不烧录”
7. 再跑一次“只兼容回归”
8. 最后再上 `rule_program`

## 13. 一句话总结

把这项能力迁移给另一台电脑或另一个 agent，关键不是复制某个 IDE，而是复制这四件事：

- 固定环境变量
- 固定命令顺序
- 固定成功判据
- 固定失败定位方法

只要这四件事被文档化，agent 就能稳定复现这套“在线编译调试”能力。
