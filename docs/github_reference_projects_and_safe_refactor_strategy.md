# GitHub 参考项目与安全改造策略

## 目的

这份文档把当前工程最相关的 GitHub 参考项目、它们的操作方案、以及本工程可安全借鉴的部分整理出来。

目标不是“照抄参考项目”，而是明确：

- 哪些做法值得采用
- 哪些做法现在不能直接搬
- 后续代码修改的先后顺序
- 哪些步骤必须通过 e2 studio/FSP Configurator 完成

## 当前工程的约束

当前工程不是普通的 RA8P1 LVGL 演示，而是一个已经跑通真实链路的联调工程。后续改造必须优先保住这条基线：

`Cloud -> MQTT script -> ESP32 bridge -> RA8P1 screen update -> deploy_ack -> Cloud`

同时保住以下外部行为：

- `SCI0 / 115200 8N1` 的 ESP32 串口链路
- `req:` / `script:` / `cmd:` / `intent:` / `ack:req=...` 文本协议
- `screen_text` 对应的屏幕刷新与 `deploy_ack`
- `aht20:status=...;t=...;h=...;crc=...` 遥测格式
- 屏幕上的 `Request / Script / Cmd / ACK` 联调字段

因此，参考项目只能作为“实现方式参考”，不能直接替换现有工程结构。

## GitHub 参考项目

### 1. `lvgl/lv_port_renesas_ek_ra8p1`

仓库：

- [lvgl/lv_port_renesas_ek_ra8p1](https://github.com/lvgl/lv_port_renesas_ek_ra8p1)

它的操作方案：

- 用 e2 studio 导入整个工程，而不是手工拼接文件
- 显示、触摸、LVGL 配置优先通过 `configuration.xml` 和 FSP Configurator 管理
- 修改 FSP 配置后必须执行 `Generate Project Content`
- LVGL 运行在线程里，不是裸机 `superloop`
- 显示口不是手写 bit-bang SPI，而是通过 `RM_LVGL_PORT` 对接底层显示硬件
- 开启了更高性能显示路径，并显式处理缓存一致性
- 使用外部内存和更大的图形缓冲区

对本工程有价值的做法：

- `LVGL` 配置和底层外设配置应该尽量回归 FSP 生成路径，不要长期维持“手写 GPIO 模拟外设”
- 如果后面启用 `D-Cache`，必须像参考工程那样补缓存 clean/invalidate 处理
- 图形性能提升的正确方向是“更好的显示外设路径 + 更合理的 buffer + 缓存一致性”，不是只加任务或只开双核

为什么现在不能直接照搬：

- 这个参考工程面向 `EK-RA8P1` 官方板卡，显示接口、内存、触摸链路和本项目当前硬件并不一致
- 它默认接受“图形优先”的工程结构，本项目当前优先级是“云端脚本链路 + 串口 ACK 不退化”
- 直接迁移到它的 `RM_LVGL_PORT + FreeRTOS + 大缓冲` 架构，风险过高

### 2. `renesas/ra-fsp-examples`

仓库：

- [renesas/ra-fsp-examples](https://github.com/renesas/ra-fsp-examples)

它的操作方案：

- 所有例程按 `module` 分类组织
- 导入和运行方式依赖 FSP 版本与 e2 studio 版本匹配
- 官方建议先看 usage guide / readme，再按板卡和模块导入
- 例程的价值在于“单模块的正确打开方式”，例如 `SCI UART`、`SCI SPI`、`SCI I2C`、`GPT PWM`、`FreeRTOS`

对本工程有价值的做法：

- 后续替换 `软件 SPI`、`软件 I2C`、`忙等舵机脉冲` 时，应优先参考官方模块例程的初始化方式和中断/回调模型
- 外设替换应该一项一项进行，不要同时重做显示、触摸、传感器、双核、RTOS
- 如果后面上 `FreeRTOS`，应以官方例程的任务/中断协作习惯为准，而不是把现在的 5ms 轮询直接搬进多个任务

为什么现在不能直接照搬：

- 官方例程验证的是单模块功能，不负责保住本项目已有的 `Cloud -> MQTT -> ESP32 -> RA8P1 -> ACK` 联调闭环
- 例程可以重置初始化路径，但本工程不能轻易改串口协议、屏幕字段、或 ACK 时机

### 3. `renesas/fsp`

仓库：

- [renesas/fsp](https://github.com/renesas/fsp)

相关重点不是源代码本身，而是 GitHub release notes 里关于 `RA8P1` 的多核支持说明。

它的操作方案：

- `RA8P1` 双核工程不是在单工程里“随手开第二核”
- 官方推荐流程是：
  1. 创建 `CPU0` 项目
  2. 构建 `CPU0`
  3. 创建 `CPU1` 项目，并指定 preceding project
  4. 构建 `CPU1`
  5. 再创建 `Renesas FSP Solution Project`
  6. 用 solution 的 launch group 做多核调试
- `OFS` 设置只由 `CPU0` 写入
- 需要手工维护 linker 边界和 solution 级别配置

对本工程有价值的做法：

- 如果后面真要用双核，应该走 `CPU0 + CPU1 + Solution Project` 正规流程
- 双核迁移属于“新阶段工程动作”，不应在当前单工程里硬塞出一个伪双核结构

为什么现在不能直接照搬：

- 当前工程还处于单工程、单链路稳定化阶段
- 一旦切入 solution，多核调试、链接脚本、OFS、生成内容都会变复杂
- 在 `screen_text -> deploy_ack` smoke 还没有充分固化之前，直接做双核迁移不划算

## 当前工程与参考项目的关键差异

当前工程的主要性能瓶颈是这些：

- `LCD` 走手写 `GPIO` 软件 SPI
- `LVGL flush` 逐像素逐字节发送
- `AHT20` 走软件 I2C 且读数阻塞
- `SG90` 走忙等脉冲
- 主逻辑是裸机轮询
- `D-Cache` 关闭
- `SDRAM` 关闭

而参考项目/官方方案的共同点是这些：

- 优先用 FSP 生成的硬件外设 stack
- 显示链路尽量走专用显示/硬件串行路径
- 大 buffer 放外部内存
- 启用缓存后补一致性处理
- RTOS 或双核是在“外设路径正确之后”再引入

## 本工程的安全改造顺序

### 第 0 阶段：冻结基线

先不动协议，不动 cloud topic，不动 ACK 格式，不动 UI 联调字段。

### 第 1 阶段：仅做不改变外部行为的内部替换

推荐顺序：

1. 舵机从软件忙等脉冲改为 `GPT PWM`
2. `AHT20` 从软件 I2C 改为硬件 I2C
3. `LCD` 从软件 SPI 改为硬件 SPI

这一阶段要求：

- 命令词、串口协议、UI 文本字段、ACK 时机保持不变
- 每做一项替换，都要能回归 `screen_text -> deploy_ack`

### 第 2 阶段：缓存与 buffer 优化

推荐顺序：

1. 启用 `D-Cache`
2. 补显示 buffer / DMA / 共享缓冲区的 cache 维护
3. 视需要启用更大的 LVGL draw buffer

这一阶段的关键不是“开开关”，而是验证没有引入缓存一致性 bug。

### 第 3 阶段：启用外部内存

适合放进去的内容：

- LVGL draw buffer
- 字体和较大的 UI 资源
- 日志缓冲

不建议一开始就把关键协议状态和频繁访问的小对象都扔进外部内存。

### 第 4 阶段：RTOS

建议先只在当前主核引入最小任务集：

- `ui_task`
- `uart_link_task`
- `sensor_task`
- `rule_task`

这个阶段仍然不建议马上切双核。

### 第 5 阶段：双核

只有在下面三点都成立后，才建议启动：

- 单核硬件外设路径已经稳定
- smoke 回归足够可靠
- 任务边界已经清晰

建议分工：

- `CPU0 / M85`：UI、LVGL、协议解析、较重逻辑
- `CPU1 / M33`：传感器采样、舵机/IO 执行、周期任务、看门狗

## 需要在 e2 studio 里完成的动作

下面这些动作我不能仅靠手改源码完成，必须你在 e2 studio/FSP Configurator 里配合：

### 必须由 e2 studio 完成

- 新增或修改 FSP stacks
- 改管脚复用
- 改 `BSP` 级别 `D-Cache` / `SDRAM` 配置
- 生成 `ra_gen/*` 和 `ra_cfg/*`
- 以后如果切双核，创建 `CPU1` 工程和 `Solution Project`

### 我建议的配合方式

后面每次需要你操作时，我会直接给你一份非常短的步骤单，格式固定成：

1. 打开什么页面
2. 改哪几个选项
3. 点哪里生成
4. 生成后把哪些文件交还给我继续改

## 当前建议

按安全性排序，下一步最合理的不是立刻上双核或 RTOS，而是：

1. 先保住当前 smoke 基线
2. 优先把 `软件外设` 改成 `FSP 硬件外设`
3. 再考虑 `D-Cache`
4. 最后才是 `RTOS / 双核`

如果要开始真正动代码，第一刀建议放在：

- 舵机 `SG90` 的 `GPT PWM` 迁移准备

原因：

- 它局部、边界清晰
- 能直接消除忙等
- 对 `screen_text -> deploy_ack` 主链影响最小
- 即使回退也容易
