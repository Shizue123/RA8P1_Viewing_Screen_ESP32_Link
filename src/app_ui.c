/* app_ui.c - 新版 UI 主体
 *
 * 4 个屏幕：首页 (HOME) / 硬件列表 (LIST) / 硬件详情 (DETAIL) / 标准口 (PORTS)
 * 1 个弹层：WiFi 切换
 * 全部使用中文（LVGL v9 内置 lv_font_source_han_sans_sc_14_cjk / 16_cjk）
 * 注意：lv_conf.h 中 simsun_14/16_cjk=0，source_han_sans 14/16=1
 *
 * v0.9.5: 新增 PORTS 页面
 *   - 用 lv_subject_t 观察者模式做"统一状态源本地镜像"
 *   - 4 个标准口: I2C-1 / I2C-2 / PWM-0 / UART-BRIDGE
 *   - 桥接定时器 200ms 增量刷新
 */
#include "app_ui.h"
#include "lv_port_indev.h"
#include "ui_theme.h"
#include "ui_widgets.h"

#include "aht20.h"
#include "bh1750.h"          /* v0.9.20: hal_entry.c 用 */
#include "sg90_servo.h"
#include "esp32_link.h"
#include "platform_ports.h"  /* v0.9.20: hal_entry.c 用 */
#include "device_registry.h" /* v0.9.23: 设备注册表 — 动态入口 */

#include "lvgl.h"
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <stdint.h>

/* v0.9.7: 字体改回 ui_font_sc_14 (NotoSansSC 全 CJK, 与 d/ 同款)。
   截图证明 Source Han Sans 14 CJK 在 320px 宽屏 + 现有 label 宽度下
   会把"瑞萨 RA8P1"等中文截断成单字孤岛；NotoSansSC 字宽更紧凑能装下。 */
extern const lv_font_t ui_font_sc_14;
#define UI_FONT_14 (&ui_font_sc_14)

/* v0.9.5: LVGL 9.3 lv_subject 观察者 */
#include "src/others/observer/lv_observer.h"

typedef struct st_hw_row {
    const char *k;
    const char *v;
} hw_row_t;

typedef struct st_ui_wifi_network {
    bool valid;
    bool connected;
    int16_t rssi_dbm;
    char ssid[32];
} ui_wifi_network_t;

#include "segger_rtt/SEGGER_RTT.h"

/* === 全局页面 === */
typedef enum { PG_HOME = 0, PG_LIST, PG_DETAIL, PG_PORTS } page_id_t;
static lv_obj_t *s_screens[4] = {NULL, NULL, NULL, NULL};
static page_id_t s_current_page = PG_HOME;
/* v0.9.22: 返栈 — on_back_click 时回上一个页面（从 PG_LIST 进 PG_DETAIL 回 PG_LIST；从 PG_HOME 进 PG_DETAIL 回 PG_HOME） */
#define BACK_STACK_MAX 4
static page_id_t s_back_stack[BACK_STACK_MAX] = {PG_HOME};
static int s_back_stack_top = 0;  /* 指向最后一个有效 entry */

static void push_back(page_id_t pg) {
    if (s_back_stack_top + 1 < BACK_STACK_MAX) {
        s_back_stack_top++;
        s_back_stack[s_back_stack_top] = pg;
    }
}

/* === 顶栏（共用） === */
static ui_topbar_t s_topbar = {0};

/* === WiFi 弹层 === */
static lv_obj_t *s_wifi_sheet = NULL;
static lv_obj_t *s_wifi_sheet_list = NULL;
#define UI_WIFI_MAX (12)
static ui_wifi_network_t s_wifi_networks[UI_WIFI_MAX] = {0};
static uint8_t s_wifi_network_count = 0U;
static char s_current_ssid[32] = "WiFi";

/* === 首页 widget 句柄 === */
typedef struct {
    lv_obj_t *esp_card;       /* 基本设备-ESP32 卡（可点进详情） */
    lv_obj_t *lcd_card;       /* 基本设备-LCD 卡 */
    lv_obj_t *hw_entry_card;  /* 接入硬件暖橙卡 */
    lv_obj_t *ports_card;     /* v0.9.5: 标准口暖橙卡 */
} home_widgets_t;
static home_widgets_t s_home = {0};

/* === 列表页 widget === */
typedef struct {
    lv_obj_t *list_container;
} list_widgets_t;
static list_widgets_t s_list = {0};

/* === 详情页 widget === */
typedef struct {
    lv_obj_t *root;
    lv_obj_t *title;
    lv_obj_t *status_pill;
    lv_obj_t *rows_box;       /* 容器 */
    lv_obj_t *mock_box;       /* 模拟数据开关组（含 label + switch），仅 AHT20 详情页可见 */
    lv_obj_t *mock_label;
    lv_obj_t *mock_switch;
} detail_widgets_t;
static detail_widgets_t s_detail = {0};

/* === 状态字符串缓存（仅保留兼容 API 用） === */
static char s_esp32_status[32]   = "online";
static char s_wifi_status[32]   = "connected";
static char s_wifi_name[32]     = "YOUR_WIFI_SSID";
static char s_mqtt_status[32]   = "connected";
static char s_aht20_status[16]  = "online";
static char s_aht20_meas[32]    = "26.4℃ 50.3%";
static char s_control[32]       = "";
static char s_input[32]         = "";
static char s_device_id[64]     = "";
static char s_clock_text[6]     = "00:00";
static bool s_mock_enabled = false;
static lv_timer_t *s_mock_timer = NULL;
static lv_timer_t *s_clock_timer = NULL;
static bool s_clock_valid = false;
static uint32_t s_clock_base_tick_ms = 0U;
static uint32_t s_clock_base_seconds = 0U;
/* AHT20 详情页"当前温度/当前湿度"两行的 v-label 句柄，由 detail_build_for 刷新 */
static lv_obj_t *s_aht20_detail_temp_label = NULL;
static lv_obj_t *s_aht20_detail_humidity_label = NULL;

/* v0.9.21: 当前详情页 idx + 所有 v-label 句柄缓存（支持热刷新） */
static int s_current_detail_idx = -1;
#define DETAIL_V_LABELS_MAX 8
static lv_obj_t *s_detail_v_labels[DETAIL_V_LABELS_MAX] = {NULL};
static int s_detail_v_label_count = 0;

/* ================================================================ */
/* v0.9.5: PORTS 状态源 (lv_subject 观察者)                          */
/* 全部用 STRING subject，桥接定时器用 lv_subject_snprintf /         */
/* lv_subject_copy_string 更新；label 在 build_ports 里               */
/* 用 lv_label_bind_text 一次性绑定，后续自动跟随                     */
/* ================================================================ */
static lv_subject_t s_sub_i2c1_module;
static lv_subject_t s_sub_i2c1_status;
static lv_subject_t s_sub_i2c1_temp;
static lv_subject_t s_sub_i2c1_humid;
static lv_subject_t s_sub_i2c1_cap;

static lv_subject_t s_sub_i2c2_module;
static lv_subject_t s_sub_i2c2_status;
static lv_subject_t s_sub_i2c2_light;
static lv_subject_t s_sub_i2c2_cap;

static lv_subject_t s_sub_pwm0_module;
static lv_subject_t s_sub_pwm0_status;
static lv_subject_t s_sub_pwm0_angle;
static lv_subject_t s_sub_pwm0_cap;
static lv_subject_t s_sub_pwm0_feedback;

static lv_subject_t s_sub_uart_module;
static lv_subject_t s_sub_uart_status;
static lv_subject_t s_sub_uart_wifi;
static lv_subject_t s_sub_uart_mqtt;
static lv_subject_t s_sub_uart_cap;

#define SUB_BUF(name, sz)  static char s_buf_##name[sz]; static char s_buf_##name##_prev[sz]
SUB_BUF(i2c1_module, 16);
SUB_BUF(i2c1_status, 24);
SUB_BUF(i2c1_temp,   16);
SUB_BUF(i2c1_humid,  16);
SUB_BUF(i2c1_cap,    64);
SUB_BUF(i2c2_module, 16);
SUB_BUF(i2c2_status, 24);
SUB_BUF(i2c2_light, 16);
SUB_BUF(i2c2_cap,    16);
SUB_BUF(pwm0_module, 40);
SUB_BUF(pwm0_status, 24);
SUB_BUF(pwm0_angle,   8);
SUB_BUF(pwm0_cap,    48);
SUB_BUF(pwm0_feedback, 40);
SUB_BUF(uart_module, 16);
SUB_BUF(uart_status, 16);
SUB_BUF(uart_wifi,   56);
SUB_BUF(uart_mqtt,   24);
SUB_BUF(uart_cap,    40);

static lv_timer_t *s_ports_timer = NULL;

/* ================================================================ */
/* 页面切换                                                          */
/* ================================================================ */
static void load_page(page_id_t pg)
{
    s_current_page = pg;
    /* v0.9.3.2: drop MOVE_LEFT software anim, rely on BUF_ROWS=80 partial flush
   for natural top-to-bottom page refresh (6 chunks: y=0..79, 80..159, ..., 400..479) */
    lv_screen_load(s_screens[pg]);
}


/* 前向声明 */
static void detail_build_for(int hw_idx);
static void detail_refresh_values(void);
static void on_wifi_chip_click(lv_event_t *e);
static void on_hw_esp32_click(lv_event_t *e);
static void on_hw_lcd_click(lv_event_t *e);
static void on_hw_entry_click(lv_event_t *e);
static void on_hw_ports_click(lv_event_t *e);
static void on_hw_list_item_click(lv_event_t *e);
static void on_back_click(lv_event_t *e);
static void on_wifi_sheet_close(lv_event_t *e);
static void on_wifi_item_click(lv_event_t *e);
static void on_mock_switch_toggle(lv_event_t *e);
static void mock_timer_cb(lv_timer_t *t);
static void clock_timer_cb(lv_timer_t * t);
static void build_ports(void);
static void ports_timer_cb(lv_timer_t *t);
static void refresh_wifi_sheet(void);
static void refresh_list_entries(void);
static const char * status_en_to_cn(const char * en);
static bool text_is_ascii(const char * text);
static void refresh_clock_from_base(void);
bool app_ui_is_aht20_mock(void);
/* hal_entry.c 的 AHT20 主动刷新入口（从静态改成跨文件可见，仅给 mock 关闭后立即回填真值用） */
void aht20_refresh_ui(void);

/* ================================================================ */
/* 详情页：填充内容                                                  */
/* ================================================================ */
/* v0.9.10 精简：删固定值/技术常识/接线一次性信息，保留用户视角关键参数。
   目标：所有详情页 ≤ 7 行 + 行高 40 → 总高 ≤ 324px，body 422 装得下不滚 */
/* v0.9.21: 改为 static 可写缓存，v 字段从字面量改为动态生成（esp32_link / aht20 真实数据） */
static hw_row_t esp32_rows[] = {
    {"型号", "ESP32-S3 Dev Module"},
    {"WiFi 协议", "802.11 b/g/n · 2.4 GHz"},
    {"当前 SSID", "--"},
    {"信号强度", "--"},
    {"MQTT Broker", "--"},
    {"设备编号", "--"},
    {"心跳间隔", "每 2 秒"},
};
static const hw_row_t lcd_rows[] = {
    {"型号", "ILI9488"},
    {"SIZE", "320x480"},
    {"PINS", "P515/P600/P102"},
    {"背光", "P106 GPIO"},
    {"面板", "CL40BC299"},
    {"状态", "工作正常"},
};
static const hw_row_t touch_rows[] = {
    {"型号", "FT6336 (FocalTech)"},
    {"接口", "I²C · 7-bit 0x38"},
    {"引脚分配", "SDA P400 · SCL P401 · RST P402"},
    {"原始范围", "X 28~287 · Y 56~432"},
    {"最近触摸", "320, 240"},
};
static hw_row_t aht20_rows[] = {
    {"型号", "AHT20"},
    {"接口", "I²C · 7-bit 0x38"},
    {"测量精度", "±0.3 ℃ · ±2 %RH"},
    {"当前温度", "--"},
    {"当前湿度", "--"},
    {"CRC 校验", "--"},
    {"量程", "温度 -40~85℃ · 湿度 0~100%"},
};
/* v0.9.23: BH1750 详情页 7 行 — 仿 AHT20 模板,真实 lux */
static hw_row_t bh1750_rows[] = {
    {"型号", "BH1750"},
    {"接口", "I²C · 7-bit 0x23"},
    {"测量精度", "±20 %"},
    {"当前光照", "--"},
    {"最近读数", "--"},
    {"CRC 校验", "--"},
    {"量程", "1 ~ 65535 lux"},
};

typedef struct {
    const char *key;
    const char *title;
    const char *status;
    const hw_row_t *rows;
    int row_count;
} hw_def_t;

/* v0.9.23: HW_DEFS 移除 SG90(改进.md §一-9 要求),加 BH1750 */
static const hw_def_t HW_DEFS[] = {
    {"esp32",  "ESP32-S3 网桥",  "在线 · WiFi 已连接", esp32_rows,  sizeof(esp32_rows)/sizeof(esp32_rows[0])},
    {"lcd",    "LCD 显示屏",     "在线 · 工作正常",   lcd_rows,    sizeof(lcd_rows)/sizeof(lcd_rows[0])},
    {"touch",  "触摸控制器",     "在线 · 空闲",       touch_rows,  sizeof(touch_rows)/sizeof(touch_rows[0])},
    {"aht20",  "温湿度传感器",   "在线 · 采样正常",   aht20_rows,  sizeof(aht20_rows)/sizeof(aht20_rows[0])},
    {"bh1750", "光照传感器",     "在线 · 采样正常",   bh1750_rows, sizeof(bh1750_rows)/sizeof(bh1750_rows[0])},
};
#define HW_DEFS_LEN (sizeof(HW_DEFS)/sizeof(HW_DEFS[0]))

static int find_hw_index(const char *key)
{
    for (int i = 0; i < (int)HW_DEFS_LEN; i++) {
        if (strcmp(HW_DEFS[i].key, key) == 0) return i;
    }
    return 0;
}

static bool text_is_ascii(const char * text)
{
    if (text == NULL) {
        return false;
    }

    for (size_t i = 0U; text[i] != '\0'; i++) {
        if (((unsigned char) text[i]) > 0x7FU) {
            return false;
        }
    }

    return true;
}

static void detail_build_for(int hw_idx)
{
    if (s_detail.rows_box != NULL) {
        lv_obj_clean(s_detail.rows_box);
    }
    /* 切详情时重置 AHT20 句柄：避免指向已 lv_obj_clean 删除的对象 */
    s_aht20_detail_temp_label = NULL;
    s_aht20_detail_humidity_label = NULL;
    /* v0.9.21: 详情页 v-label 句柄缓存全部清零 */
    s_detail_v_label_count = 0;
    for (int k = 0; k < DETAIL_V_LABELS_MAX; k++) s_detail_v_labels[k] = NULL;
    if (hw_idx < 0 || hw_idx >= (int)HW_DEFS_LEN) hw_idx = 0;
    s_current_detail_idx = hw_idx;  /* v0.9.21: 记录当前详情 idx 给刷新函数用 */
    const hw_def_t *hw = &HW_DEFS[hw_idx];
    lv_label_set_text(s_detail.title, hw->title);
    lv_label_set_text(s_detail.status_pill, hw->status);
    lv_obj_set_style_text_color(s_detail.status_pill, (lv_color_t){.red=0x1F, .green=0x9C, .blue=0x5A}, 0);
    /* 仅 AHT20 详情页显示"模拟数据"开关；其他硬件详情页不暴露这个开关 */
    if (s_detail.mock_box != NULL) {
        if (strcmp(hw->key, "aht20") == 0) {
            lv_obj_clear_flag(s_detail.mock_box, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(s_detail.mock_box, LV_OBJ_FLAG_HIDDEN);
        }
    }

    for (int i = 0; i < hw->row_count; i++) {
        lv_obj_t *row = lv_obj_create(s_detail.rows_box);
        /* v0.9.10: 行高 56→40 (lvgl pad 14+14 内建)，7 行 + pad_row 4 = 7×40+6×4 = 304 < 422 body */
        lv_obj_set_size(row, lv_pct(100), 40);
        lv_obj_set_style_bg_color(row, lv_color_hex(UI_COLOR_BG_PANEL), 0);
        lv_obj_set_style_bg_opa(row, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(row, 12, 0);
        lv_obj_set_style_border_color(row, lv_color_hex(UI_COLOR_BORDER), 0);
        lv_obj_set_style_border_width(row, 1, 0);
        lv_obj_set_style_border_opa(row, LV_OPA_COVER, 0);
        lv_obj_set_style_shadow_opa(row, LV_OPA_TRANSP, 0);
        lv_obj_set_style_pad_left(row, 12, 0);
        lv_obj_set_style_pad_right(row, 12, 0);
        lv_obj_set_style_pad_top(row, 0, 0);
        lv_obj_set_style_pad_bottom(row, 0, 0);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_clear_flag(row, LV_OBJ_FLAG_SCROLLABLE);

        /* k 字段：固定宽 110px，左对齐（足够装下"引脚分配"4字） */
        lv_obj_t *k = lv_label_create(row);
        lv_label_set_text(k, hw->rows[i].k);
        lv_obj_set_style_text_font(k, text_is_ascii(hw->rows[i].k) ? &lv_font_montserrat_12 : UI_FONT_14, 0);
        lv_obj_set_style_text_color(k, lv_color_hex(UI_COLOR_TEXT_DIM), 0);
        lv_obj_set_width(k, 110);
        lv_obj_set_height(k, LV_SIZE_CONTENT);
        lv_label_set_long_mode(k, LV_LABEL_LONG_CLIP);
        lv_obj_set_style_text_align(k, LV_TEXT_ALIGN_LEFT, 0);

        /* v 字段：flex 1 占据剩余空间，右对齐 */
        lv_obj_t *v = lv_label_create(row);
        lv_label_set_text(v, hw->rows[i].v);
        lv_obj_set_style_text_font(v, text_is_ascii(hw->rows[i].v) ? &lv_font_montserrat_12 : UI_FONT_14, 0);
        lv_obj_set_style_text_color(v, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
        lv_obj_set_flex_grow(v, 1);
        lv_obj_set_height(v, LV_SIZE_CONTENT);
        lv_label_set_long_mode(v, LV_LABEL_LONG_DOT);
        lv_obj_set_style_text_align(v, LV_TEXT_ALIGN_RIGHT, 0);
        /* v0.9.21: 所有 v-label 句柄缓存到 s_detail_v_labels[]，给 detail_refresh_values() 用 */
        if (s_detail_v_label_count < DETAIL_V_LABELS_MAX) {
            s_detail_v_labels[s_detail_v_label_count++] = v;
        }
        /* AHT20 详情页：把"当前温度"/"当前湿度"两行的 v-label 句柄存下来，给 mock_timer_cb 直接更新 */
        if (strcmp(hw->key, "aht20") == 0) {
            if (strcmp(hw->rows[i].k, "当前温度") == 0) {
                s_aht20_detail_temp_label = v;
            } else if (strcmp(hw->rows[i].k, "当前湿度") == 0) {
                s_aht20_detail_humidity_label = v;
            }
        }
    }
}

/* ================================================================ */
/* 首页 build                                                        */
/* ================================================================ */
static void build_home(void)
{
    lv_obj_t *scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(scr, lv_color_hex(UI_COLOR_BG), 0);
    s_screens[PG_HOME] = scr;

    s_topbar = ui_topbar_create(scr, "设备面板", s_current_ssid, on_wifi_chip_click);

    lv_obj_t *body = lv_obj_create(scr);
    lv_obj_set_pos(body, 0, UI_TOPBAR_H);
    lv_obj_set_size(body, UI_SCREEN_W, UI_SCREEN_H - UI_TOPBAR_H);
    lv_obj_set_style_bg_color(body, lv_color_hex(UI_COLOR_BG), 0);
    lv_obj_set_style_bg_opa(body, LV_OPA_COVER, 0);
    lv_obj_set_style_border_opa(body, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(body, 0, 0);
    lv_obj_clear_flag(body, LV_OBJ_FLAG_SCROLLABLE);

    /* 标题区 */
    lv_obj_t *pretitle = lv_label_create(body);
    lv_label_set_text(pretitle, "RENESAS · 2026");
    lv_obj_set_style_text_font(pretitle, &lv_font_montserrat_10, 0);
    lv_obj_set_style_text_color(pretitle, lv_color_hex(UI_COLOR_TEXT_MUTED), 0);
    lv_obj_set_pos(pretitle, 0, 22);
    lv_obj_set_size(pretitle, UI_SCREEN_W, 14);
    lv_obj_set_style_text_align(pretitle, LV_TEXT_ALIGN_CENTER, 0);

    lv_obj_t *title = lv_label_create(body);
    lv_label_set_text(title, "瑞萨 RA8P1");
    lv_obj_set_style_text_font(title, UI_FONT_14, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
    lv_obj_set_pos(title, 0, 40);
    lv_obj_set_size(title, UI_SCREEN_W, 24);
    lv_obj_set_style_text_align(title, LV_TEXT_ALIGN_CENTER, 0);
    /* v0.9.9: 去掉 SCROLL_CIRCULAR，软 SPI 460ms/帧下持续滚动会触发整页 partial flush，
       表现为"滚动回弹卡顿"。"瑞萨 RA8P1" 7 字 + 14px + width=320 不截断，用默认 CLIP 即可 */
    lv_label_set_long_mode(title, LV_LABEL_LONG_CLIP);

    lv_obj_t *sub = lv_label_create(body);
    lv_label_set_text(sub, "即插即用项目");
    lv_obj_set_style_text_font(sub, UI_FONT_14, 0);
    lv_obj_set_style_text_color(sub, lv_color_hex(UI_COLOR_TEXT_DIM), 0);
    lv_obj_set_pos(sub, 0, 66);
    lv_obj_set_size(sub, UI_SCREEN_W, 18);
    lv_obj_set_style_text_align(sub, LV_TEXT_ALIGN_CENTER, 0);

    lv_obj_t *ver = lv_obj_create(body);
    lv_obj_set_size(ver, 130, 22);
    lv_obj_set_pos(ver, (UI_SCREEN_W - 110) / 2, 90);
    lv_obj_set_style_bg_color(ver, (lv_color_t){.red=0xE5, .green=0xE5, .blue=0xEA}, 0);
    lv_obj_set_style_bg_opa(ver, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(ver, 10, 0);
    lv_obj_set_style_border_opa(ver, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(ver, 0, 0);
    lv_obj_clear_flag(ver, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t *ver_lab = lv_label_create(ver);
    lv_label_set_text(ver_lab, "v0.8 版本");
    lv_obj_set_style_text_font(ver_lab, UI_FONT_14, 0);
    lv_obj_set_style_text_color(ver_lab, lv_color_hex(UI_COLOR_TEXT_MUTED), 0);
    lv_obj_center(ver_lab);

    /* 分隔 */
    lv_obj_t *div = lv_obj_create(body);
    lv_obj_set_size(div, UI_SCREEN_W - 32, 1);
    lv_obj_set_pos(div, 16, 124);
    lv_obj_set_style_bg_color(div, lv_color_hex(UI_COLOR_DIVIDER), 0);
    lv_obj_set_style_bg_opa(div, LV_OPA_COVER, 0);
    lv_obj_set_style_border_opa(div, LV_OPA_TRANSP, 0);
    lv_obj_clear_flag(div, LV_OBJ_FLAG_SCROLLABLE);

    /* 基本设备标题 */
    lv_obj_t *sec = lv_label_create(body);
    lv_label_set_text(sec, "基本设备");
    /* v0.9.14 P0#7: 修中文字体 bug */
    lv_obj_set_style_text_font(sec, UI_FONT_14, 0);
    lv_obj_set_style_text_color(sec, lv_color_hex(UI_COLOR_TEXT_MUTED), 0);
    lv_obj_set_pos(sec, 16, 134);
    lv_obj_set_size(sec, 100, 14);

    /* 基本设备卡 — v0.9.14 P0#1: 抽 ui_device_card_create 复用函数 */
    int card_y = 152;
    int card_w = (UI_SCREEN_W - 16 * 2 - 10) / 2;
    s_home.esp_card = ui_device_card_create(body, 16, card_y, card_w, 76,
        "ESP32-S3", "115k · 8N1", ui_status_glyph("在线"),
        on_hw_esp32_click, NULL);
    s_home.lcd_card = ui_device_card_create(body, 16 + card_w + 10, card_y, card_w, 76,
        "ILI9488", "320 × 480", ui_status_glyph("在线"),
        on_hw_lcd_click, NULL);

    /* 暖橙主题卡：接入硬件 */
    s_home.hw_entry_card = ui_orange_card_create(body, 16, 240,
                                                  UI_SCREEN_W - 32, 86,
                                                  "HARDWARE", "接入硬件", "查看已插入硬件列表",
                                                  on_hw_entry_click, NULL);

    /* v0.9.5: 暖橙主题卡：标准口入口 */
    s_home.ports_card = ui_orange_card_create(body, 16, 338,
                                              UI_SCREEN_W - 32, 86,
                                              "PORTS", "端口", "查看 I2C / PWM / UART 桥接状态",
                                              on_hw_ports_click, NULL);
}

static void list_add_entry(device_registry_entry_t const * e, int hw_idx, bool online_dot)
{
    lv_obj_t *item;
    lv_obj_t *dot;
    lv_obj_t *t;
    lv_obj_t *s;
    lv_obj_t *ar;
    const char * subtitle;

    if ((s_list.list_container == NULL) || (e == NULL) || (hw_idx < 0)) {
        return;
    }

    item = lv_obj_create(s_list.list_container);
    lv_obj_set_size(item, lv_pct(100), 62);
    lv_obj_set_style_bg_color(item, lv_color_hex(UI_COLOR_BG_PANEL), 0);
    lv_obj_set_style_bg_opa(item, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(item, 12, 0);
    lv_obj_set_style_border_color(item, lv_color_hex(UI_COLOR_BORDER), 0);
    lv_obj_set_style_border_width(item, 1, 0);
    lv_obj_set_style_pad_left(item, 14, 0);
    lv_obj_set_style_pad_right(item, 14, 0);
    lv_obj_set_style_shadow_opa(item, LV_OPA_TRANSP, 0);
    lv_obj_clear_flag(item, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(item, on_hw_list_item_click, LV_EVENT_PRESSED, (void *) HW_DEFS[hw_idx].key);
    lv_obj_add_flag(item, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_ext_click_area(item, 0);

    dot = lv_obj_create(item);
    lv_obj_set_size(dot, 8, 8);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(dot, lv_color_hex(online_dot ? UI_COLOR_SUCCESS : UI_COLOR_BADGE_BG), 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
    lv_obj_set_style_border_opa(dot, LV_OPA_TRANSP, 0);
    lv_obj_align(dot, LV_ALIGN_LEFT_MID, 0, 0);

    t = lv_label_create(item);
    lv_label_set_text(t, e->title);
    lv_obj_set_style_text_font(t, UI_FONT_14, 0);
    lv_obj_set_style_text_color(t, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
    lv_obj_align(t, LV_ALIGN_LEFT_MID, 16, -8);

    subtitle = (e->subtitle[0] != '\0') ? e->subtitle : (online_dot ? "在线" : "已识别");
    s = lv_label_create(item);
    lv_label_set_text(s, subtitle);
    lv_obj_set_style_text_font(s, UI_FONT_14, 0);
    lv_obj_set_style_text_color(s, lv_color_hex(UI_COLOR_TEXT_MUTED), 0);
    lv_obj_align(s, LV_ALIGN_LEFT_MID, 16, 8);

    ar = lv_label_create(item);
    lv_label_set_text(ar, LV_SYMBOL_RIGHT);
    lv_obj_set_style_text_font(ar, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(ar, lv_color_hex(UI_COLOR_ARROW_DIM), 0);
    lv_obj_align(ar, LV_ALIGN_RIGHT_MID, 0, 0);
}

static void refresh_list_entries(void)
{
    static const char * basic_keys[] = {"esp32", "lcd", "touch"};
    static const device_class_t hw_classes[] = {
        DEVICE_CLASS_ENV_TEMP_HUMIDITY,
        DEVICE_CLASS_ENV_LIGHT,
    };

    if (s_list.list_container == NULL) {
        return;
    }

    lv_obj_clean(s_list.list_container);

    lv_obj_t * basic_title = lv_label_create(s_list.list_container);
    lv_label_set_text(basic_title, "基本设备");
    lv_obj_set_style_text_font(basic_title, UI_FONT_14, 0);
    lv_obj_set_style_text_color(basic_title, lv_color_hex(UI_COLOR_TEXT_DIM), 0);
    lv_obj_set_size(basic_title, lv_pct(100), 22);
    lv_obj_set_style_pad_left(basic_title, 4, 0);

    for (size_t k = 0; k < sizeof(basic_keys)/sizeof(basic_keys[0]); k++) {
        device_registry_entry_t const * e = device_registry_get_by_key(basic_keys[k]);
        if (e == NULL) {
            continue;
        }
        list_add_entry(e, find_hw_index(e->key), true);
    }

    lv_obj_t * hw_title = lv_label_create(s_list.list_container);
    lv_label_set_text(hw_title, "插入硬件");
    lv_obj_set_style_text_font(hw_title, UI_FONT_14, 0);
    lv_obj_set_style_text_color(hw_title, lv_color_hex(UI_COLOR_TEXT_DIM), 0);
    lv_obj_set_size(hw_title, lv_pct(100), 22);
    lv_obj_set_style_pad_left(hw_title, 4, 0);

    for (size_t c = 0; c < sizeof(hw_classes)/sizeof(hw_classes[0]); c++) {
        size_t count = device_registry_get_count_by_class(hw_classes[c]);
        for (size_t i = 0; i < count; i++) {
            device_registry_entry_t const * e = device_registry_get_by_class(hw_classes[c], i);
            if ((e == NULL) || !e->present) {
                continue;
            }
            list_add_entry(e, find_hw_index(e->key), e->online);
        }
    }
}

/* ================================================================ */
/* 列表页 build                                                     */
/* ================================================================ */
static void build_list(void)
{
    lv_obj_t *scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(scr, lv_color_hex(UI_COLOR_BG), 0);
    s_screens[PG_LIST] = scr;

    lv_obj_t *bar = lv_obj_create(scr);
    lv_obj_set_pos(bar, 0, 0);
    lv_obj_set_size(bar, UI_SCREEN_W, UI_TOPBAR_H);
    lv_obj_set_style_bg_color(bar, (lv_color_t){.red=0xFF, .green=0xFF, .blue=0xFF}, 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_set_style_border_side(bar, LV_BORDER_SIDE_BOTTOM, 0);
    lv_obj_set_style_border_color(bar, lv_color_hex(UI_COLOR_BORDER), 0);
    lv_obj_set_style_border_width(bar, 1, 0);
    lv_obj_set_style_pad_all(bar, 0, 0);
    lv_obj_clear_flag(bar, LV_OBJ_FLAG_SCROLLABLE);

    /* 整条 bar 也 clickable: 点 bar 任何位置都触发 on_back_click */
    lv_obj_add_event_cb(bar, on_back_click, LV_EVENT_CLICKED, NULL);
    lv_obj_add_flag(bar, LV_OBJ_FLAG_CLICKABLE);

    lv_obj_t *back = lv_label_create(bar);
    lv_label_set_text(back, LV_SYMBOL_LEFT "  返回");
    lv_obj_set_style_text_font(back, UI_FONT_14, 0);
    lv_obj_set_style_text_color(back, lv_color_hex(UI_COLOR_ACCENT), 0);
    lv_obj_set_pos(back, 8, 12);
    /* 扩大点击区：label 实际 80x20，但点击可命中 110x44 */
    lv_obj_set_size(back, 110, 44);
    lv_obj_set_ext_click_area(back, 10);
    lv_obj_add_event_cb(back, on_back_click, LV_EVENT_CLICKED, NULL);
    lv_obj_add_flag(back, LV_OBJ_FLAG_CLICKABLE);

    lv_obj_t *title = lv_label_create(bar);
    lv_label_set_text(title, "接入硬件");
    lv_obj_set_style_text_font(title, UI_FONT_14, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
    lv_obj_set_pos(title, 60, 12);
    lv_obj_set_size(title, UI_SCREEN_W - 130, 22);
    lv_obj_set_style_text_align(title, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_long_mode(title, LV_LABEL_LONG_SCROLL_CIRCULAR);

    s_list.list_container = lv_obj_create(scr);
    lv_obj_set_pos(s_list.list_container, 0, UI_TOPBAR_H);
    lv_obj_set_size(s_list.list_container, UI_SCREEN_W, UI_SCREEN_H - UI_TOPBAR_H);
    lv_obj_set_style_bg_color(s_list.list_container, lv_color_hex(UI_COLOR_BG), 0);
    lv_obj_set_style_bg_opa(s_list.list_container, LV_OPA_COVER, 0);
    lv_obj_set_style_border_opa(s_list.list_container, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(s_list.list_container, 14, 0);
    lv_obj_set_style_pad_top(s_list.list_container, 8, 0);
    lv_obj_set_style_pad_row(s_list.list_container, 8, 0);
    lv_obj_set_flex_flow(s_list.list_container, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(s_list.list_container, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    /* v0.9.25: 当前 5 张卡可完整装下；关滚动以避免触摸被判成拖动，提升命中稳定性 */
    lv_obj_clear_flag(s_list.list_container, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_clear_flag(s_list.list_container, LV_OBJ_FLAG_SCROLL_ELASTIC);
    lv_obj_clear_flag(s_list.list_container, LV_OBJ_FLAG_SCROLL_MOMENTUM);
    lv_obj_set_scrollbar_mode(s_list.list_container, LV_SCROLLBAR_MODE_OFF);
    lv_obj_set_scroll_dir(s_list.list_container, LV_DIR_NONE);
    refresh_list_entries();
}

/* ================================================================ */
/* 详情页 build                                                     */
/* ================================================================ */
static void build_detail(void)
{
    lv_obj_t *scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(scr, lv_color_hex(UI_COLOR_BG), 0);
    s_screens[PG_DETAIL] = scr;

    lv_obj_t *bar = lv_obj_create(scr);
    lv_obj_set_pos(bar, 0, 0);
    lv_obj_set_size(bar, UI_SCREEN_W, UI_TOPBAR_H);
    lv_obj_set_style_bg_color(bar, (lv_color_t){.red=0xFF, .green=0xFF, .blue=0xFF}, 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_set_style_border_side(bar, LV_BORDER_SIDE_BOTTOM, 0);
    lv_obj_set_style_border_color(bar, lv_color_hex(UI_COLOR_BORDER), 0);
    lv_obj_set_style_border_width(bar, 1, 0);
    lv_obj_set_style_pad_all(bar, 0, 0);
    lv_obj_clear_flag(bar, LV_OBJ_FLAG_SCROLLABLE);

    /* 整条 bar 也 clickable: 点 bar 任何位置都触发 on_back_click */
    lv_obj_add_event_cb(bar, on_back_click, LV_EVENT_CLICKED, NULL);
    lv_obj_add_flag(bar, LV_OBJ_FLAG_CLICKABLE);

    lv_obj_t *back = lv_label_create(bar);
    lv_label_set_text(back, LV_SYMBOL_LEFT "  返回");
    lv_obj_set_style_text_font(back, UI_FONT_14, 0);
    lv_obj_set_style_text_color(back, lv_color_hex(UI_COLOR_ACCENT), 0);
    lv_obj_set_pos(back, 8, 12);
    /* 扩大点击区：label 实际 80x20，但点击可命中 110x44 */
    lv_obj_set_size(back, 110, 44);
    lv_obj_set_ext_click_area(back, 10);
    lv_obj_add_event_cb(back, on_back_click, LV_EVENT_CLICKED, NULL);
    lv_obj_add_flag(back, LV_OBJ_FLAG_CLICKABLE);

    s_detail.title = lv_label_create(bar);
    lv_label_set_text(s_detail.title, "硬件详情");
    lv_obj_set_style_text_font(s_detail.title, UI_FONT_14, 0);
    lv_obj_set_style_text_color(s_detail.title, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
    lv_obj_set_pos(s_detail.title, 80, 13);
    lv_obj_set_size(s_detail.title, UI_SCREEN_W - 160, 20);
    lv_obj_set_style_text_align(s_detail.title, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_long_mode(s_detail.title, LV_LABEL_LONG_SCROLL_CIRCULAR);

    s_detail.root = lv_obj_create(scr);
    lv_obj_set_pos(s_detail.root, 0, UI_TOPBAR_H);
    lv_obj_set_size(s_detail.root, UI_SCREEN_W, UI_SCREEN_H - UI_TOPBAR_H);
    /* 临时变量避免 lv_color_hex() 的 aggregate-return 警告 */
    lv_color_t bg_color = (lv_color_t){.red=(uint8_t)(UI_COLOR_BG>>16), .green=(uint8_t)(UI_COLOR_BG>>8), .blue=(uint8_t)UI_COLOR_BG};
    lv_obj_set_style_bg_color(s_detail.root, bg_color, 0);
    lv_obj_set_style_bg_opa(s_detail.root, LV_OPA_COVER, 0);
    lv_obj_set_style_border_opa(s_detail.root, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(s_detail.root, 14, 0);
    lv_obj_set_flex_flow(s_detail.root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(s_detail.root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    /* v0.9.9: 关滚动 — 详情页最长 ESP32 10 行 ≈ 274 < 422 body padding 装得下 */
    lv_obj_clear_flag(s_detail.root, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_clear_flag(s_detail.root, LV_OBJ_FLAG_SCROLL_ELASTIC);
    lv_obj_clear_flag(s_detail.root, LV_OBJ_FLAG_SCROLL_MOMENTUM);
    lv_obj_set_scrollbar_mode(s_detail.root, LV_SCROLLBAR_MODE_OFF);
    lv_obj_set_scroll_dir(s_detail.root, LV_DIR_NONE);

    /* 顶部行：左 status_pill，右 mock_box（仅 AHT20 详情页可见，默认隐藏） */
    lv_obj_t *top_row = lv_obj_create(s_detail.root);
    lv_obj_remove_style_all(top_row);
    lv_obj_set_size(top_row, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(top_row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(top_row, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_clear_flag(top_row, LV_OBJ_FLAG_SCROLLABLE);

    s_detail.status_pill = lv_label_create(top_row);
    /* v0.9.14 P1#8: 状态字走 ui_status_glyph，符号 + 中文冗余 */
    lv_label_set_text(s_detail.status_pill, ui_status_glyph("在线"));
    /* v0.9.14 P0#7: 修中文字体 bug + P2#2 颜色 token 化 */
    lv_obj_set_style_text_font(s_detail.status_pill, UI_FONT_14, 0);
    lv_obj_set_style_text_color(s_detail.status_pill, lv_color_hex(UI_COLOR_BADGE_TEXT), 0);
    lv_obj_set_style_bg_color(s_detail.status_pill, lv_color_hex(UI_COLOR_BADGE_BG), 0);
    lv_obj_set_style_bg_opa(s_detail.status_pill, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_left(s_detail.status_pill, 10, 0);
    lv_obj_set_style_pad_right(s_detail.status_pill, 10, 0);
    lv_obj_set_style_pad_top(s_detail.status_pill, 3, 0);
    lv_obj_set_style_pad_bottom(s_detail.status_pill, 3, 0);
    lv_obj_set_style_radius(s_detail.status_pill, 10, 0);
    lv_obj_set_size(s_detail.status_pill, LV_SIZE_CONTENT, 22);

    /* 模拟数据 开关组（label + switch 同行，靠右） */
    s_detail.mock_box = lv_obj_create(top_row);
    lv_obj_remove_style_all(s_detail.mock_box);
    lv_obj_set_size(s_detail.mock_box, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(s_detail.mock_box, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(s_detail.mock_box, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(s_detail.mock_box, 8, 0);
    lv_obj_clear_flag(s_detail.mock_box, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(s_detail.mock_box, LV_OBJ_FLAG_HIDDEN);

    s_detail.mock_label = lv_label_create(s_detail.mock_box);
    lv_label_set_text(s_detail.mock_label, "模拟数据");
    lv_obj_set_style_text_font(s_detail.mock_label, UI_FONT_14, 0);
    lv_obj_set_style_text_color(s_detail.mock_label, lv_color_hex(UI_COLOR_TEXT_DIM), 0);

    s_detail.mock_switch = lv_switch_create(s_detail.mock_box);
    lv_obj_set_size(s_detail.mock_switch, 48, 24);
    lv_obj_add_event_cb(s_detail.mock_switch, on_mock_switch_toggle, LV_EVENT_VALUE_CHANGED, NULL);

    s_detail.rows_box = lv_obj_create(s_detail.root);
    lv_obj_set_size(s_detail.rows_box, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(s_detail.rows_box, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_opa(s_detail.rows_box, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(s_detail.rows_box, 0, 0);
    lv_obj_set_flex_flow(s_detail.rows_box, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(s_detail.rows_box, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    /* v0.9.10: pad_row 6→4，每行省 2px */
    lv_obj_set_style_pad_row(s_detail.rows_box, 4, 0);
    /* v0.9.9: rows_box 跟随 root 不滚动 */
    lv_obj_clear_flag(s_detail.rows_box, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(s_detail.rows_box, LV_DIR_NONE);
}

/* ================================================================ */
/* WiFi 弹层                                                         */
/* ================================================================ */
static void on_wifi_sheet_close(lv_event_t *e)
{
    (void)e;  /* keep */
    if (s_wifi_sheet != NULL) lv_obj_add_flag(s_wifi_sheet, LV_OBJ_FLAG_HIDDEN);
}

static void on_wifi_item_click(lv_event_t *e)
{
    int idx = (int)(intptr_t)lv_event_get_user_data(e);
    if (idx < 0 || idx >= (int)s_wifi_network_count) return;
    if (!s_wifi_networks[idx].valid || s_wifi_networks[idx].ssid[0] == '\0') return;

    strncpy(s_current_ssid, s_wifi_networks[idx].ssid, sizeof(s_current_ssid) - 1);
    s_current_ssid[sizeof(s_current_ssid) - 1] = '\0';
    ui_topbar_set_left_label(&s_topbar, s_current_ssid);
    on_wifi_sheet_close(NULL);
    esp32_link_request_wifi_connect(s_current_ssid);
}

static void refresh_wifi_sheet(void)
{
    if (s_wifi_sheet_list == NULL) {
        return;
    }

    lv_obj_clean(s_wifi_sheet_list);

    if (s_wifi_network_count == 0U) {
        lv_obj_t *empty = lv_label_create(s_wifi_sheet_list);
        lv_label_set_text(empty, "正在扫描 WiFi...");
        lv_obj_set_style_text_font(empty, UI_FONT_14, 0);
        lv_obj_set_style_text_color(empty, lv_color_hex(UI_COLOR_TEXT_MUTED), 0);
        lv_obj_set_width(empty, lv_pct(100));
        lv_obj_set_style_text_align(empty, LV_TEXT_ALIGN_CENTER, 0);
        return;
    }

    for (uint8_t i = 0U; i < s_wifi_network_count; i++) {
        lv_obj_t *item = lv_obj_create(s_wifi_sheet_list);
        lv_obj_set_size(item, lv_pct(100), 50);
        lv_obj_set_style_bg_color(item, (lv_color_t){.red=0xF7, .green=0xF8, .blue=0xFB}, 0);
        lv_obj_set_style_bg_opa(item, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(item, 10, 0);
        lv_obj_set_style_border_opa(item, LV_OPA_TRANSP, 0);
        lv_obj_set_style_pad_left(item, 14, 0);
        lv_obj_set_style_pad_right(item, 14, 0);
        lv_obj_set_style_shadow_opa(item, LV_OPA_TRANSP, 0);
        lv_obj_clear_flag(item, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_add_event_cb(item, on_wifi_item_click, LV_EVENT_CLICKED, (void *)(intptr_t)i);
        lv_obj_add_flag(item, LV_OBJ_FLAG_CLICKABLE);

        lv_obj_t *name = lv_label_create(item);
        lv_label_set_text(name, s_wifi_networks[i].ssid);
        lv_obj_set_style_text_font(name, &lv_font_montserrat_14, 0);
        lv_obj_set_style_text_color(name, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
        lv_obj_align(name, LV_ALIGN_LEFT_MID, 0, 0);

        lv_obj_t *rssi = lv_label_create(item);
        if (s_wifi_networks[i].connected) {
            lv_label_set_text(rssi, "已连接");
        } else {
            char rssi_buf[20];
            snprintf(rssi_buf, sizeof(rssi_buf), "%d dBm", (int)s_wifi_networks[i].rssi_dbm);
            lv_label_set_text(rssi, rssi_buf);
        }
        lv_obj_set_style_text_font(rssi, &lv_font_montserrat_10, 0);
        lv_obj_set_style_text_color(rssi, lv_color_hex(UI_COLOR_TEXT_MUTED), 0);
        lv_obj_align(rssi, LV_ALIGN_RIGHT_MID, 0, 0);
    }
}

static void build_wifi_sheet(void)
{
    s_wifi_sheet = lv_obj_create(lv_layer_top());
    lv_obj_set_size(s_wifi_sheet, UI_SCREEN_W, UI_SCREEN_H);
    lv_obj_set_pos(s_wifi_sheet, 0, 0);
    lv_obj_set_style_bg_color(s_wifi_sheet, (lv_color_t){.red=0x00, .green=0x00, .blue=0x00}, 0);
    lv_obj_set_style_bg_opa(s_wifi_sheet, LV_OPA_50, 0);
    lv_obj_set_style_border_opa(s_wifi_sheet, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(s_wifi_sheet, 0, 0);
    lv_obj_add_event_cb(s_wifi_sheet, on_wifi_sheet_close, LV_EVENT_CLICKED, NULL);
    lv_obj_add_flag(s_wifi_sheet, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(s_wifi_sheet, LV_OBJ_FLAG_HIDDEN);

    lv_obj_t *sheet = lv_obj_create(s_wifi_sheet);
    lv_obj_set_size(sheet, UI_SCREEN_W, 320);
    lv_obj_set_pos(sheet, 0, UI_SCREEN_H - 320);
    lv_obj_set_style_bg_color(sheet, (lv_color_t){.red=0xFF, .green=0xFF, .blue=0xFF}, 0);
    lv_obj_set_style_bg_opa(sheet, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(sheet, 16, 0);
    lv_obj_set_style_border_opa(sheet, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(sheet, 14, 0);
    lv_obj_set_flex_flow(sheet, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(sheet, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    /* v0.9.9: 关滚动 — 4 项 WiFi 总高 < 280, sheet 320 装得下 */
    lv_obj_clear_flag(sheet, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_clear_flag(sheet, LV_OBJ_FLAG_SCROLL_ELASTIC);
    lv_obj_clear_flag(sheet, LV_OBJ_FLAG_SCROLL_MOMENTUM);
    lv_obj_set_scrollbar_mode(sheet, LV_SCROLLBAR_MODE_OFF);
    lv_obj_set_scroll_dir(sheet, LV_DIR_NONE);

    lv_obj_t *handle = lv_obj_create(sheet);
    lv_obj_set_size(handle, 36, 4);
    lv_obj_set_style_bg_color(handle, lv_color_hex(UI_COLOR_BORDER), 0);
    lv_obj_set_style_radius(handle, 2, 0);
    lv_obj_set_style_border_opa(handle, LV_OPA_TRANSP, 0);
    lv_obj_clear_flag(handle, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *tt = lv_label_create(sheet);
    lv_label_set_text(tt, "选择 WiFi");
    lv_obj_set_style_text_font(tt, UI_FONT_14, 0);
    lv_obj_set_style_text_color(tt, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
    lv_obj_set_size(tt, lv_pct(100), 24);

    s_wifi_sheet_list = lv_obj_create(sheet);
    lv_obj_set_size(s_wifi_sheet_list, lv_pct(100), 220);
    lv_obj_set_style_bg_opa(s_wifi_sheet_list, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_opa(s_wifi_sheet_list, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(s_wifi_sheet_list, 0, 0);
    lv_obj_set_style_pad_row(s_wifi_sheet_list, 8, 0);
    lv_obj_set_flex_flow(s_wifi_sheet_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(s_wifi_sheet_list, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_scrollbar_mode(s_wifi_sheet_list, LV_SCROLLBAR_MODE_ACTIVE);
    lv_obj_set_scroll_dir(s_wifi_sheet_list, LV_DIR_VER);

    refresh_wifi_sheet();
}

/* ================================================================ */
/* 事件回调实现                                                     */
/* ================================================================ */
static void on_wifi_chip_click(lv_event_t *e)
{
    (void)e;  /* keep */
    if (s_wifi_sheet == NULL) build_wifi_sheet();
    lv_obj_clear_flag(s_wifi_sheet, LV_OBJ_FLAG_HIDDEN);
    esp32_link_request_wifi_scan();
}

static void on_hw_esp32_click(lv_event_t *e)
{
    SEGGER_RTT_WriteString(0, "[click] on_hw_esp32_click\n");
    push_back(PG_HOME);
    detail_build_for(find_hw_index("esp32"));
    load_page(PG_DETAIL);
}

static void on_hw_lcd_click(lv_event_t *e)
{
    (void)e;  /* keep */
    push_back(PG_HOME);
    detail_build_for(find_hw_index("lcd"));
    load_page(PG_DETAIL);
}

static void on_hw_entry_click(lv_event_t *e)
{
    (void)e;  /* keep */
    refresh_list_entries();
    push_back(PG_HOME);
    load_page(PG_LIST);
}

static void on_hw_ports_click(lv_event_t *e)
{
    (void)e;  /* keep */
    push_back(PG_HOME);
    load_page(PG_PORTS);
}

static void on_hw_list_item_click(lv_event_t *e)
{
    const char * key = (const char *) lv_event_get_user_data(e);
    int idx = find_hw_index(key);
    if (idx < 0 || idx >= (int)HW_DEFS_LEN) idx = 0;
    push_back(PG_LIST);
    detail_build_for(idx);
    load_page(PG_DETAIL);
}

static void on_back_click(lv_event_t *e)
{
    (void)e;
    SEGGER_RTT_WriteString(0, "[click] on_back_click\n");
    /* v0.9.22: 用 back stack 回到上一个页面, 没记录就回首页 */
    if (s_back_stack_top > 0) {
        page_id_t prev = s_back_stack[s_back_stack_top];
        s_back_stack_top--;
        load_page(prev);
    } else {
        load_page(PG_HOME);
    }
}

/* === AHT20 详情页"模拟数据"开关回调 === */
static void on_mock_switch_toggle(lv_event_t *e)
{
    lv_obj_t *sw = lv_event_get_target(e);
    bool on = lv_obj_has_state(sw, LV_STATE_CHECKED);
    s_mock_enabled = on;

    if (on) {
        if (s_mock_timer == NULL) {
            s_mock_timer = lv_timer_create(mock_timer_cb, 200, NULL);
        }
        if (s_detail.status_pill != NULL) {
            lv_label_set_text(s_detail.status_pill, "mock sin");
        }
        SEGGER_RTT_WriteString(0, "[mock] enabled\n");
    } else {
        if (s_mock_timer != NULL) {
            lv_timer_delete(s_mock_timer);
            s_mock_timer = NULL;
        }
        if (s_detail.status_pill != NULL) {
            lv_label_set_text(s_detail.status_pill, "online");
        }
        aht20_refresh_ui();
        detail_refresh_values();  /* v0.9.21: mock 关时把详情页 label 同步成真值 */
        SEGGER_RTT_WriteString(0, "[mock] disabled\n");
    }
}

/* v0.9.21: 详情页 label 实时刷新 — 从 aht20_last / esp32_link 读真值，
 * 写到 v-label。在 mock 关闭 / AHT20 2s 轮询 / ESP32 状态变化时调用。 */
static void detail_refresh_values(void)
{
    int idx = s_current_detail_idx;
    if (idx < 0 || idx >= (int)HW_DEFS_LEN) return;
    const hw_def_t *hw = &HW_DEFS[idx];

    /* === AHT20 详情页：从 aht20_last() 真值刷新 === */
    if (strcmp(hw->key, "aht20") == 0) {
        aht20_sample_t s;
        bool got = aht20_last(&s);
        for (int i = 0; i < hw->row_count && i < s_detail_v_label_count; i++) {
            if (s_detail_v_labels[i] == NULL) continue;
            if (strcmp(hw->rows[i].k, "当前温度") == 0) {
                if (got) {
                    int32_t t10 = (int32_t)(s.temperature_c * 10.0f + (s.temperature_c >= 0 ? 0.5f : -0.5f));
                    if (t10 < 0) t10 = -t10;
                    char buf[16];
                    snprintf(buf, sizeof(buf), "%ld.%ld ℃", (long)(t10 / 10), (long)(t10 % 10));
                    lv_label_set_text(s_detail_v_labels[i], buf);
                } else {
                    lv_label_set_text(s_detail_v_labels[i], "--");
                }
            } else if (strcmp(hw->rows[i].k, "当前湿度") == 0) {
                if (got) {
                    int32_t h10 = (int32_t)(s.humidity_rh * 10.0f + (s.humidity_rh >= 0 ? 0.5f : -0.5f));
                    if (h10 < 0) h10 = 0;
                    char buf[16];
                    snprintf(buf, sizeof(buf), "%ld.%ld %%", (long)(h10 / 10), (long)(h10 % 10));
                    lv_label_set_text(s_detail_v_labels[i], buf);
                } else {
                    lv_label_set_text(s_detail_v_labels[i], "--");
                }
            } else if (strcmp(hw->rows[i].k, "CRC 校验") == 0) {
                const char * crc_text = got ? (s.crc_ok ? "通过" : "失败") : "无读";
                lv_label_set_text(s_detail_v_labels[i], crc_text);
            }
        }
        return;
    }

    /* === ESP32 详情页：从 s_wifi_name / esp32_link_is_online 刷 === */
    if (strcmp(hw->key, "esp32") == 0) {
        for (int i = 0; i < hw->row_count && i < s_detail_v_label_count; i++) {
            if (s_detail_v_labels[i] == NULL) continue;
            if (strcmp(hw->rows[i].k, "当前 SSID") == 0) {
                const char * ssid = (s_wifi_name[0] != '\0') ? s_wifi_name : "--";
                lv_label_set_text(s_detail_v_labels[i], ssid);
            } else if (strcmp(hw->rows[i].k, "信号强度") == 0) {
                lv_label_set_text(s_detail_v_labels[i], "实时未读");
            } else if (strcmp(hw->rows[i].k, "MQTT Broker") == 0) {
                lv_label_set_text(s_detail_v_labels[i],
                                  esp32_link_is_online() ? "已上报 · 见云端" : "--");
            } else if (strcmp(hw->rows[i].k, "设备编号") == 0) {
                lv_label_set_text(s_detail_v_labels[i], s_device_id[0] ? s_device_id : "--");
            } else if (strcmp(hw->rows[i].k, "心跳间隔") == 0) {
                lv_label_set_text(s_detail_v_labels[i], "2 秒");
            }
        }
        return;
    }

    /* v0.9.23: BH1750 详情页 — 从 bh1750_last() 真值刷新当前光照/最近读数/CRC */
    if (strcmp(hw->key, "bh1750") == 0) {
        bh1750_sample_t s;
        bool got = bh1750_last(&s);
        for (int i = 0; i < hw->row_count && i < s_detail_v_label_count; i++) {
            if (s_detail_v_labels[i] == NULL) continue;
            if (strcmp(hw->rows[i].k, "当前光照") == 0) {
                if (got) {
                    char buf[16];
                    snprintf(buf, sizeof(buf), "%ld lux", (long)s.lux);
                    lv_label_set_text(s_detail_v_labels[i], buf);
                } else {
                    lv_label_set_text(s_detail_v_labels[i], "--");
                }
            } else if (strcmp(hw->rows[i].k, "最近读数") == 0) {
                if (got) {
                    char buf[16];
                    snprintf(buf, sizeof(buf), "%ld", (long)s.lux);
                    lv_label_set_text(s_detail_v_labels[i], buf);
                } else {
                    lv_label_set_text(s_detail_v_labels[i], "--");
                }
            } else if (strcmp(hw->rows[i].k, "CRC 校验") == 0) {
                const char * crc_text = got ? (bh1750_last_diag() == BH1750_DIAG_OK ? "通过" : "失败") : "无读";
                lv_label_set_text(s_detail_v_labels[i], crc_text);
            }
        }
        return;
    }
    /* v0.9.23: SG90 详情页已删除 — 改进.md §一-9 要求 */
    /* LCD / touch 详情页：v 全静态，不刷新 */
}

/* === 200ms lv_timer 回调：sin 波形驱动 AHT20 详情页两行 === */
static void mock_timer_cb(lv_timer_t *t)
{
    (void)t;
    if (!s_mock_enabled) {
        return;
    }
    float t_seconds = (float) lv_tick_get() / 1000.0f;
    float temp_f     = 24.0f + 1.5f * sinf(t_seconds / 3.0f);
    float humidity_f = 45.0f + 8.0f * sinf(t_seconds / 3.0f + 0.7f);
    int32_t temp_tenths = (int32_t) (temp_f >= 0.0f ? (temp_f * 10.0f + 0.5f) : (temp_f * 10.0f - 0.5f));
    int32_t hum_tenths  = (int32_t) (humidity_f * 10.0f + 0.5f);

    char buf[32];
    if (s_aht20_detail_temp_label != NULL) {
        (void) snprintf(buf, sizeof(buf), "%ld.%ld C",
                (long) (temp_tenths / 10),
                (long) (labs((long) (temp_tenths % 10))));
        lv_label_set_text(s_aht20_detail_temp_label, buf);
    }
    if (s_aht20_detail_humidity_label != NULL) {
        (void) snprintf(buf, sizeof(buf), "%ld.%ld %%",
                (long) (hum_tenths / 10),
                (long) (hum_tenths % 10));
        lv_label_set_text(s_aht20_detail_humidity_label, buf);
    }
}

static void refresh_clock_from_base(void)
{
    uint32_t elapsed_seconds;
    uint32_t total_seconds;
    uint32_t hour;
    uint32_t minute;

    if (!s_clock_valid) {
        return;
    }

    elapsed_seconds = (lv_tick_get() - s_clock_base_tick_ms) / 1000U;
    total_seconds = (s_clock_base_seconds + elapsed_seconds) % 86400U;
    hour = total_seconds / 3600U;
    minute = (total_seconds % 3600U) / 60U;
    snprintf(s_clock_text, sizeof(s_clock_text), "%02lu:%02lu", (unsigned long) hour, (unsigned long) minute);
    ui_topbar_set_time(&s_topbar, s_clock_text);
}

static void clock_timer_cb(lv_timer_t * t)
{
    (void) t;
    refresh_clock_from_base();
}

bool app_ui_is_aht20_mock(void)
{
    return s_mock_enabled;
}

/* ================================================================ */
/* v0.9.5: 标准口页面 (PORTS)                                        */
/*                                                                   */
/* 4 张卡：I2C-1 / I2C-2 / PWM-0 / UART-BRIDGE                      */
/* 每张卡内部布局：                                                  */
/*   [●  状态]   标题: 物理口 (e.g. "I2C-1")                        */
/*               模块: "AHT20" / "empty" / "SG90" / "ESP32-S3"      */
/*               数值: 温度 23.5℃  湿度 50.3%  (I2C-1 专用)         */
/*                     角度 90° (PWM-0 专用)                         */
/*                     WiFi/MQTT (UART-BRIDGE 专用)                  */
/*               能力: env.temperature / env.humidity  (Latin 10px)  */
/*                                                                   */
/* 文本 label 全部用 lv_label_bind_text 绑到 STRING subject；         */
/* 桥接定时器 200ms 调 lv_subject_snprintf/copy_string 增量刷新。    */
/* ================================================================ */

/* 构建一张端口卡；返回 root 容器 (用于调试定位，非必须) */
/* v0.9.13: 完整简化版 — 全部单 label + 绝对定位, 无嵌套 obj
   高度 96, 5 行布局（行间留 20px 间距, 不重叠）：
     title   (y=4,  h=18) 左 60% 宽
     status  (y=4,  h=18) 右 40% 宽, 右对齐
     module  (y=24, h=16) 全宽
     v1      (y=44, h=18) prefix 56px + value 剩余
     v2      (y=64, h=18) prefix 56px + value 剩余
     cap     (y=84, h=10) Latin 10px
   所有 label 用 LV_LABEL_LONG_DOT 截断保护 */
static lv_obj_t *build_ports_card(lv_obj_t *parent, int x, int y, int w, int h,
                                  const char *physical_port,
                                  lv_subject_t *sub_module,
                                  lv_subject_t *sub_status,
                                  lv_subject_t *sub_value,
                                  const char *value_prefix,
                                  lv_subject_t *sub_value2,
                                  const char *value2_prefix,
                                  lv_subject_t *sub_cap)
{
    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_set_size(card, w, h);
    lv_obj_set_pos(card, x, y);
    lv_obj_set_style_bg_color(card, lv_color_hex(UI_COLOR_BG_PANEL), 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(card, UI_CARD_RADIUS, 0);
    lv_obj_set_style_border_color(card, lv_color_hex(UI_COLOR_BORDER), 0);
    lv_obj_set_style_border_width(card, 1, 0);
    lv_obj_set_style_pad_all(card, 8, 0);
    lv_obj_set_style_shadow_opa(card, LV_OPA_TRANSP, 0);
    lv_obj_clear_flag(card, LV_OBJ_FLAG_SCROLLABLE);

    int inner_w = w - 16;  /* 8 pad 两侧 */
    int prefix_w = 132;
    int title_w = (inner_w * 6) / 10;
    int status_w = inner_w - title_w;

    /* title (左) y=4 */
    lv_obj_t *title = lv_label_create(card);
    lv_label_set_text(title, physical_port);
    lv_obj_set_style_text_font(title, UI_FONT_14, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
    lv_obj_set_pos(title, 0, 4);
    lv_obj_set_size(title, title_w, 18);
    lv_label_set_long_mode(title, LV_LABEL_LONG_DOT);

    /* status (右) y=4 */
    lv_obj_t *status = lv_label_create(card);
    lv_obj_set_style_text_font(status, UI_FONT_14, 0);
    lv_obj_set_style_text_color(status, lv_color_hex(0x1F9C5A), 0);
    lv_obj_set_pos(status, title_w, 4);
    lv_obj_set_size(status, status_w, 18);
    lv_obj_set_style_text_align(status, LV_TEXT_ALIGN_RIGHT, 0);
    lv_label_set_long_mode(status, LV_LABEL_LONG_DOT);
    lv_label_bind_text(status, sub_status, NULL);

    /* module (y=24) */
    lv_obj_t *module = lv_label_create(card);
    lv_obj_set_style_text_font(module, UI_FONT_14, 0);
    lv_obj_set_style_text_color(module, lv_color_hex(UI_COLOR_TEXT_DIM), 0);
    lv_obj_set_pos(module, 0, 24);
    lv_obj_set_size(module, inner_w, 16);
    lv_label_set_long_mode(module, LV_LABEL_LONG_DOT);
    lv_label_bind_text(module, sub_module, NULL);

    /* v1 (y=44) */
    if (sub_value != NULL) {
        lv_obj_t *prefix1 = lv_label_create(card);
        lv_label_set_text(prefix1, value_prefix);
        lv_obj_set_style_text_font(prefix1, UI_FONT_14, 0);
        lv_obj_set_style_text_color(prefix1, lv_color_hex(UI_COLOR_TEXT_MUTED), 0);
        lv_obj_set_pos(prefix1, 0, 44);
        lv_obj_set_size(prefix1, prefix_w, 18);
        lv_label_set_long_mode(prefix1, LV_LABEL_LONG_DOT);

        lv_obj_t *v1 = lv_label_create(card);
        lv_obj_set_style_text_font(v1, UI_FONT_14, 0);
        lv_obj_set_style_text_color(v1, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
        lv_obj_set_pos(v1, prefix_w, 44);
        lv_obj_set_size(v1, inner_w - prefix_w, 18);
        lv_label_set_long_mode(v1, LV_LABEL_LONG_DOT);
        lv_label_bind_text(v1, sub_value, NULL);
    }

    /* v2 (y=64) */
    if (sub_value2 != NULL) {
        lv_obj_t *prefix2 = lv_label_create(card);
        lv_label_set_text(prefix2, value2_prefix);
        lv_obj_set_style_text_font(prefix2, UI_FONT_14, 0);
        lv_obj_set_style_text_color(prefix2, lv_color_hex(UI_COLOR_TEXT_MUTED), 0);
        lv_obj_set_pos(prefix2, 0, 64);
        lv_obj_set_size(prefix2, prefix_w, 18);
        lv_label_set_long_mode(prefix2, LV_LABEL_LONG_DOT);

        lv_obj_t *v2 = lv_label_create(card);
        lv_obj_set_style_text_font(v2, UI_FONT_14, 0);
        lv_obj_set_style_text_color(v2, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
        lv_obj_set_pos(v2, prefix_w, 64);
        lv_obj_set_size(v2, inner_w - prefix_w, 18);
        lv_label_set_long_mode(v2, LV_LABEL_LONG_DOT);
        lv_label_bind_text(v2, sub_value2, NULL);
    }

    /* cap (y=84) Latin 10px */
    lv_obj_t *cap = lv_label_create(card);
    lv_obj_set_style_text_font(cap, &lv_font_montserrat_10, 0);
    lv_obj_set_style_text_color(cap, lv_color_hex(UI_COLOR_TEXT_MUTED), 0);
    lv_obj_set_pos(cap, 0, 84);
    lv_obj_set_size(cap, inner_w, 10);
    lv_label_set_long_mode(cap, LV_LABEL_LONG_DOT);
    lv_label_bind_text(cap, sub_cap, NULL);

    return card;
}

static void build_ports(void)
{
    /* 1. screen + 顶栏（复用 build_list() 风格：白底 44px + 返回箭头） */
    lv_obj_t *scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(scr, lv_color_hex(UI_COLOR_BG), 0);
    s_screens[PG_PORTS] = scr;

    lv_obj_t *bar = lv_obj_create(scr);
    lv_obj_set_pos(bar, 0, 0);
    lv_obj_set_size(bar, UI_SCREEN_W, UI_TOPBAR_H);
    lv_obj_set_style_bg_color(bar, (lv_color_t){.red=0xFF, .green=0xFF, .blue=0xFF}, 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_set_style_border_side(bar, LV_BORDER_SIDE_BOTTOM, 0);
    lv_obj_set_style_border_color(bar, lv_color_hex(UI_COLOR_BORDER), 0);
    lv_obj_set_style_border_width(bar, 1, 0);
    lv_obj_set_style_pad_all(bar, 0, 0);
    lv_obj_clear_flag(bar, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(bar, on_back_click, LV_EVENT_CLICKED, NULL);
    lv_obj_add_flag(bar, LV_OBJ_FLAG_CLICKABLE);

    lv_obj_t *back = lv_label_create(bar);
    lv_label_set_text(back, LV_SYMBOL_LEFT "  返回");
    lv_obj_set_style_text_font(back, UI_FONT_14, 0);
    lv_obj_set_style_text_color(back, lv_color_hex(UI_COLOR_ACCENT), 0);
    lv_obj_set_pos(back, 8, 12);
    lv_obj_set_size(back, 110, 44);
    lv_obj_set_ext_click_area(back, 10);
    lv_obj_add_event_cb(back, on_back_click, LV_EVENT_CLICKED, NULL);
    lv_obj_add_flag(back, LV_OBJ_FLAG_CLICKABLE);

    lv_obj_t *title = lv_label_create(bar);
    lv_label_set_text(title, "端口");
    lv_obj_set_style_text_font(title, UI_FONT_14, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(UI_COLOR_TEXT_PRIMARY), 0);
    lv_obj_set_pos(title, 60, 12);
    lv_obj_set_size(title, UI_SCREEN_W - 130, 22);
    lv_obj_set_style_text_align(title, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_long_mode(title, LV_LABEL_LONG_SCROLL_CIRCULAR);

    /* 2. 初始化所有 subject (一次 init 终身复用；v0.9.6 状态全中文化) */
    /* I2C-1 = AHT20 (env.temperature / env.humidity) */
    lv_subject_init_string(&s_sub_i2c1_module, s_buf_i2c1_module, s_buf_i2c1_module_prev,
                           sizeof(s_buf_i2c1_module), "AHT20");
    lv_subject_init_string(&s_sub_i2c1_status, s_buf_i2c1_status, s_buf_i2c1_status_prev,
                           sizeof(s_buf_i2c1_status), "离线");
    lv_subject_init_string(&s_sub_i2c1_temp, s_buf_i2c1_temp, s_buf_i2c1_temp_prev,
                           sizeof(s_buf_i2c1_temp), "--.- ℃");
    lv_subject_init_string(&s_sub_i2c1_humid, s_buf_i2c1_humid, s_buf_i2c1_humid_prev,
                           sizeof(s_buf_i2c1_humid), "--.- %");
    lv_subject_init_string(&s_sub_i2c1_cap, s_buf_i2c1_cap, s_buf_i2c1_cap_prev,
                           sizeof(s_buf_i2c1_cap), "env.temperature / env.humidity");

    /* I2C-2 = 未实现：空 + 未启用
       v0.9.15: 初值直接传 glyph 字串，跟运行时 4 状态视觉一致 */
    lv_subject_init_string(&s_sub_i2c2_module, s_buf_i2c2_module, s_buf_i2c2_module_prev,
                           sizeof(s_buf_i2c2_module), "无模块");
    lv_subject_init_string(&s_sub_i2c2_status, s_buf_i2c2_status, s_buf_i2c2_status_prev,
                           sizeof(s_buf_i2c2_status), LV_SYMBOL_MINUS "  未启用");
    lv_subject_init_string(&s_sub_i2c2_light, s_buf_i2c2_light, s_buf_i2c2_light_prev,
                           sizeof(s_buf_i2c2_light), "--");
    lv_subject_init_string(&s_sub_i2c2_cap, s_buf_i2c2_cap, s_buf_i2c2_cap_prev,
                           sizeof(s_buf_i2c2_cap), "—");

    /* PWM-0 = SG90 (motor.servo.angle, 无物理反馈) */
    lv_subject_init_string(&s_sub_pwm0_module, s_buf_pwm0_module, s_buf_pwm0_module_prev,
                           sizeof(s_buf_pwm0_module), "");
    lv_subject_init_string(&s_sub_pwm0_status, s_buf_pwm0_status, s_buf_pwm0_status_prev,
                           sizeof(s_buf_pwm0_status), "");
    lv_subject_init_string(&s_sub_pwm0_angle, s_buf_pwm0_angle, s_buf_pwm0_angle_prev,
                           sizeof(s_buf_pwm0_angle), "");
    lv_subject_init_string(&s_sub_pwm0_cap, s_buf_pwm0_cap, s_buf_pwm0_cap_prev,
                           sizeof(s_buf_pwm0_cap), "");
    lv_subject_init_string(&s_sub_pwm0_feedback, s_buf_pwm0_feedback, s_buf_pwm0_feedback_prev,
                           sizeof(s_buf_pwm0_feedback),
                           "");

    /* UART-BRIDGE = ESP32-S3 UART 桥接 + WiFi + MQTT */
    lv_subject_init_string(&s_sub_uart_module, s_buf_uart_module, s_buf_uart_module_prev,
                           sizeof(s_buf_uart_module), "ESP32-S3");
    lv_subject_init_string(&s_sub_uart_status, s_buf_uart_status, s_buf_uart_status_prev,
                           sizeof(s_buf_uart_status), "离线");
    lv_subject_init_string(&s_sub_uart_wifi, s_buf_uart_wifi, s_buf_uart_wifi_prev,
                           sizeof(s_buf_uart_wifi), "WiFi 等待连接");
    lv_subject_init_string(&s_sub_uart_mqtt, s_buf_uart_mqtt, s_buf_uart_mqtt_prev,
                           sizeof(s_buf_uart_mqtt), "MQTT 等待连接");
    lv_subject_init_string(&s_sub_uart_cap, s_buf_uart_cap, s_buf_uart_cap_prev,
                           sizeof(s_buf_uart_cap), "UART 桥接 / MQTT 链路");

    /* 3. body 容器 + 4 张卡 */
    lv_obj_t *body = lv_obj_create(scr);
    lv_obj_set_pos(body, 0, UI_TOPBAR_H);
    lv_obj_set_size(body, UI_SCREEN_W, UI_SCREEN_H - UI_TOPBAR_H);
    lv_obj_set_style_bg_color(body, lv_color_hex(UI_COLOR_BG), 0);
    lv_obj_set_style_bg_opa(body, LV_OPA_COVER, 0);
    lv_obj_set_style_border_opa(body, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(body, 0, 0);
    lv_obj_set_flex_flow(body, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_top(body, 6, 0);
    lv_obj_set_style_pad_bottom(body, 6, 0);
    lv_obj_set_style_pad_left(body, 14, 0);
    lv_obj_set_style_pad_right(body, 14, 0);
    lv_obj_set_style_pad_row(body, 4, 0);
    /* v0.9.8: 关弹性回弹 + 关惯性 + 关滚动条
       (软件 SPI 320×480 一帧 ~460ms，滚动一次 SPI 全速也只能 17fps；
        用户反馈"取消回弹改成低帧率下稳定刷新"，本版彻底关闭滚动行为，
        让 4 张卡首屏装下，需要时再开滚动但不回弹) */
    lv_obj_clear_flag(body, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_clear_flag(body, LV_OBJ_FLAG_SCROLL_ELASTIC);
    lv_obj_clear_flag(body, LV_OBJ_FLAG_SCROLL_MOMENTUM);
    lv_obj_set_scrollbar_mode(body, LV_SCROLLBAR_MODE_OFF);
    lv_obj_set_scroll_dir(body, LV_DIR_NONE);

    /* v0.9.12: card_h 100 装下 5 行不重叠
       行布局: title(4-22) / module(26-42) / cap(44-58) / v1(60-78) / v2(80-98)
       注意: badge 起点 y=4 h=20, module 起点 y=26 不重叠 */
    int card_w = UI_SCREEN_W - 28;
    int card_h = 96;  /* v0.9.13: 简化布局 5 行 96 够 */
    int y0 = 0;

    /* 4×96+3×6+12 = 414 < 436 body 装得下 */
    (void)y0;

    /* I2C-1: AHT20, 温度+湿度双值 */
    build_ports_card(body, 0, y0, card_w, card_h,
                     "I2C-1",
                     &s_sub_i2c1_module, &s_sub_i2c1_status,
                     &s_sub_i2c1_temp,  "温度",
                     &s_sub_i2c1_humid, "湿度",
                     &s_sub_i2c1_cap);

    /* I2C-2: 逻辑上承接 BH1750 显示 */
    build_ports_card(body, 0, y0, card_w, card_h,
                     "I2C-2",
                     &s_sub_i2c2_module, &s_sub_i2c2_status,
                     &s_sub_i2c2_light, "光照",
                     NULL, "",
                     &s_sub_i2c2_cap);

    /* PWM-0: SG90, 角度 */
    build_ports_card(body, 0, y0, card_w, card_h,
                     "PWM-0",
                     &s_sub_pwm0_module, &s_sub_pwm0_status,
                     NULL, "",
                     NULL, "",
                     &s_sub_pwm0_cap);

    /* UART-BRIDGE: ESP32, wifi + mqtt */
    build_ports_card(body, 0, y0, card_w, card_h,
                     "UART-BRIDGE",
                     &s_sub_uart_module, &s_sub_uart_status,
                     &s_sub_uart_wifi, "WiFi",
                     &s_sub_uart_mqtt, "MQTT",
                     &s_sub_uart_cap);

    /* 4. 启动 200ms 桥接定时器 */
    s_ports_timer = lv_timer_create(ports_timer_cb, 200, NULL);
}

static void ports_timer_cb(lv_timer_t *t)
{
    platform_port_t const * i2c1_port = platform_ports_get_port(0U);
    bool i2c1_has_temp = false;
    bool i2c1_has_hum = false;
    bool i2c1_has_light = false;
    bool i2c2_show_light = false;
    char i2c1_module_text[32];
    char i2c1_cap_text[64];
    bh1750_sample_t light_sample;
    bool light_sample_ok = false;

    (void)t;

    strcpy(i2c1_module_text, "无模块");
    strcpy(i2c1_cap_text, "—");
    if (i2c1_port != NULL) {
        for (uint8_t i = 0U; i < i2c1_port->capability_count; i++) {
            if (strcmp(i2c1_port->capabilities[i].id, "env.temperature") == 0) {
                i2c1_has_temp = true;
            } else if (strcmp(i2c1_port->capabilities[i].id, "env.humidity") == 0) {
                i2c1_has_hum = true;
            } else if (strcmp(i2c1_port->capabilities[i].id, "env.light.lux") == 0) {
                i2c1_has_light = true;
            }
        }

        if (i2c1_has_temp || i2c1_has_hum) {
            strcpy(i2c1_module_text, "AHT20");
            strcpy(i2c1_cap_text, "env.temperature / env.humidity");
        } else if (i2c1_has_light) {
            strcpy(i2c1_module_text, "BH1750");
            strcpy(i2c1_cap_text, "env.light.lux");
        } else if (i2c1_port->module.module_type[0] != '\0') {
            snprintf(i2c1_module_text, sizeof(i2c1_module_text), "%s", i2c1_port->module.module_type);
        }
        i2c2_show_light = i2c1_has_light;
    }
    lv_subject_copy_string(&s_sub_i2c1_module, i2c1_module_text);
    lv_subject_copy_string(&s_sub_i2c1_cap, i2c1_cap_text);

    /* === I2C-1 ← AHT20 === */
    aht20_sample_t s;
    if (aht20_last(&s)) {
        int32_t t10 = (int32_t)(s.temperature_c * 10.0f + (s.temperature_c >= 0 ? 0.5f : -0.5f));
        int32_t h10 = (int32_t)(s.humidity_rh  * 10.0f + (s.humidity_rh  >= 0 ? 0.5f : -0.5f));
        if (t10 < 0) t10 = -t10;  /* 负数只显示绝对值，前缀 '-' 由 fmt 体现；这里保守 */
        if (h10 < 0) h10 = 0;
        lv_subject_snprintf(&s_sub_i2c1_temp,  "%ld.%ld ℃",
                            (long)(t10 / 10), (long)(t10 % 10));
        lv_subject_snprintf(&s_sub_i2c1_humid, "%ld.%ld %%",
                            (long)(h10 / 10), (long)(h10 % 10));
        /* v0.9.15: PORTS status 走 ui_status_glyph */
        if (s.crc_ok) {
            lv_subject_copy_string(&s_sub_i2c1_status, ui_status_glyph("在线"));
        } else {
            lv_subject_copy_string(&s_sub_i2c1_status, ui_status_glyph("校验错"));
        }
    } else {
        lv_subject_copy_string(&s_sub_i2c1_status, ui_status_glyph("离线"));
    }

    /* === I2C-2: 逻辑上映射 BH1750 === */
    light_sample_ok = bh1750_last(&light_sample);
    if (i2c2_show_light) {
        lv_subject_copy_string(&s_sub_i2c2_module, "BH1750");
        lv_subject_copy_string(&s_sub_i2c2_cap, "env.light.lux");
        if (light_sample_ok) {
            lv_subject_snprintf(&s_sub_i2c2_light, "%ld lux", (long) light_sample.lux);
            lv_subject_copy_string(&s_sub_i2c2_status, ui_status_glyph("在线"));
        } else {
            lv_subject_copy_string(&s_sub_i2c2_light, "--");
            lv_subject_copy_string(&s_sub_i2c2_status, ui_status_glyph("离线"));
        }
    } else {
        lv_subject_copy_string(&s_sub_i2c2_module, "无模块");
        lv_subject_copy_string(&s_sub_i2c2_light, "--");
        lv_subject_copy_string(&s_sub_i2c2_cap, "—");
        lv_subject_copy_string(&s_sub_i2c2_status, ui_status_glyph("未启用"));
    }

    /* === PWM-0 ← SG90 (无反馈执行器) === */
    lv_subject_copy_string(&s_sub_pwm0_module, "");
    lv_subject_copy_string(&s_sub_pwm0_cap, "");
    lv_subject_copy_string(&s_sub_pwm0_angle, "");
    lv_subject_copy_string(&s_sub_pwm0_status, "");
    lv_subject_copy_string(&s_sub_pwm0_feedback, "");

    /* === UART-BRIDGE ← ESP32 === */
    /* v0.9.22: status 走 status_en_to_cn 映射中文 */
    lv_subject_copy_string(&s_sub_uart_status,
                           ui_status_glyph(esp32_link_is_online() ? "在线" : "离线"));
    /* v0.9.22: WiFi 行 = "已连接" (中文) */
    char wifi_line[64];
    snprintf(wifi_line, sizeof(wifi_line), "%s · %s",
             s_wifi_name[0] ? s_wifi_name : "WiFi",
             status_en_to_cn(s_wifi_status));
    lv_subject_copy_string(&s_sub_uart_wifi, wifi_line);
    char mqtt_line[40];
    snprintf(mqtt_line, sizeof(mqtt_line), "MQTT · %s", status_en_to_cn(s_mqtt_status));
    lv_subject_copy_string(&s_sub_uart_mqtt, mqtt_line);
}

/* ================================================================ */
/* 主入口                                                           */
/* ================================================================ */
void app_ui_create(void)
{
    device_registry_init();  /* v0.9.23: 启动时拉一次状态,后面 hal_entry tick 增量刷新 */
    build_home();
    build_list();
    build_detail();
    build_ports();   /* v0.9.5: 标准口页面 */
    if (s_clock_timer == NULL) {
        s_clock_timer = lv_timer_create(clock_timer_cb, 250, NULL);
    }
    lv_screen_load(s_screens[PG_HOME]);
    s_current_page = PG_HOME;
}

/* ================================================================ */
/* 兼容旧 API（无操作，存字符串）                                    */
/* ================================================================ */
static void safe_copy(char *dst, const char *src, size_t cap)
{
    if (src == NULL) { dst[0] = '\0'; return; }
    size_t n = strlen(src);
    if (n >= cap) n = cap - 1;
    memcpy(dst, src, n);
    dst[n] = '\0';
}

/* v0.9.22: 英文状态字符串映射成中文 (esp32_link UART 协议过来是英文) */
static const char * status_en_to_cn(const char * en)
{
    if (en == NULL || en[0] == '\0') return "--";
    if (strcmp(en, "online") == 0)        return "在线";
    if (strcmp(en, "offline") == 0)       return "离线";
    if (strcmp(en, "connected") == 0)     return "已连接";
    if (strcmp(en, "disconnected") == 0)  return "未连接";
    if (strcmp(en, "connecting") == 0)    return "连接中";
    if (strcmp(en, "configured") == 0)    return "已配置";
    if (strcmp(en, "channel_active") == 0)   return "通道就绪";
    if (strcmp(en, "channel_idle") == 0)     return "通道空闲";
    if (strcmp(en, "not_inserted") == 0)     return "未插入";
    if (strcmp(en, "reserved") == 0)         return "保留";
    if (strcmp(en, "empty") == 0)            return "空";
    if (strcmp(en, "warming") == 0)          return "预热中";
    if (strcmp(en, "retrying") == 0)         return "重试中";
    return en;  /* 未知英文原样返回 */
}

/* v0.9.22: 去除末尾 \r \n 空白, 避免 status_en_to_cn strcmp 不匹配 */
static void safe_copy_trim(char *dst, const char *src, size_t cap)
{
    if (dst == NULL || cap == 0) return;
    if (src == NULL) { dst[0] = '\0'; return; }
    /* 跳过前导空白 */
    while (*src == ' ' || *src == '\t' || *src == '\r' || *src == '\n') src++;
    size_t n = strlen(src);
    /* 去除末尾空白 */
    while (n > 0 && (src[n-1] == ' ' || src[n-1] == '\t' || src[n-1] == '\r' || src[n-1] == '\n')) n--;
    if (n >= cap) n = cap - 1;
    memcpy(dst, src, n);
    dst[n] = '\0';
}

void app_ui_set_esp32_status(const char * t)        { safe_copy_trim(s_esp32_status, status_en_to_cn(t), sizeof(s_esp32_status)); }
void app_ui_set_wifi_status(const char * t)         { safe_copy_trim(s_wifi_status, status_en_to_cn(t), sizeof(s_wifi_status)); }
void app_ui_set_wifi_name(const char * t)
{
    safe_copy_trim(s_wifi_name, t, sizeof(s_wifi_name));
    if (s_wifi_name[0] != '\0') {
        safe_copy_trim(s_current_ssid, s_wifi_name, sizeof(s_current_ssid));
        ui_topbar_set_left_label(&s_topbar, s_current_ssid);
    }
}
void app_ui_set_mqtt_status(const char * t)         { safe_copy_trim(s_mqtt_status, status_en_to_cn(t), sizeof(s_mqtt_status)); }
void app_ui_set_aht20_status(const char * t)        { safe_copy_trim(s_aht20_status, status_en_to_cn(t), sizeof(s_aht20_status)); }
void app_ui_set_aht20_measurement(const char * t)   { safe_copy_trim(s_aht20_meas, t, sizeof(s_aht20_meas)); }
void app_ui_set_control_status(const char * t)      { safe_copy_trim(s_control, status_en_to_cn(t), sizeof(s_control)); }
void app_ui_set_input_status(const char * t)        { safe_copy_trim(s_input, status_en_to_cn(t), sizeof(s_input)); }

void app_ui_set_last_rx(const char * t)             { (void)t; }
void app_ui_set_last_tx(const char * t)             { (void)t; }
void app_ui_set_request_id(const char * t)          { (void)t; }
void app_ui_set_script_id(const char * t)           { (void)t; }
void app_ui_set_intent_type(const char * t)         { (void)t; }
void app_ui_set_command_text(const char * t)        { (void)t; }
void app_ui_set_ack_status(const char * t)          { (void)t; }
void app_ui_set_touch_state(bool p, uint16_t x, uint16_t y) { (void)p; (void)x; (void)y; }
void app_ui_set_touch_signal(const char * t)        { (void)t; }
void app_ui_set_touch_probe(const char * t)         { (void)t; }
void app_ui_set_candidate_status(const char * t)    { (void)t; }
void app_ui_mark_input_forwarded(const char * t)    { (void)t; }
bool app_ui_touch_hits_input(int32_t x, int32_t y)
{
    int32_t tx, ty;
    bool pressed;
    lv_port_indev_get_state(&tx, &ty, &pressed);
    (void) x; (void) y;
    return pressed && (tx > 0 || ty > 0);
}
bool app_ui_take_input_submission(char * t, size_t s){ (void)t; (void)s; return false; }

/* v0.9.20: 除ui版独有 setter 兼容 (esp32_link.c / hal_entry.c 调).
 * ui版 app_ui.c 不需要这些（PORTS 走 lv_subject 自动跟随时不需要手动 refresh_platform_state），
 * 这里实现为 no-op + safe_copy，保留字符串缓存以备将来需要。 */
void app_ui_set_device_id(const char * t)
{
    safe_copy_trim(s_device_id, t, sizeof(s_device_id));
    detail_refresh_values();
}
void app_ui_set_i2c_s1_scan(const char * diag_text, const char * devices_text, uint8_t count)
{
    /* ui版 PORTS 页面 i2c.s1 卡直接读 platform_ports，不需要这个 setter */
    (void)diag_text; (void)devices_text; (void)count;
}
void app_ui_refresh_platform_state(void)
{
    /* v0.9.21: hal_entry 每次 aht20_read/bh1750_read/i2c_scan 后调此函数
     * — 让 PORTS lv_subject 自动跟随后，再触发详情页 label 刷新。
     * v0.9.25: 不再在这里重建硬件列表，避免列表页触摸期间对象被反复 clean/recreate。 */
    detail_refresh_values();
}
void app_ui_set_clock_time(uint8_t hour, uint8_t minute, uint8_t second)
{
    s_clock_base_seconds = ((uint32_t) hour * 3600U) + ((uint32_t) minute * 60U) + (uint32_t) second;
    s_clock_base_tick_ms = lv_tick_get();
    s_clock_valid = true;
    refresh_clock_from_base();
}
void app_ui_clear_wifi_networks(void)
{
    memset(s_wifi_networks, 0, sizeof(s_wifi_networks));
    s_wifi_network_count = 0U;
    refresh_wifi_sheet();
}
void app_ui_add_wifi_network(const char * ssid, int16_t rssi_dbm, bool connected)
{
    uint8_t slot = UI_WIFI_MAX;

    if ((ssid == NULL) || (ssid[0] == '\0')) {
        return;
    }

    for (uint8_t i = 0U; i < s_wifi_network_count; i++) {
        if (s_wifi_networks[i].valid && (strcmp(s_wifi_networks[i].ssid, ssid) == 0)) {
            slot = i;
            break;
        }
    }

    if (slot == UI_WIFI_MAX) {
        if (s_wifi_network_count >= UI_WIFI_MAX) {
            return;
        }
        slot = s_wifi_network_count++;
    }

    s_wifi_networks[slot].valid = true;
    s_wifi_networks[slot].connected = connected;
    s_wifi_networks[slot].rssi_dbm = rssi_dbm;
    safe_copy_trim(s_wifi_networks[slot].ssid, ssid, sizeof(s_wifi_networks[slot].ssid));

    if (connected) {
        safe_copy_trim(s_current_ssid, ssid, sizeof(s_current_ssid));
        ui_topbar_set_left_label(&s_topbar, s_current_ssid);
    }

    refresh_wifi_sheet();
}
