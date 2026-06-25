#include "touch_debug_rtt.h"

#include <stdio.h>

#include "segger_rtt/SEGGER_RTT.h"
#include "app_ui.h"

static uint32_t g_touch_log_seq;
static bool g_touch_last_pressed;
static uint16_t g_touch_last_raw_x;
static uint16_t g_touch_last_raw_y;
static uint16_t g_touch_last_mapped_x;
static uint16_t g_touch_last_mapped_y;

void touch_debug_rtt_init(void)
{
    SEGGER_RTT_Init();
    g_touch_log_seq = 0U;
    g_touch_last_pressed = false;
    g_touch_last_raw_x = 0U;
    g_touch_last_raw_y = 0U;
    g_touch_last_mapped_x = 0U;
    g_touch_last_mapped_y = 0U;
    SEGGER_RTT_WriteString(0, "touch-rtt:init\n");
    app_ui_set_touch_signal("rtt ready");
}

void touch_debug_rtt_log_sample(bool pressed, ft6336_point_t const * point, uint16_t mapped_x, uint16_t mapped_y)
{
    char line[160];
    char signal[32];

    if (point == NULL) {
        return;
    }

    if (pressed) {
        g_touch_last_raw_x = point->x;
        g_touch_last_raw_y = point->y;
        g_touch_last_mapped_x = mapped_x;
        g_touch_last_mapped_y = mapped_y;
    }

    if ((pressed == g_touch_last_pressed) &&
        (!pressed ||
         ((point->x == g_touch_last_raw_x) &&
          (point->y == g_touch_last_raw_y) &&
          (mapped_x == g_touch_last_mapped_x) &&
          (mapped_y == g_touch_last_mapped_y)))) {
        return;
    }

    g_touch_log_seq++;
    if (pressed) {
        (void) snprintf(line, sizeof(line),
                        "touch seq=%lu state=down raw=%u,%u map=%u,%u touches=%u event=%u id=%u\n",
                        (unsigned long) g_touch_log_seq,
                        (unsigned int) point->x,
                        (unsigned int) point->y,
                        (unsigned int) mapped_x,
                        (unsigned int) mapped_y,
                        (unsigned int) point->touches,
                        (unsigned int) point->event,
                        (unsigned int) point->track_id);
        (void) snprintf(signal, sizeof(signal), "rtt rx %lu", (unsigned long) g_touch_log_seq);
        app_ui_set_touch_signal(signal);
    } else {
        (void) snprintf(line, sizeof(line),
                        "touch seq=%lu state=up raw=%u,%u map=%u,%u\n",
                        (unsigned long) g_touch_log_seq,
                        (unsigned int) g_touch_last_raw_x,
                        (unsigned int) g_touch_last_raw_y,
                        (unsigned int) g_touch_last_mapped_x,
                        (unsigned int) g_touch_last_mapped_y);
        (void) snprintf(signal, sizeof(signal), "rtt up %lu", (unsigned long) g_touch_log_seq);
        app_ui_set_touch_signal(signal);
    }

    SEGGER_RTT_WriteString(0, line);
    g_touch_last_pressed = pressed;
}
