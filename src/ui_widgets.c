/* ui_widgets.c - 复用组件实现 */
#include "ui_widgets.h"
#include "ui_theme.h"
#include <string.h>

/* v0.9.7: 字体回到 ui_font_sc_14 (NotoSansSC 全 CJK, 与 d/ 同款)。
   Source Han Sans 14 在 320px 宽屏把中文截断成单字孤岛，
   切回 NotoSansSC 后 layout 不变，字符宽度够装。 */
extern const lv_font_t ui_font_sc_14;
#define UI_FONT_14 (&ui_font_sc_14)

/* === 面板 === */
lv_obj_t *ui_panel_create(lv_obj_t *parent, int x, int y, int w, int h)
{
    lv_obj_t *p = lv_obj_create(parent);
    lv_obj_set_pos(p, x, y);
    lv_obj_set_size(p, w, h);
    lv_obj_set_style_bg_color(p, lv_color_hex(UI_COLOR_BG_PANEL), 0);
    lv_obj_set_style_bg_opa(p, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(p, UI_CARD_RADIUS, 0);
    lv_obj_set_style_border_color(p, lv_color_hex(UI_COLOR_BORDER), 0);
    lv_obj_set_style_border_width(p, 1, 0);
    lv_obj_set_style_border_opa(p, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(p, 0, 0);
    lv_obj_set_style_shadow_opa(p, LV_OPA_TRANSP, 0);
    lv_obj_clear_flag(p, LV_OBJ_FLAG_SCROLLABLE);
    return p;
}

/* === 标签 === */
lv_obj_t *ui_label_create(lv_obj_t *parent, int x, int y, int w,
                          const char *text, const lv_font_t *font,
                          lv_color_t color, lv_text_align_t align)
{
    lv_obj_t *lab = lv_label_create(parent);
    lv_obj_set_pos(lab, x, y);
    lv_obj_set_size(lab, w, LV_SIZE_CONTENT);
    lv_label_set_text(lab, text);
    lv_obj_set_style_text_font(lab, font, 0);
    lv_obj_set_style_text_color(lab, color, 0);
    lv_obj_set_style_text_align(lab, align, 0);
    lv_obj_set_style_bg_opa(lab, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_opa(lab, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(lab, 0, 0);
    return lab;
}

/* === 圆点 === */
lv_obj_t *ui_dot_create(lv_obj_t *parent, int x, int y,
                        lv_color_t color, int diameter)
{
    lv_obj_t *d = lv_obj_create(parent);
    lv_obj_set_pos(d, x, y);
    lv_obj_set_size(d, diameter, diameter);
    lv_obj_set_style_radius(d, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(d, color, 0);
    lv_obj_set_style_bg_opa(d, LV_OPA_COVER, 0);
    lv_obj_set_style_border_opa(d, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(d, 0, 0);
    lv_obj_clear_flag(d, LV_OBJ_FLAG_SCROLLABLE);
    return d;
}

/* === 按钮 === */
lv_obj_t *ui_button_create(lv_obj_t *parent, int x, int y, int w, int h,
                           const char *text, lv_color_t bg,
                           lv_event_cb_t cb, void *user_data)
{
    lv_obj_t *btn = lv_btn_create(parent);
    lv_obj_set_pos(btn, x, y);
    lv_obj_set_size(btn, w, h);
    lv_obj_set_style_bg_color(btn, bg, 0);
    lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(btn, 8, 0);
    lv_obj_set_style_border_opa(btn, LV_OPA_TRANSP, 0);
    lv_obj_set_style_shadow_opa(btn, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(btn, 0, 0);
    if (cb != NULL) lv_obj_add_event_cb(btn, cb, LV_EVENT_CLICKED, user_data);
    lv_obj_t *lab = lv_label_create(btn);
    lv_label_set_text(lab, text);
    lv_obj_set_style_text_font(lab, UI_FONT_14, 0);
    lv_obj_set_style_text_color(lab, (lv_color_t){.red=0xFF, .green=0xFF, .blue=0xFF}, 0);
    lv_obj_center(lab);
    return btn;
}

/* === 暖橙主题卡 === */
typedef struct {
    lv_obj_t *arrow_circle;
} orange_card_user_t;

lv_obj_t *ui_orange_card_create(lv_obj_t *parent, int x, int y, int w, int h,
                                const char *label_text, const char *title_text,
                                const char *hint_text,
                                lv_event_cb_t cb, void *user_data)
{
    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_set_pos(card, x, y);
    lv_obj_set_size(card, w, h);
    /* v0.9.9: 去渐变 + 描边加深
       原 v0.9.6 HOR 渐变到 0xFFCC66，右半边与屏底 0xF2F3F7 同色阶，边界"融化"；
       改实底 0xFFE8B0 + 描边 0xC77810 (加深) 解决"不明显" */
    lv_obj_set_style_bg_color(card, lv_color_hex(0xFFE8B0), 0);
    lv_obj_set_style_bg_grad_color(card, lv_color_hex(0xFFE8B0), 0);  /* 同色 = 无渐变 */
    lv_obj_set_style_bg_grad_dir(card, LV_GRAD_DIR_NONE, 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(card, 16, 0);
    lv_obj_set_style_border_color(card, lv_color_hex(0xC77810), 0);  /* 加深的橙边框 */
    lv_obj_set_style_border_width(card, 2, 0);
    lv_obj_set_style_border_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(card, 16, 0);
    lv_obj_set_style_shadow_opa(card, LV_OPA_TRANSP, 0);
    lv_obj_clear_flag(card, LV_OBJ_FLAG_SCROLLABLE);

    if (cb != NULL) {
        lv_obj_add_event_cb(card, cb, LV_EVENT_CLICKED, user_data);
    }
    lv_obj_add_flag(card, LV_OBJ_FLAG_CLICKABLE);

    /* 顶部小标 */
    lv_obj_t *lab = lv_label_create(card);
    lv_label_set_text(lab, label_text);
    lv_obj_set_style_text_font(lab, &lv_font_montserrat_10, 0);
    lv_obj_set_style_text_color(lab, lv_color_hex(0x8A4A0A), 0);  /* 深橙小标 */
    lv_obj_set_pos(lab, 0, 0);
    lv_obj_set_size(lab, w - 32, LV_SIZE_CONTENT);
    lv_obj_set_style_text_align(lab, LV_TEXT_ALIGN_LEFT, 0);

    /* 标题行：左标题 + 右箭头圆 */
    lv_obj_t *title = lv_label_create(card);
    lv_label_set_text(title, title_text);
    lv_obj_set_style_text_font(title, UI_FONT_14, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(0x3A2200), 0);  /* 几乎黑色，深棕 */
    lv_obj_set_pos(title, 0, 16);
    lv_obj_set_size(title, w - 60, 24);
    lv_label_set_long_mode(title, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_style_text_align(title, LV_TEXT_ALIGN_LEFT, 0);

    /* 右侧白圆 › */
    lv_obj_t *arrow = lv_obj_create(card);
    lv_obj_set_size(arrow, 28, 28);
    lv_obj_set_pos(arrow, w - 28 - 16, 12);
    lv_obj_set_style_radius(arrow, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(arrow, (lv_color_t){.red=0xFF, .green=0xFF, .blue=0xFF}, 0);
    lv_obj_set_style_bg_opa(arrow, LV_OPA_COVER, 0);
    lv_obj_set_style_border_opa(arrow, LV_OPA_TRANSP, 0);
    lv_obj_clear_flag(arrow, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t *arrow_ch = lv_label_create(arrow);
    lv_label_set_text(arrow_ch, LV_SYMBOL_RIGHT);
    lv_obj_set_style_text_font(arrow_ch, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(arrow_ch, lv_color_hex(0x8A4A0A), 0);
    lv_obj_center(arrow_ch);

    /* 提示文字 */
    if (hint_text != NULL && hint_text[0] != '\0') {
        lv_obj_t *hint = lv_label_create(card);
        lv_label_set_text(hint, hint_text);
        lv_obj_set_style_text_font(hint, UI_FONT_14, 0);
        lv_obj_set_style_text_color(hint, lv_color_hex(0x5A3300), 0);
        lv_obj_set_pos(hint, 0, 46);
        lv_obj_set_size(hint, w - 16, LV_SIZE_CONTENT);
        lv_label_set_long_mode(hint, LV_LABEL_LONG_WRAP);
    }

    return card;
}

/* === 顶栏：左右标签用全局静态指针存（每次顶栏创建时覆盖） === */
static lv_obj_t *s_topbar_left_label = NULL;
static lv_obj_t *s_topbar_time_label = NULL;

typedef struct {
    lv_obj_t *left_label;
    lv_obj_t *time_label;
} topbar_user_t;

static void topbar_left_event_cb(lv_event_t *e)
{
    lv_event_cb_t orig = (lv_event_cb_t)lv_event_get_user_data(e);
    if (orig != NULL) orig(e);
}

ui_topbar_t ui_topbar_create(lv_obj_t *parent, const char *title,
                             const char *left_label, lv_event_cb_t left_cb)
{
    ui_topbar_t tb = {0};

    tb.root = lv_obj_create(parent);
    lv_obj_set_pos(tb.root, 0, 0);
    lv_obj_set_size(tb.root, UI_SCREEN_W, UI_TOPBAR_H);
    /* v0.9.22: 强制设 height, 避免某些 LVGL v9 path 下 topbar 被压成 0px */
    lv_obj_set_height(tb.root, UI_TOPBAR_H);
    lv_obj_set_width(tb.root, UI_SCREEN_W);
    lv_obj_set_style_bg_color(tb.root, (lv_color_t){.red=0xFF, .green=0xFF, .blue=0xFF}, 0);
    lv_obj_set_style_bg_opa(tb.root, LV_OPA_COVER, 0);
    lv_obj_set_style_border_side(tb.root, LV_BORDER_SIDE_BOTTOM, 0);
    lv_obj_set_style_border_color(tb.root, lv_color_hex(UI_COLOR_BORDER), 0);
    lv_obj_set_style_border_width(tb.root, 1, 0);
    lv_obj_set_style_pad_all(tb.root, 0, 0);
    lv_obj_clear_flag(tb.root, LV_OBJ_FLAG_SCROLLABLE);
    /* 整条 bar 都 clickable，点任何位置都触发 left_cb（默认是 WiFi 弹层） */
    if (left_cb != NULL) {
        lv_obj_add_event_cb(tb.root, topbar_left_event_cb, LV_EVENT_CLICKED, (void *)left_cb);
        lv_obj_add_flag(tb.root, LV_OBJ_FLAG_CLICKABLE);
    }

    /* 左侧 WiFi 块（可点） */
    tb.left = lv_obj_create(tb.root);
    lv_obj_set_size(tb.left, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_color_t bg_gray;
    bg_gray.red = (0xF2F3F7 >> 16) & 0xFF;
    bg_gray.green = (0xF2F3F7 >> 8) & 0xFF;
    bg_gray.blue = 0xF2F3F7 & 0xFF;
    lv_obj_set_style_bg_color(tb.left, bg_gray, 0);
    lv_obj_set_style_bg_opa(tb.left, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(tb.left, 8, 0);
    lv_obj_set_style_pad_left(tb.left, 8, 0);
    lv_obj_set_style_pad_right(tb.left, 8, 0);
    lv_obj_set_style_pad_top(tb.left, 5, 0);
    lv_obj_set_style_pad_bottom(tb.left, 5, 0);
    lv_obj_set_style_border_opa(tb.left, LV_OPA_TRANSP, 0);
    lv_obj_set_pos(tb.left, 12, (UI_TOPBAR_H - 30) / 2);
    lv_obj_clear_flag(tb.left, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(tb.left, LV_OBJ_FLAG_CLICKABLE);
    if (left_cb != NULL) {
        lv_obj_add_event_cb(tb.left, topbar_left_event_cb, LV_EVENT_CLICKED, (void *)left_cb);
    }
    /* left 内放圆点 + 文字 + 三角 */
    (void)ui_dot_create(tb.left, 0, 8, lv_color_hex(UI_COLOR_WIFI_GREEN), 7);
    s_topbar_left_label = lv_label_create(tb.left);
    lv_label_set_text(s_topbar_left_label, left_label);
    lv_obj_set_style_text_font(s_topbar_left_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_color(s_topbar_left_label, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
    lv_obj_set_pos(s_topbar_left_label, 12, 4);
    lv_obj_set_size(s_topbar_left_label, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_t *caret = lv_label_create(tb.left);
    lv_label_set_text(caret, LV_SYMBOL_DOWN);
    lv_obj_set_style_text_font(caret, &lv_font_montserrat_10, 0);
    lv_obj_set_style_text_color(caret, lv_color_hex(UI_COLOR_ARROW_DIM), 0);
    lv_obj_align_to(caret, s_topbar_left_label, LV_ALIGN_OUT_RIGHT_MID, 4, 0);

    /* 中标题：让出左右顶栏控件 (左 WiFi 块 ~ 80px，右时间 ~ 70px) */
    tb.title = lv_label_create(tb.root);
    lv_label_set_text(tb.title, title);
    lv_obj_set_style_text_font(tb.title, UI_FONT_14, 0);
    lv_obj_set_style_text_color(tb.title, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
    lv_obj_set_style_text_align(tb.title, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(tb.title, 60, 12);
    lv_obj_set_size(tb.title, UI_SCREEN_W - 130, 22);
    lv_label_set_long_mode(tb.title, LV_LABEL_LONG_SCROLL_CIRCULAR);

    /* 右侧时间 */
    lv_obj_t *right = lv_obj_create(tb.root);
    lv_obj_set_size(right, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_pos(right, UI_SCREEN_W - 70, (UI_TOPBAR_H - 24) / 2);
    lv_obj_set_style_bg_opa(right, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_opa(right, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(right, 0, 0);
    lv_obj_clear_flag(right, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t *clock_icon = lv_label_create(right);
    lv_label_set_text(clock_icon, LV_SYMBOL_BELL "\x20");
    lv_obj_set_style_text_font(clock_icon, &lv_font_montserrat_10, 0);
    lv_obj_set_style_text_color(clock_icon, lv_color_hex(UI_COLOR_TEXT_DIM), 0);
    lv_obj_set_pos(clock_icon, 0, 5);
    s_topbar_time_label = lv_label_create(right);
    lv_label_set_text(s_topbar_time_label, "00:00");
    lv_obj_set_style_text_font(s_topbar_time_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_color(s_topbar_time_label, lv_color_hex(UI_COLOR_TEXT_DIM), 0);
    lv_obj_set_pos(s_topbar_time_label, 14, 5);
    tb.right = right;

    /* 顶栏数据存到 user_data 不可行（left_cb 是回调）— 存到 tb.time_label/left_label 即可 */
    return tb;
}

void ui_topbar_set_time(ui_topbar_t *tb, const char *time_str)
{
    (void)tb;
    if (s_topbar_time_label != NULL) lv_label_set_text(s_topbar_time_label, time_str);
}

void ui_topbar_set_left_label(ui_topbar_t *tb, const char *text)
{
    (void)tb;
    if (s_topbar_left_label != NULL) lv_label_set_text(s_topbar_left_label, text);
}

/* === v0.9.14 P1#8: 状态字助手 ===
 * 设计: 6 个核心状态全覆盖，输入是源码里写死的字串（"在线"/"离线" 等），
 *       返回带 LV_SYMBOL_* 前缀的字串。仅做字面转换，不调 lv_subject。
 */
const char *ui_status_glyph(const char *state)
{
    if (state == NULL) return "";
    if (strcmp(state, "在线") == 0)     return LV_SYMBOL_OK "  在线";
    if (strcmp(state, "离线") == 0)     return LV_SYMBOL_CLOSE "  离线";
    if (strcmp(state, "未启用") == 0)    return LV_SYMBOL_MINUS "  未启用";
    if (strcmp(state, "已配置") == 0)    return LV_SYMBOL_SETTINGS "  已配置";
    if (strcmp(state, "通道就绪") == 0)  return LV_SYMBOL_PLAY "  通道就绪";
    if (strcmp(state, "校验错") == 0)    return LV_SYMBOL_WARNING "  校验错";
    if (strcmp(state, "PWM 输出无读取反馈") == 0) return LV_SYMBOL_EJECT "  无反馈";
    return state;
}

/* === v0.9.14 P0#1: 基本设备卡（主页 ESP32/LCD 共用） ===
 * 设计: 跟 v0.9.13 主页 ESP32/LCD 卡 100% 一致（card_h=76, pad=12,
 *       name y=0, param y=22, status y=46, arrow right-mid）。
 *       抽函数后 build_home 调用 2 行而不是 80 行重复。 */
lv_obj_t *ui_device_card_create(lv_obj_t *parent, int x, int y, int w, int h,
                                const char *name, const char *param,
                                const char *status_text,
                                lv_event_cb_t click_cb, void *user_data)
{
    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_set_size(card, w, h);
    lv_obj_set_pos(card, x, y);
    lv_obj_set_style_bg_color(card, lv_color_hex(UI_COLOR_BG_PANEL), 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(card, 14, 0);
    lv_obj_set_style_border_color(card, lv_color_hex(UI_COLOR_BORDER), 0);
    lv_obj_set_style_border_width(card, 1, 0);
    lv_obj_set_style_pad_all(card, 12, 0);
    lv_obj_set_style_shadow_opa(card, LV_OPA_TRANSP, 0);
    lv_obj_clear_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    if (click_cb != NULL) {
        lv_obj_add_event_cb(card, click_cb, LV_EVENT_CLICKED, user_data);
        lv_obj_add_flag(card, LV_OBJ_FLAG_CLICKABLE);
    }

    /* 名称（大标题） */
    lv_obj_t *name_label = lv_label_create(card);
    lv_label_set_text(name_label, name);
    lv_obj_set_style_text_font(name_label, UI_FONT_14, 0);
    lv_obj_set_style_text_color(name_label, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
    lv_obj_set_pos(name_label, 0, 0);

    /* 副标题（参数）— 纯数字 Latin，montserrat_10 紧凑 */
    lv_obj_t *param_label = lv_label_create(card);
    lv_label_set_text(param_label, param);
    lv_obj_set_style_text_font(param_label, &lv_font_montserrat_10, 0);
    lv_obj_set_style_text_color(param_label, lv_color_hex(UI_COLOR_TEXT_MUTED), 0);
    lv_obj_set_pos(param_label, 0, 22);

    /* 状态行（中文）— v0.9.14 P0#7 修字体 bug，UI_FONT_14 */
    lv_obj_t *status_label = lv_label_create(card);
    lv_label_set_text(status_label, status_text);
    lv_obj_set_style_text_font(status_label, UI_FONT_14, 0);
    lv_obj_set_style_text_color(status_label, lv_color_hex(UI_COLOR_SUCCESS), 0);
    lv_obj_set_pos(status_label, 0, 46);

    /* 右箭头（符号） */
    lv_obj_t *arrow = lv_label_create(card);
    lv_label_set_text(arrow, LV_SYMBOL_RIGHT);
    lv_obj_set_style_text_font(arrow, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_color(arrow, lv_color_hex(UI_COLOR_ARROW_DIM), 0);
    lv_obj_align(arrow, LV_ALIGN_RIGHT_MID, 0, 0);

    return card;
}

