# 中文字库生成与使用说明

## 1. 结论

截至 `2026-05-28`，这个项目的板端中文字库不是直接把整份 OTF/TTF 字体打进固件，而是采用了 `中文子集 + ASCII` 的 LVGL 自定义字体方案。

当前可确认的状态是：

- 字体源文件是 `UI/fonts/NotoSansCJKsc-Regular.otf`
- 已生成的板端字体产物有：
  - `src/ui_font_sc_14.c`
  - `src/ui_font_sc_16.c`
- 当前 `app_ui.c` 实际启用的是 `ui_font_sc_14`
- `ui_font_sc_16` 已存在生成产物，但当前没有在 `app_ui.c` 中被引用
- LVGL 内置整套 CJK 字体开关当前是关闭的，项目仍然遵循“小型中文子集字体优先”的约束

这意味着：

1. 板端中文显示依赖的是预生成的 `.c` 字库文件
2. 固件不会直接加载 `NotoSansCJKsc-Regular.otf`
3. 新增中文文案时，需要扩展子集字符表后重新生成字体

## 2. 相关文件

### 2.1 字体源文件

- `UI/fonts/NotoSansCJKsc-Regular.otf`

这是生成中文子集字库时使用的原始字体文件。当前文件大小约 `16,437,364` 字节。

### 2.2 生成产物

- `src/ui_font_sc_14.c`
  - 当前文件大小约 `39,100` 字节
  - `14 px`
  - `1 bpp`
  - 包含 `95` 个 ASCII 字符（`0x20-0x7E`）和 `79` 个中文子集字符

- `src/ui_font_sc_16.c`
  - 当前文件大小约 `102,075` 字节
  - `16 px`
  - `4 bpp`
  - 包含 `95` 个 ASCII 字符（`0x20-0x7E`）和 `84` 个中文子集字符

### 2.3 使用入口

- `src/app_ui.c`
- `ra_cfg/fsp_cfg/lvgl/lvgl/lv_conf.h`

## 3. 当前生成情况

仓库里没有找到独立保存的字体生成脚本，例如：

- `generate_font.ps1`
- `generate_font.bat`
- `package.json` 中的字体生成命令

但是两份生成产物头部都保留了生成参数，因此当前可以从产物反推出生成方式。

### 3.1 `ui_font_sc_14` 的生成参数

`src/ui_font_sc_14.c` 文件头记录的参数如下：

```text
--size 14
--bpp 1
--format lvgl
--font UI\fonts\NotoSansCJKsc-Regular.otf
--range 0x20-0x7E
--symbols 备本步操插查常传次待等点度端断舵发蜂感刚和机即检建脚接捷据开空控快离立连链令路鸣命平屏器情请求确热认入上设湿收首数刷送台态同未温闲线详新行已异用云在正执制状作
--no-compress
--no-prefilter
--no-kerning
--lv-font-name ui_font_sc_14
-o src\ui_font_sc_14.c
```

### 3.2 `ui_font_sc_16` 的生成参数

`src/ui_font_sc_16.c` 文件头记录的参数如下：

```text
--size 16
--bpp 4
--format lvgl
--font UI\fonts\NotoSansCJKsc-Regular.otf
--range 0x20-0x7E
--symbols 备本步操插查常传次待等点度端断舵发蜂感刚稿和机即检建角脚接捷据开空控口快扩离立连链令路鸣命平器嵌情请求确热认入上设湿收数刷送台态同未温闲线详新行已异用云在展正执制状自作
--lv-font-name ui_font_sc_16
-o src\ui_font_sc_16.c
```

### 3.3 对生成工具的判断

仓库里没有直接保存生成命令的可执行名，但从参数格式和 LVGL 产物结构看，这两份文件明显是按 `LVGL font converter` 一类工具生成的。

为了后续复现，建议直接按 `lv_font_conv` 的方式管理和再生成；下面的命令就是根据现有产物头部参数还原出来的推荐写法。

## 4. 推荐的再生成命令

### 4.1 生成 `ui_font_sc_14.c`

```powershell
lv_font_conv --size 14 --bpp 1 --format lvgl --font UI/fonts/NotoSansCJKsc-Regular.otf --range 0x20-0x7E --symbols "备本步操插查常传次待等点度端断舵发蜂感刚和机即检建脚接捷据开空控快离立连链令路鸣命平屏器情请求确热认入上设湿收首数刷送台态同未温闲线详新行已异用云在正执制状作" --no-compress --no-prefilter --no-kerning --lv-font-name ui_font_sc_14 -o src/ui_font_sc_14.c
```

### 4.2 生成 `ui_font_sc_16.c`

```powershell
lv_font_conv --size 16 --bpp 4 --format lvgl --font UI/fonts/NotoSansCJKsc-Regular.otf --range 0x20-0x7E --symbols "备本步操插查常传次待等点度端断舵发蜂感刚稿和机即检建角脚接捷据开空控口快扩离立连链令路鸣命平器嵌情请求确热认入上设湿收数刷送台态同未温闲线详新行已异用云在展正执制状自作" --lv-font-name ui_font_sc_16 -o src/ui_font_sc_16.c
```

说明：

- `--range 0x20-0x7E` 负责英文、数字、符号等 ASCII 字符
- `--symbols` 负责补充项目实际要显示的中文字符
- `ui_font_sc_14` 明确关闭了压缩、预滤波和 kerning
- `ui_font_sc_16` 当前头部没有记录这些关闭项，因此它的输出风格和 `14 px` 版本并不完全一致

## 5. 当前是怎么使用的

### 5.1 板端没有直接使用整份 OTF

板端固件实际使用的是 `src/ui_font_sc_14.c` / `src/ui_font_sc_16.c` 这种 LVGL 字体 C 文件，而不是运行时去读 `UI/fonts/NotoSansCJKsc-Regular.otf`。

因此 `UI/fonts/NotoSansCJKsc-Regular.otf` 的角色更接近：

- 字库生成源文件
- 设计/资源保留文件

而不是板端部署文件。

### 5.2 当前 UI 真正启用的是 `ui_font_sc_14`

`src/app_ui.c` 里当前只有：

- `LV_FONT_DECLARE(ui_font_sc_14);`

并且：

- `ui_font_large()` 返回 `&ui_font_sc_14`
- `ui_font_small()` 也返回 `&ui_font_sc_14`

所以当前首页上的中文标题、标签、状态字样，实际上都走的是 `14 px` 这套中文子集字体。

### 5.3 数值类显示仍然混用 LVGL 内置英文字体

`src/app_ui.c` 中的温度、湿度这类 ASCII 值显示，使用的是：

- `lv_font_montserrat_16`

也就是说当前 UI 是混合方案：

- 中文文案：`ui_font_sc_14`
- 数字/ASCII 大字：`lv_font_montserrat_16`

这样做的直接好处是：

- 中文范围可控
- 英文数字显示更省事
- 不需要把所有字号都做成中文子集字库

### 5.4 默认字体仍然不是自定义中文字库

`ra_cfg/fsp_cfg/lvgl/lvgl/lv_conf.h` 里当前默认字体仍是：

- `LV_FONT_DEFAULT = &lv_font_montserrat_14`

这说明项目不是通过“替换全局默认字体”来支持中文，而是在具体控件上显式调用 `lv_obj_set_style_text_font()` 绑定中文字库。

## 6. 为什么没有直接开 LVGL 内置整套中文字体

`lv_conf.h` 里当前可见：

- `LV_FONT_SOURCE_HAN_SANS_SC_14_CJK = 0`
- `LV_FONT_SOURCE_HAN_SANS_SC_16_CJK = 0`

这和项目历史约束是一致的：优先小型中文子集字体，不要直接启用整套 CJK 字库。

这样做主要是为了控制：

- 固件体积
- Flash 占用
- 构建和烧录风险

项目历史记录里已经明确提到，完整 CJK 字体曾带来体积和目标写入方面的问题，因此当前方案是有明确工程背景的，不是随手裁剪。

## 7. `ui_font_sc_16` 当前处于什么状态

当前可以确认：

- `src/ui_font_sc_16.c` 已生成
- `Debug/src/subdir.mk` 会把它编译成对象文件
- `app_ui.c` 中没有发现对 `ui_font_sc_16` 的声明和引用
- 工程链接参数开启了 `--gc-sections`

因此更准确的说法应该是：

- `ui_font_sc_16` 是现存的候选字库产物
- 它会进入编译流程
- 但当前是否进入最终固件镜像，要看链接阶段是否因为“无引用”而被裁剪
- 无论如何，它当前不是界面显示时实际选中的字体

## 8. 后续如果要新增中文，应该怎么做

建议按下面流程维护：

1. 先从 `src/app_ui.c`、原型文案、状态文案里收集新增中文字符
2. 把所有需要显示的新增汉字补到 `--symbols` 字符串
3. 重新生成对应的 `src/ui_font_sc_14.c` 或 `src/ui_font_sc_16.c`
4. 重新编译固件
5. 上板验证是否有缺字、错位、行高异常

如果界面出现下面这些现象：

- 方框
- 缺字
- 某个状态文案显示为空

优先检查的不是 LVGL 本身，而是：

- 新字符有没有加入 `--symbols`
- 是否重新生成了字库
- 代码是否仍在使用旧的 `ui_font_sc_14.c`

## 9. 与 HTML 原型的关系

需要特别区分两件事：

1. `UI/RA8P1_UI.html` 是原型
2. `src/ui_font_sc_14.c` / `src/ui_font_sc_16.c` 是板端字体产物

当前 HTML 原型里的字体栈主要是系统字体：

- `"Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`

仓库里没有看到它通过 `@font-face` 直接加载 `NotoSansCJKsc-Regular.otf`。

因此：

- 原型显示中文，主要依赖系统字体栈
- 板端显示中文，依赖预生成的 LVGL 子集字库

两边不要混为一谈。

## 10. 建议的后续整理项

如果后面要把这套流程做成可重复、可交接的工程资产，建议再补两项：

1. 新增一个明确的生成脚本，例如 `tools/generate_ui_fonts.ps1`
2. 把 `--symbols` 列表单独拆到文本文件，避免每次手工改长命令

这样后面扩字时就不会只能依赖“查看旧产物头部参数”来回推生成命令。
