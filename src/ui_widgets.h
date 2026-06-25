/* ui_widgets.h - 复用 UI 组件 */
#ifndef UI_WIDGETS_H_
#define UI_WIDGETS_H_

#include "lvgl.h"

/* 创建面板：白底圆角浅描边 */
lv_obj_t *ui_panel_create(lv_obj_t *parent, int x, int y, int w, int h);

/* 标签（基础） */
lv_obj_t *ui_label_create(lv_obj_t *parent, int x, int y, int w,
                          const char *text, const lv_font_t *font,
                          lv_color_t color, lv_text_align_t align);

/* 状态点（圆点） */
lv_obj_t *ui_dot_create(lv_obj_t *parent, int x, int y,
                        lv_color_t color, int diameter);

/* 按钮（带文字 + 圆角 + 回调） */
lv_obj_t *ui_button_create(lv_obj_t *parent, int x, int y, int w, int h,
                           const char *text, lv_color_t bg,
                           lv_event_cb_t cb, void *user_data);

/* v0.9.14 P1#8: 状态字渲染统一（主页/详情/PORTS 共享）
 * - input 语义状态字符串："在线" / "离线" / "未启用" / "已配置" / "通道就绪"
 * - return: 带 LV_SYMBOL_* 前缀的字符串（中文/符号冗余，色盲友好）
 * - 不识别时原样返回（fallback 友好）
 */
const char *ui_status_glyph(const char *state);

/* v0.9.14 P0#1: 基本设备卡（主页 ESP32/LCD 共用）
 * - name: 大标题（"ESP32-S3" / "ILI9488"）
 * - param: 副标题（"115k · 8N1" / "320 × 480"），纯数字 Latin 用 10px
 * - status_text: 状态行（"✓ 在线"），中文用 14px
 * - click_cb / user_data: 整卡点击回调
 */
lv_obj_t *ui_device_card_create(lv_obj_t *parent, int x, int y, int w, int h,
                                const char *name, const char *param,
                                const char *status_text,
                                lv_event_cb_t click_cb, void *user_data);

/* 暖橙主题卡（接入硬件专用） */
lv_obj_t *ui_orange_card_create(lv_obj_t *parent, int x, int y, int w, int h,
                                const char *label_text, const char *title_text,
                                const char *hint_text,
                                lv_event_cb_t cb, void *user_data);

/* 顶栏（共用） */
typedef struct {
    lv_obj_t *root;     /* 顶栏容器 */
    lv_obj_t *left;     /* 左区域（可点） */
    lv_obj_t *title;    /* 标题 */
    lv_obj_t *right;    /* 右区域（时钟） */
} ui_topbar_t;

ui_topbar_t ui_topbar_create(lv_obj_t *parent, const char *title,
                             const char *left_label, lv_event_cb_t left_cb);

/* 顶栏时间更新 */
void ui_topbar_set_time(ui_topbar_t *tb, const char *time_str);

/* 顶栏左侧标签更新（WiFi SSID 切换） */
void ui_topbar_set_left_label(ui_topbar_t *tb, const char *text);

#endif /* UI_WIDGETS_H_ */
