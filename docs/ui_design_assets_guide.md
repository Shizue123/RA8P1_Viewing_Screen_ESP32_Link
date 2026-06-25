# UI 设计文件索引与配套说明

## 1. 结论

当前项目里已经有可用的 UI 设计文件，但它们不是单一“设计稿”，而是按下面这套结构组织：

1. `HTML 原型`
2. `原型截图`
3. `交互方案文档`
4. `板端 LVGL 落地代码`

如果要找“UI 设计文件”，优先看：

- [`UI/RA8P1_UI.html`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/UI/RA8P1_UI.html)
- [`docs/ui_operation_interface_plan.md`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/docs/ui_operation_interface_plan.md)

## 2. 文件位置

### 2.1 设计原型

- [`UI/RA8P1_UI.html`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/UI/RA8P1_UI.html)
  当前最完整的 UI 设计原型。
  一个文件里同时包含：
  - 板端屏幕 HMI 原型
  - 云端 Web 控制台原型
  - 点击交互、弹窗、Toast 模拟

- [`UI/playwright-ui-check.png`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/UI/playwright-ui-check.png)
  对 `RA8P1_UI.html` 的页面截图，适合快速预览和汇报时引用。

- [`UI/fonts/NotoSansCJKsc-Regular.otf`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/UI/fonts/NotoSansCJKsc-Regular.otf)
  原型使用到的中文字体资源。
  这是原型侧素材，不等于板端固件直接使用该整字体文件。

## 3. 配套说明文档

- [`docs/ui_operation_interface_plan.md`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/docs/ui_operation_interface_plan.md)
  UI 方案主文档。
  定义了板端 `首页 / 控制 / 任务 / 诊断` 四页结构，以及云端 `总览 / 部署 / 模块 / 事件 / 历史` 五页结构。

- [`project-wiki/touch_ui_plan.md`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/project-wiki/touch_ui_plan.md)
  更偏开发规划，说明触摸接入、LVGL 输入设备分层、后续 UI 拆分方式。
  这个文档适合开发人员，不是最终交互稿。

- [`docs/agent_feedback_ledger.md`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/docs/agent_feedback_ledger.md)
  记录了这个项目在 UI 上的几个硬约束：
  - 必须按真实竖屏面板设计
  - 不能把页面做得过密
  - 优先小型中文子集字体
  - 不要在运行时用 float `scanf` 解析显示值

## 4. 对应的板端实现文件

- [`src/app_ui.c`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/src/app_ui.c)
- [`src/app_ui.h`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/src/app_ui.h)

这两份不是“设计稿”，而是当前 RA8P1 板端 UI 的真实落地代码。

它们当前实现的是一个轻量状态首页，重点展示：

- `ESP32 / WiFi / MQTT / LCD` 状态
- 温湿度卡片
- `AHT20` 状态
- 云端链路状态
- `RX / TX / Request / Script / Cmd / ACK`

也就是说：

- `RA8P1_UI.html` 代表目标交互形态
- `app_ui.c` 代表当前已经跑在板子上的简化实现

两者目前还不是一比一完全对齐。
当前板端实现更接近原型中的“首页状态壳”，还没有完整移植出四个主页面和全部触摸交互。

## 5. 原型和实现的关系

建议按下面的顺序理解这套 UI：

1. 先看 [`docs/ui_operation_interface_plan.md`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/docs/ui_operation_interface_plan.md)
   先明确页面职责和交互边界。
2. 再看 [`UI/RA8P1_UI.html`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/UI/RA8P1_UI.html)
   看视觉结构、按钮、弹窗和 Web/板端联动表现。
3. 最后看 [`src/app_ui.c`](/D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/src/app_ui.c)
   确认当前固件实际上已经落到了哪一步。

## 6. 当前可直接给别人看的说明

如果需要对外说明这套设计文件，可以直接用下面这段：

> `UI/RA8P1_UI.html` 是历史交互原型；当前实机界面与行为必须以 `src/app_ui.c`、`src/ui_widgets.c`、`src/ui_theme.c` 和 `docs/competition_solution_baseline_2026.md` 为准。原型不能覆盖真实设备注册、动态模块列表或当前 320 x 480 竖屏约束。

## 7. 当前缺口

当前仓库里没有看到以下类型的独立设计源文件：

- `.fig`
- `.sketch`
- `.xd`
- Axure 工程文件

因此这个项目现阶段的“设计稿基线”应认定为：

- `HTML 原型 + 方案文档 + LVGL 实现代码`

而不是 Figma 类源文件。
