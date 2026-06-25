#ifndef FT6336_H
#define FT6336_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct st_ft6336_point
{
    uint8_t touches;
    uint8_t event;
    uint8_t track_id;
    uint16_t x;
    uint16_t y;
} ft6336_point_t;

extern volatile uint8_t g_ft6336_last_frame[16];
extern volatile uint8_t g_ft6336_last_read_ok;
extern volatile uint8_t g_ft6336_last_touches;
extern volatile uint8_t g_ft6336_last_chip_id;
extern volatile uint8_t g_ft6336_last_vendor_id;
extern volatile uint8_t g_ft6336_last_focaltech_id;

void ft6336_init(void);
uint8_t ft6336_read_point(ft6336_point_t * point);
uint8_t ft6336_scan(uint16_t *x, uint16_t *y);

#ifdef __cplusplus
}
#endif

#endif /* FT6336_H */
