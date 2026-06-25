#include "lv_port_indev.h"

#include <stdbool.h>
#include <stdint.h>

#include "app_ui.h"
#include "ft6336.h"
#include "touch_debug_rtt.h"

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsign-conversion"
#include "lvgl.h"
#pragma GCC diagnostic pop

#define TOUCH_SCREEN_W           320
#define TOUCH_SCREEN_H           480
#define TOUCH_NATIVE_W           320
#define TOUCH_NATIVE_H           480
#define TOUCH_ROTATION           0
#define TOUCH_RELEASE_DEBOUNCE   2U

lv_indev_t * g_touch_indev;
static int32_t g_last_x;
static int32_t g_last_y;
static uint16_t g_last_raw_x;
static uint16_t g_last_raw_y;
static bool g_last_pressed;
static uint8_t g_release_streak;
static bool g_last_hit_input;

void lv_port_indev_get_state(int32_t * out_x, int32_t * out_y, bool * out_pressed)
{
    if (out_x != NULL) *out_x = g_last_x;
    if (out_y != NULL) *out_y = g_last_y;
    if (out_pressed != NULL) *out_pressed = g_last_pressed;
}

static int32_t clamp_coord(int32_t value, int32_t upper_bound)
{
    if (value < 0) {
        return 0;
    }
    if (value > upper_bound) {
        return upper_bound;
    }
    return value;
}

static void map_touch_raw_to_screen(uint16_t raw_x, uint16_t raw_y, int32_t * screen_x, int32_t * screen_y)
{
    /*
     * FT6336 reports native panel coordinates. The previous UI-specific
     * calibration (28..287 / 56..432 plus a 32 px top offset) belonged to
     * an older content area and shifted the current full-screen UI hit boxes.
     */
    int32_t mapped_x = (int32_t) raw_x;
    int32_t mapped_y = (int32_t) raw_y;
    int32_t swap_temp;

    switch (TOUCH_ROTATION & 3) {
        case 1:
            swap_temp = mapped_x;
            mapped_x = mapped_y;
            mapped_y = (TOUCH_NATIVE_W - 1) - swap_temp;
            break;
        case 2:
            mapped_x = (TOUCH_NATIVE_W - 1) - mapped_x;
            mapped_y = (TOUCH_NATIVE_H - 1) - mapped_y;
            break;
        case 3:
            swap_temp = mapped_x;
            mapped_x = (TOUCH_NATIVE_H - 1) - mapped_y;
            mapped_y = swap_temp;
            break;
        default:
            break;
    }

    mapped_x = clamp_coord(mapped_x, TOUCH_SCREEN_W - 1);
    mapped_y = clamp_coord(mapped_y, TOUCH_SCREEN_H - 1);

    *screen_x = mapped_x;
    *screen_y = mapped_y;
}

static void touch_read_cb(lv_indev_t * indev, lv_indev_data_t * data)
{
    ft6336_point_t point = {0};
    bool sample_valid;
    bool report_pressed;
    bool was_pressed;

    (void) indev;

    was_pressed = g_last_pressed;
    sample_valid = (ft6336_read_point(&point) != 0U);
    if (sample_valid) {
        g_release_streak = 0U;
        g_last_raw_x = point.x;
        g_last_raw_y = point.y;
        map_touch_raw_to_screen(point.x, point.y, &g_last_x, &g_last_y);
        g_last_pressed = true;
    } else if (g_last_pressed && (g_release_streak < TOUCH_RELEASE_DEBOUNCE)) {
        g_release_streak++;
    } else {
        g_last_pressed = false;
    }

    report_pressed = g_last_pressed;
    data->point.x = g_last_x;
    data->point.y = g_last_y;
    data->state = report_pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;

    if (report_pressed) {
        bool hit_input = app_ui_touch_hits_input(g_last_x, g_last_y);
        if (hit_input != g_last_hit_input) {
            app_ui_set_touch_probe(hit_input ? "input hit" : "input miss");
            g_last_hit_input = hit_input;
        }
    } else if (g_last_hit_input) {
        app_ui_set_touch_probe("input release");
        g_last_hit_input = false;
    }

    if (sample_valid || report_pressed || was_pressed) {
        app_ui_set_touch_state(report_pressed, (uint16_t) g_last_x, (uint16_t) g_last_y);
        touch_debug_rtt_log_sample(sample_valid, &point, (uint16_t) g_last_x, (uint16_t) g_last_y);
    }
}

void lv_port_indev_init(void)
{
    ft6336_init();

    g_last_x = 0;
    g_last_y = 0;
    g_last_raw_x = 0U;
    g_last_raw_y = 0U;
    g_last_pressed = false;
    g_release_streak = 0U;
    g_last_hit_input = false;

    g_touch_indev = lv_indev_create();
    lv_indev_set_type(g_touch_indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(g_touch_indev, touch_read_cb);
}
