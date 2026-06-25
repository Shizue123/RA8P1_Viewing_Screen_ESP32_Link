# RA8P1 LVGL 黑屏问题失败原因总结

## 背景

本工程用于在 RA8P1 核心板上驱动 CL40BC299-40A IPS CTP 屏幕，并移植 LVGL 作为后续触摸 UI 的基础。

硬件连接以当前实物连接为准：

| 信号 | RA8P1 引脚 |
| --- | --- |
| LCD SCK | P514 |
| LCD MOSI / SDI | P714 |
| LCD MISO / SDO | P715 |
| LCD CS | P515 |
| LCD DC | P102 |
| LCD RESET | P600 |
| LCD LED | P106 |
| Touch SDA / T-SDI | P400 |
| Touch SCL / T_clk | P401 |
| Touch CS / T_CS | P402 |

## 现象

调试过程中出现过以下现象：

- Renesas Flash Programmer 烧录成功，目标芯片识别正常。
- LCD 背光正常。
- 直接使用 GPIO SPI 写屏时，红、绿、蓝色条可以显示。
- 加入 LVGL 后，早期版本黑屏或只有背光。
- 后续调试版本能看到直写色条，但没有 LVGL UI。
- 在 `disp_flush()` 入口加入黄色条后，黄色条一开始没有出现。
- 阶段性白块只显示约 80%，即程序没有走完首次 LVGL 刷新流程。
- `.srec` 曾经只有 4 KB 或 5 KB，说明当时 LVGL 实际没有被完整链接进最终固件。

## 根因

最终确认主因是 **main stack 过小**。

原始 BSP 配置为：

```c
#define BSP_CFG_STACK_MAIN_BYTES (0x400)
```

也就是主栈只有 1 KB。

LCD 直写测试能够成功，是因为调用链很浅，只涉及 GPIO 翻转、LCD 命令和像素写入。LVGL 首次刷新则不同，会经过对象树、样式、布局、无效区域、绘制任务、颜色转换、显示 flush 回调等调用链。1 KB 主栈不足以支撑这条调用链，导致程序卡在首次刷新阶段。

从调试现象可以反推出卡点：

- 黄色条没有出现：说明 `disp_flush()` 根本没有被调用。
- 白块只有约 80%：说明程序卡在 `lv_refr_now(NULL)` 或首次 `lv_timer_handler()` 附近。
- 直写色条正常：说明 LCD 初始化、GPIO SPI、引脚连接和烧录流程不是主要问题。

## 修复

将主栈从 1 KB 提升到 16 KB。

修改文件：

```text
D:\Renesas-Workspace\RA8P1_Viewing_Screen_Working\ra_cfg\fsp_cfg\bsp\bsp_cfg.h
```

修改内容：

```c
#define BSP_CFG_STACK_MAIN_BYTES (0x4000)
```

同时同步修改 FSP 配置源文件，避免后续点击 `Generate Project Content` 后被恢复：

```text
D:\Renesas-Workspace\RA8P1_Viewing_Screen_Working\configuration.xml
```

修改内容：

```xml
<property id="config.bsp.common.main" value="0x4000"/>
```

重新编译后，map 文件确认：

```text
.bss.g_main_stack  size = 0x4000
```

## 修复后的验证结果

修复主栈后，现象变为：

- 黄色条出现，证明 LVGL 已进入 `disp_flush()`。
- 白块从约 80% 变为完整一行，证明首次刷新流程走完。
- 顶部区域出现紫色 LVGL 背景，证明 LVGL 已经真正刷到屏幕。
- 移除调试条后，完整 320x480 LVGL UI 显示成功。

## 本次代码改动清单

本次调试和修复涉及以下文件：

### `configuration.xml`

修改 FSP 工程配置中的 main stack 大小：

```xml
<property id="config.bsp.common.main" value="0x4000"/>
```

目的：

- 避免后续在 e2 studio 中点击 `Generate Project Content` 后，主栈又被恢复为 1 KB。
- 让 FSP 配置源文件和生成出来的 BSP 头文件保持一致。

### `ra_cfg/fsp_cfg/bsp/bsp_cfg.h`

修改 BSP 生成头文件中的主栈大小：

```c
#define BSP_CFG_STACK_MAIN_BYTES (0x4000)
```

目的：

- 将主栈从 `0x400` 提升到 `0x4000`。
- 解决 LVGL 首次刷新过程中调用链过深导致程序卡死的问题。

### `src/lcd_spi.c`

整理并确认 LCD GPIO SPI 驱动路径，核心功能包括：

- 配置 LCD 相关 GPIO：
  - P514：SCK
  - P714：MOSI / SDI
  - P515：CS
  - P600：RESET
  - P102：DC
  - P106：LED
- 实现软件 SPI 写字节。
- 实现 LCD 命令和数据写入。
- 实现 `lcd_set_window()` 设置显示窗口。
- 实现 `lcd_fill_rect()` 和 `lcd_fill_screen()`，用于直写色块验证。
- 按 ILI9488 / CL40BC299 参考测试程序初始化 LCD。
- 使用 RGB666 写屏格式，对 LVGL 的 RGB565 像素做 16-bit 到 18-bit 输出转换。

目的：

- 先确认 LCD 初始化、引脚连接、写屏时序、背光控制都可用。
- 为 LVGL 的 `disp_flush()` 提供底层写屏接口。

### `src/lv_port_disp.c`

实现 LVGL display port：

- 创建 LVGL display：

```c
lv_display_t * disp = lv_display_create(320, 480);
```

- 设置颜色格式：

```c
lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
```

- 设置 partial buffer：

```c
lv_display_set_buffers(disp, buf_1, NULL, sizeof(buf_1), LV_DISPLAY_RENDER_MODE_PARTIAL);
```

- 实现 `disp_flush()`：
  - 接收 LVGL 刷新区域。
  - 调用 `lcd_set_window()` 设置 LCD 写入区域。
  - 将 LVGL RGB565 像素转换为 LCD 需要的 RGB888/RGB666 三字节写入。
  - 调用 `lv_display_flush_ready(disp)` 通知 LVGL 本次刷新完成。

调试过程中曾临时加入黄色条：

```c
lcd_fill_rect(0, 200, 319, 223, 0xFFE0);
```

这个黄色条用于确认 `disp_flush()` 是否被调用。确认主栈问题修复后，已移除。

目的：

- 打通 LVGL 到 LCD 的真正显示路径。
- 通过黄色条确认问题发生在 `disp_flush()` 之前还是之后。

### `src/hal_entry.c`

调整裸机入口流程：

```c
lcd_init();
lv_init();
lv_port_disp_init();
ui_create();
lv_tick_inc(1);
lv_refr_now(NULL);
```

主循环中周期驱动 LVGL：

```c
while (1) {
    lv_tick_inc(5);
    (void) lv_timer_handler();
    R_BSP_SoftwareDelay(5, BSP_DELAY_UNITS_MILLISECONDS);
}
```

调试过程中曾加入红、绿、蓝色条和 5 段白块：

- 红、绿、蓝色条：验证 LCD 直写是否正常。
- 5 段白块：验证程序执行到 LVGL 初始化、显示注册、UI 创建、首次刷新后的哪个阶段。

确认问题修复后，调试色块已移除，并改为一个简单 LVGL UI：

- 深灰背景。
- 顶部 `RA8P1 LVGL` 文本。
- 中间 `Display online` 状态框。
- 底部红、绿、蓝、黄色块。

目的：

- 先用阶段性标记定位卡死位置。
- 修复后保留一个最小可见 UI，作为后续触摸 UI 开发的基线。

### `docs/lvgl_black_screen_failure_summary.md`

新增本文档。

目的：

- 记录黑屏问题的现象、根因、修复方式、验证结果和代码改动。
- 后续接手工程或重新生成 FSP 工程内容时，可以快速知道不能把 main stack 改回 1 KB。

## 非根因问题

以下问题曾影响判断，但不是最终黑屏根因：

- 软件 GPIO SPI 速度慢，但不导致 LVGL 完全不刷新。
- LCD 初始化和 RGB666 写屏流程基本正确，因为直接写色条能显示。
- 字体 `lv_font_montserrat_20`、`lv_font_montserrat_24` 未启用，只是编译配置问题，改用已启用的 `lv_font_montserrat_16` 即可。
- `.srec` 异常小代表当时 LVGL 未被完整链接，不代表 LCD 或芯片烧录失败。

## 结论

本次黑屏失败的核心原因不是硬件引脚、RFP 烧录、LCD 初始化或 LVGL 库本身，而是：

> 裸机 main stack 默认 1 KB，无法承载 LVGL 首次刷新调用链。

后续继续开发 LVGL UI 时，必须保持 `BSP_CFG_STACK_MAIN_BYTES >= 0x4000`。如果后续 UI 更复杂、启用更多 LVGL 控件、动画、触摸处理或文件系统，建议进一步评估是否提升到 `0x8000`。
