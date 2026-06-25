#ifndef LV_PORT_INDEV_H
#define LV_PORT_INDEV_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

void lv_port_indev_init(void);
void lv_port_indev_get_state(int32_t * out_x, int32_t * out_y, bool * out_pressed);

#ifdef __cplusplus
}
#endif

struct _lv_indev_t;
extern struct _lv_indev_t * g_touch_indev;

#endif /* LV_PORT_INDEV_H */
