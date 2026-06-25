#ifndef TOUCH_DEBUG_RTT_H
#define TOUCH_DEBUG_RTT_H

#include <stdbool.h>
#include <stdint.h>

#include "ft6336.h"

#ifdef __cplusplus
extern "C" {
#endif

void touch_debug_rtt_init(void);
void touch_debug_rtt_log_sample(bool pressed, ft6336_point_t const * point, uint16_t mapped_x, uint16_t mapped_y);

#ifdef __cplusplus
}
#endif

#endif /* TOUCH_DEBUG_RTT_H */
