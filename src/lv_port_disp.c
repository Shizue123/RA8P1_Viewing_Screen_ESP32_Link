#include "lv_port_disp.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsign-conversion"
#include "lvgl.h"
#pragma GCC diagnostic pop
#include "lcd_spi.h"

#define DISP_HOR_RES  320
#define DISP_VER_RES  480
#define BYTE_PER_PIXEL 2   /* RGB565 = 2 bytes */

/* Single partial buffer: 320 x 20 rows x 2 bytes = 12800 bytes */
#define BUF_ROWS  20
static LV_ATTRIBUTE_MEM_ALIGN uint8_t buf_1[DISP_HOR_RES * BUF_ROWS * BYTE_PER_PIXEL];

static void disp_flush(lv_display_t * disp, const lv_area_t * area, uint8_t * px_map)
{
    int32_t x, y;
    uint32_t w = (uint32_t)(area->x2 - area->x1 + 1);
    uint32_t h = (uint32_t)(area->y2 - area->y1 + 1);

    lcd_set_window((uint16_t)area->x1, (uint16_t)area->y1,
                   (uint16_t)area->x2, (uint16_t)area->y2);

    dc_high(); cs_low();

    uint16_t * pixels = (uint16_t *)px_map;
    for (y = 0; y < (int32_t)h; y++) {
        for (x = 0; x < (int32_t)w; x++) {
            uint16_t c = pixels[y * (int32_t)w + x];
            uint8_t r5 = (c >> 11) & 0x1F;
            uint8_t g6 = (c >> 5)  & 0x3F;
            uint8_t b5 =  c        & 0x1F;
            spi_write_byte((uint8_t)((r5 << 3) | (r5 >> 2)));  /* R: 5→8 bit */
            spi_write_byte((uint8_t)(g6 << 2));                 /* G: 6→8 bit */
            spi_write_byte((uint8_t)((b5 << 3) | (b5 >> 2)));  /* B: 5→8 bit */
        }
    }

    cs_high();

    lv_display_flush_ready(disp);
}

void lv_port_disp_init(void)
{
    lv_display_t * disp = lv_display_create(DISP_HOR_RES, DISP_VER_RES);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    lv_display_set_flush_cb(disp, disp_flush);
    lv_display_set_buffers(disp, buf_1, NULL, sizeof(buf_1), LV_DISPLAY_RENDER_MODE_PARTIAL);
}
