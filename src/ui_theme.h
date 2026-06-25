/* ui_theme.h - 设计系统 token 与主题应用 */
#ifndef UI_THEME_H_
#define UI_THEME_H_

#include "lvgl.h"

/* === 颜色 token（亮色家电风 / iOS 干净） === */
#define UI_COLOR_BG            0xF2F3F7   /* 屏幕底色 */
#define UI_COLOR_BG_PANEL      0xFFFFFF   /* 卡片白底 */
#define UI_COLOR_BORDER        0xDDE1E8   /* 浅描边 */
#define UI_COLOR_DIVIDER       0xE5E7EB   /* 分隔线 */
#define UI_COLOR_TEXT_PRIMARY  0x1C1C1E   /* 主文字 */
#define UI_COLOR_TEXT_DIM      0x6C6C70   /* 次文字 */
#define UI_COLOR_TEXT_MUTED    0x8E8E93   /* 提示 */
#define UI_COLOR_ACCENT        0x1D3AA8   /* 深蓝（标题强调） */
#define UI_COLOR_SUCCESS       0x34C759   /* iOS 绿 */
#define UI_COLOR_DANGER        0xFF3B30   /* iOS 红 */
#define UI_COLOR_WIFI_GREEN    0x34C759   /* WiFi 在线绿 */
#define UI_COLOR_ARROW_DIM     0xC7C9CF   /* 浅灰箭头 */

/* v0.9.14 状态徽章色（浅绿背景 + 深绿文字，详情 status_pill 用） */
#define UI_COLOR_BADGE_BG      0xE1F7EC
#define UI_COLOR_BADGE_TEXT    0x1F9C5A

/* v0.9.14 元件色（版本号框、tag） */
#define UI_COLOR_TAG_BG        0xE5E5EA

/* === 暖橙主题（接入硬件入口） === */
#define UI_COLOR_ORANGE_A       0xFFF7E6
#define UI_COLOR_ORANGE_B       0xFFE5C2
#define UI_COLOR_ORANGE_BG_A    0xFFF7E6
#define UI_COLOR_ORANGE_BG_B    0xFFE5C2
#define UI_COLOR_ORANGE_LABEL   0xB8761F
#define UI_COLOR_ORANGE_TITLE   0x5A3B00
#define UI_COLOR_ORANGE_HINT    0x8A5A1A
#define UI_COLOR_ORANGE_META    0x8A5A1A

/* === 尺寸 token === */
#define UI_TOPBAR_H            44
#define UI_SCREEN_W            320
#define UI_SCREEN_H            480
#define UI_BODY_PADDING        14
#define UI_CARD_RADIUS         14
#define UI_CARD_GAP            10
#define UI_CARD_INNER_PAD      14

/* === 字体 token（指向 LVGL 内置 CJK 字体） === */
const lv_font_t *ui_font_xs(void);    /* 10 */
const lv_font_t *ui_font_sm(void);    /* 12 */
const lv_font_t *ui_font_md(void);    /* 14 中文 */
const lv_font_t *ui_font_lg(void);    /* 16 中文 */
const lv_font_t *ui_font_xl(void);    /* 18 拉丁 */
const lv_font_t *ui_font_xxl(void);   /* 22 拉丁 */
const lv_font_t *ui_font_mono(void);  /* 等宽 14 */

/* === 主题初始化（在 hal_entry 的 lv_init 之后调一次） === */
void ui_theme_apply(void);

/* === 通用样式应用：清背景 + 设圆角 + 设 padding === */
void ui_style_card_init(void);
void ui_style_card_apply(lv_obj_t *obj);

#endif /* UI_THEME_H_ */
