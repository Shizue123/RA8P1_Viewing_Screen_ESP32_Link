/* ui_theme.c - 设计系统 token 与主题 */
#include "ui_theme.h"

/* 全局样式（单例） */
static lv_style_t s_style_card;

/* v0.9.7: 切回 ui_font_sc_14/16 (NotoSansSC 全 CJK，与 d/ 路径同款) */
extern const lv_font_t ui_font_sc_14;
extern const lv_font_t ui_font_sc_16;

const lv_font_t *ui_font_xs(void)   { return &lv_font_montserrat_10; }
const lv_font_t *ui_font_sm(void)   { return &lv_font_montserrat_12; }
const lv_font_t *ui_font_md(void)   { return &ui_font_sc_14; }
const lv_font_t *ui_font_lg(void)   { return &ui_font_sc_16; }
const lv_font_t *ui_font_xl(void)   { return &lv_font_montserrat_18; }
const lv_font_t *ui_font_xxl(void)  { return &lv_font_montserrat_22; }
const lv_font_t *ui_font_mono(void) { return &lv_font_montserrat_14; }

void ui_style_card_init(void)
{
    lv_style_init(&s_style_card);
    lv_style_set_radius(&s_style_card, UI_CARD_RADIUS);
    lv_style_set_bg_color(&s_style_card, lv_color_hex(UI_COLOR_BG_PANEL));
    lv_style_set_bg_opa(&s_style_card, LV_OPA_COVER);
    lv_style_set_border_color(&s_style_card, lv_color_hex(UI_COLOR_BORDER));
    lv_style_set_border_width(&s_style_card, 1);
    lv_style_set_pad_all(&s_style_card, UI_CARD_INNER_PAD);
    lv_style_set_shadow_opa(&s_style_card, LV_OPA_TRANSP);
}

void ui_style_card_apply(lv_obj_t *obj)
{
    lv_obj_add_style(obj, &s_style_card, 0);
}

void ui_theme_apply(void)
{
    ui_style_card_init();

    /* 设置 LVGL v9 默认主题：simple light, 不然 widget 是黑色 */
    lv_theme_t *th = lv_theme_simple_init(lv_display_get_default());
    if (th != NULL) {
        lv_display_set_theme(lv_display_get_default(), th);
    }

    /* 把当前激活屏幕的背景刷成 UI 底色（其他 screen 由各自 build 时设） */
    lv_obj_t *scr = lv_screen_active();
    if (scr != NULL) {
        lv_obj_set_style_bg_color(scr, lv_color_hex(UI_COLOR_BG), 0);
    }
}
