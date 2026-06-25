# RA8P1 与 CL40BC299 屏幕链路打通总结

## 当前结果

RA8P1 与 CL40BC299-40A IPS CTP 屏幕的显示链路已经打通。

当前已验证：

- Renesas Flash Programmer 可以正常连接和烧录 RA8P1。
- LCD 背光、复位、片选、DC、SCK、MOSI 等 GPIO 控制有效。
- 软件 GPIO SPI 直写 LCD 能显示色条。
- LVGL 已能通过 `disp_flush()` 刷新到屏幕。
- 最终完整 `320 x 480` LVGL UI 显示成功。

## 硬件连接基线

| 信号 | 板端标识 | RA8P1 引脚 |
| --- | --- | --- |
| T-SDI / Touch SDA | P8 | P400 |
| T_CS / Touch reset or CS | P4 | P402 |
| T_clk / Touch SCL | P9 | P401 |
| SDO / LCD MISO | P6 | P715 |
| LED | P7 | P106 |
| Sck / LCD SCK | P4 | P514 |
| SDI / LCD MOSI | P6 | P714 |
| DC | P7 | P102 |
| RESET | P7 | P600 |
| CS | P4 | P515 |

这张表是当前工程的第一标准。后续如果 e2studio 中出现旧的 SCI/I2C/SPI 外设复用，应以这张表重新校正。

## 当前关键工程文件

| 文件 | 作用 |
| --- | --- |
| `src/lcd_spi.c/h` | LCD GPIO SPI、LCD 初始化、窗口设置、像素写入 |
| `src/lv_port_disp.c/h` | LVGL display 创建、buffer 注册、flush 回调 |
| `src/hal_entry.c` | 启动流程和当前简单 UI |
| `src/ft6336.c/h` | 后续触摸 FT6336 驱动基础 |
| `configuration.xml` | FSP 工程配置源 |
| `ra_cfg/fsp_cfg/bsp/bsp_cfg.h` | FSP 生成的 BSP 配置 |
| `docs/lvgl_black_screen_failure_summary.md` | 黑屏失败原因与调试过程 |
| `project-wiki/` | 后续长期知识库和外部资料快照 |

## 关键修复

最终黑屏主因是 main stack 太小。

失败配置：

```c
#define BSP_CFG_STACK_MAIN_BYTES (0x400)
```

也就是只有 1 KB。LCD 直写能跑，但 LVGL 首次刷新调用链更深，程序卡在第一次刷新前，导致 `disp_flush()` 不被调用。

修复配置：

```c
#define BSP_CFG_STACK_MAIN_BYTES (0x4000)
```

同时在 `configuration.xml` 中保留：

```xml
<property id="config.bsp.common.main" value="0x4000"/>
```

这样后续点击 `Generate Project Content` 时不会轻易退回 1 KB。

## 验证过程

调试过程按层验证：

1. RFP 烧录成功。
2. LCD 直写色条成功。
3. 加入 LVGL 后曾经黑屏。
4. 添加阶段白块，发现只执行到约 80%。
5. 在 `disp_flush()` 入口添加黄色条，发现黄色条不出现。
6. 判断 LVGL 没有进入 flush，优先检查 main stack。
7. main stack 从 `0x400` 调整到 `0x4000`。
8. 黄色条出现，阶段白块完整。
9. 移除调试色块，完整 LVGL UI 显示成功。

## 当前显示路径

LCD 初始化配置为 ILI9488 兼容路径：

- 分辨率：`320 x 480`
- LCD 接收格式：RGB666 / 18-bit，`0x3A = 0x66`
- LVGL 内部格式：RGB565
- `disp_flush()` 中将 RGB565 展开为 3 字节写入 LCD

LVGL display 创建方式：

```c
lv_display_t * disp = lv_display_create(320, 480);
lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
lv_display_set_flush_cb(disp, disp_flush);
lv_display_set_buffers(disp, buf_1, NULL, sizeof(buf_1), LV_DISPLAY_RENDER_MODE_PARTIAL);
```

主循环：

```c
while (1) {
    lv_tick_inc(5);
    (void) lv_timer_handler();
    R_BSP_SoftwareDelay(5, BSP_DELAY_UNITS_MILLISECONDS);
}
```

## 已整理成 Skill

为后续复用，已新增 skill：

```text
D:\Renesas-Workspace\RA8P1_Viewing_Screen_Working\agent-skills\skills\ra8p1-lvgl-screen-bringup
```

内容包括：

- RA8P1 + CL40BC299/ILI9488 屏幕 bring-up 工作流。
- 硬件引脚和工程配置基线。
- 黑屏诊断流程。
- LVGL flush、stack、`.srec` 大小等判断规则。

后续遇到屏幕黑屏、LVGL 不刷新、引脚复用混乱、FSP 重新生成配置等问题，可以直接读取这个 skill。

## 后续建议

下一步做触摸时，不要同时改显示链路。

推荐顺序：

1. 保持当前软件 GPIO SPI 显示路径不变。
2. 单独验证 FT6336 原始坐标读取。
3. 新增 `lv_port_indev.c/h` 接入 LVGL 输入设备。
4. 做坐标方向和镜像校准。
5. 再把 UI 从 `hal_entry.c` 拆到 `app_ui.c/h`。

当前显示链路已经是可工作的基线，后续改动应按小步验证推进。
