# RA8P1 与 ESP32 链路失败根因总结

## 1. 结论

本项目最初不能跑通 `RA8P1 <-> ESP32` 链路，**根因不是 UART 引脚、波特率或 ESP32 固件本身错误**，而是：

- 当前工程从屏幕工程派生后，`BSP / FSP` 的**启动与时钟前提配置被改坏**
- 导致当前工程虽然表面上已经有 `SCI0 / 115200 / P602-P603` 的 UART 配置，但**运行时基础环境并不等同于参考工程**
- 在这种前提下，`LVGL + esp32_link` 里的静态全局状态、时钟初始化、引脚保护与外部晶振相关行为都可能失真，最终表现为链路无法正常建立

参考工程：

- `D:\Renesas-Workspace\CPKHMI_RA8P1_ESP32`

当前工程：

- `D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link`

## 2. 直接现象

对比参考工程后发现：

- 两边 UART 实例都叫 `g_uart_esp32`
- 两边都是 `SCI0`
- 两边都是 `115200 8N1`
- 两边都使用 `P602 = RXD0`、`P603 = TXD0`
- ESP32 固件协议也一致，仍然是 `ping -> pong`

因此“链路不通”不能用“串口参数抄错”来解释。

## 3. 根因拆解

### 3.1 C 运行时初始化被关闭

当前工程中：

- [bsp_cfg.h](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra_cfg/fsp_cfg/bsp/bsp_cfg.h:38)
  - `BSP_CFG_C_RUNTIME_INIT ((1))` 是修复后的状态

在修复前，这个配置是关闭的。

这意味着：

- `.bss` 不保证被清零
- `.data` 不保证从 ROM 正确拷贝到 RAM
- 依赖静态全局状态的模块可能在错误初值下运行

而当前工程的链路逻辑不是参考工程的最小裸 UART 逻辑，而是：

- `LVGL`
- `app_ui`
- `esp32_link`
- 多个静态全局队列、计数器、状态位

只要 `C runtime init` 被关掉，这些状态机就可能从随机状态起步，链路自然不稳定甚至完全不通。

这是本次问题的**第一根因**。

### 3.2 主晶振/子时钟装配状态与时钟树设置矛盾

当前工程修复后的关键配置在：

- [configuration.xml](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/configuration.xml:292)
- [configuration.xml](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/configuration.xml:297)

修复前的问题是：

- `main_osc_populated = disabled`
- `subclock_populated = disabled`

但同一个工程里又配置了：

- 主时钟依赖外部晶振
- `SCICLK` 仍然走 `PLL2R`

这会造成一个板级矛盾：

- 工程在逻辑上要求使用外部晶振和对应 PLL 时钟树
- 但 BSP 又声明这些振荡源“不存在”

结果就是：

- 时钟初始化路径与参考工程不同
- SCI 波特率赖以成立的时钟前提不再可靠

这是本次问题的**第二根因**。

### 3.3 启动保护与时钟保护延时被关掉

当前工程修复后的关键配置在：

- [configuration.xml](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/configuration.xml:78)
- [bsp_mcu_family_cfg.h](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra_cfg/fsp_cfg/bsp/bsp_mcu_family_cfg.h:43)

修复前被关闭的内容包括：

- `clock_settling_delay`
- `sleep_mode_delays`
- `mstp_change_delays`
- `PFS protect`

这些项单独看未必一定导致链路失败，但在当前工程这种“显示 + LVGL + UART 混合”的场景里，会放大启动阶段的不确定性。

它们更像是**促发问题和放大问题的条件**。

### 3.4 当前工程已经不是参考工程的板级基线

参考工程文档写得很明确：

- [ra8p1-esp32-porting-notes.md](/D:/Renesas-Workspace/CPKHMI_RA8P1_ESP32/ra8p1-esp32-porting-notes.md:45)

其中明确区分：

- `src/*.c` 是业务逻辑
- `ra_gen/*`、`ra_cfg/*`、`configuration.xml` 是板级/FSP 配置产物

并且明确提示：

- 换板或换工程时，不要机械复制生成产物

当前项目并不是参考工程原样延续，而是一个屏幕工程派生体。  
因此它即使“把 UART 配上了”，也不代表它已经满足参考工程那条链路赖以成立的启动前提。

### 3.5 为什么“刚烧录完能亮”，但“断电再上电会黑屏”

这次还有一个容易误判的现象：

- 烧录完固件后，屏幕可以点亮
- 但断电后重新上电，屏幕反而黑屏

这个现象说明问题**不太像 LCD 初始化指令本身写错**，更像是：

- 冷启动路径不稳定
- 调试/烧录后的启动路径暂时把问题掩盖了

从代码上看，LCD 驱动本身每次都会重新执行完整初始化，而不是“只在烧录后才初始化一次”：

- [lcd_spi.c](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/src/lcd_spi.c:66)

这里会重新做：

- LCD 复位脚拉低/拉高
- 初始化延时
- `sleep out`
- `display on`

也就是说，只要 MCU 能稳定走到 `lcd_init()`，LCD 本身是有机会被重新点亮的。

真正的差异在 MCU 启动前半段：

- [system.c](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/fsp/src/bsp/cmsis/Device/RENESAS/Source/system.c:295)
- [system.c](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/fsp/src/bsp/cmsis/Device/RENESAS/Source/system.c:372)
- [bsp_clocks.c](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/fsp/src/bsp/mcu/all/bsp_clocks.c:78)

在进入 [hal_entry.c](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/src/hal_entry.c:11) 之前，RA8P1 先要完成：

- 时钟初始化
- C 运行时初始化
- WarmStart / BSP 启动流程

修复前这些前提被改坏后，就会出现：

- 冷上电时，系统真的按错误的振荡器/运行时配置启动
- 烧录后直接运行时，调试器复位、装载、启动的过程可能让部分状态暂时落在“刚好能跑”的区间

因此“烧录后亮、断电后黑”的根因，和 UART 链路失败是同一类问题：

- 不是 LCD 驱动单独有特殊魔法
- 而是 `BSP / FSP` 冷启动基线不正确

这也是为什么本次修复 `C runtime init`、晶振装配状态、启动延时和 RA 模板启动序列后，屏幕和 UART 链路一起恢复正常。

## 4. 不是根因的项

以下内容经过对比，**不是这次失败的主因**：

- UART 通道号不是问题：两边都是 `SCI0`
- UART 波特率不是问题：两边都是 `115200`
- 数据格式不是问题：两边都是 `8N1`
- UART 回调不是问题：都使用 `esp32_uart_callback`
- 物理引脚映射不是问题：都使用 `P602/P603`
- ESP32 协议不是问题：参考工程固件仍然是 `ping -> pong`

## 5. 本次修复动作

本次为了恢复参考工程可运行语义，做了以下对齐：

- 启用 `BSP_CFG_C_RUNTIME_INIT`
- 启用 `BSP_CFG_PFS_PROTECT`
- 启用 `BSP_CLOCK_CFG_MAIN_OSC_POPULATED`
- 启用 `BSP_CLOCK_CFG_SUBCLOCK_POPULATED`
- 启用时钟稳定相关延时项
- 在 `hal_entry()` 前部补回 RA 模板启动序列

对应文件：

- [bsp_cfg.h](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra_cfg/fsp_cfg/bsp/bsp_cfg.h:36)
- [bsp_mcu_family_cfg.h](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra_cfg/fsp_cfg/bsp/bsp_mcu_family_cfg.h:43)
- [configuration.xml](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/configuration.xml:78)
- [hal_entry.c](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/src/hal_entry.c:11)

## 6. 为什么修复后可以跑通

修复后，当前工程重新满足了三件事：

1. 全局/静态状态能按预期初始化
2. 时钟树与“外部 24 MHz 晶振 + SCICLK”假设重新一致
3. 启动阶段的保护和延时行为恢复到参考工程可运行区间

这样一来：

- `esp32_link.c` 的状态机可以从确定初值启动
- `SCI0` 的波特率计算和运行时钟前提恢复一致
- `LVGL + UI + UART` 组合不再建立在错误的 BSP 启动基线上
- LCD 初始化也能够在正常冷启动路径下稳定执行

链路因此恢复正常。

## 7. 额外发现

当前工程原有说明文档：

- [esp32_uart_link_next_steps.md](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/docs/esp32_uart_link_next_steps.md:22)

其中写着“当前工程还没有生成 FSP UART stack”。  
但实际代码里 `g_uart_esp32` 已经存在，这份文档已经过时，容易误导排查方向。

## 8. 后续避免方式

后续如果再把这条链路移植到别的 RA8P1 工程，建议遵守下面原则：

1. 不要只拷贝 `src` 里的 UART 逻辑，同时要核对 `ra_cfg`、`ra_gen`、`configuration.xml`
2. 先确认 `C runtime init`、晶振装配状态、时钟树、PFS 保护是否与目标板真实硬件一致
3. 优先把链路先在“最小 UART 闭环”上跑通，再叠加 LVGL、LCD、触摸等模块
4. 如果是派生工程，先检查 BSP 启动基线，再检查协议代码

## 9. 最终结论

本次问题的本质是：

**当前工程的 UART 配置虽然看起来已经对了，但 BSP/FSP 启动基线不对。**

链路失败的主因是：

- `C runtime init` 被关闭
- 主晶振/子时钟装配状态与实际时钟树矛盾
- 启动保护与时钟稳定配置偏离参考工程

修复这些板级前提后，不改 ESP32 协议本身，链路即可恢复正常。

同样地，屏幕“烧录后可亮、断电再上电黑屏”的现象，也不是独立问题，而是同一个冷启动基线错误在 LCD 路径上的表现。
