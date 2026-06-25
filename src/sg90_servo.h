#ifndef SG90_SERVO_H
#define SG90_SERVO_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void sg90_servo_init(void);
void sg90_servo_tick_5ms(void);
void sg90_servo_set_enabled(bool enabled);
void sg90_servo_set_active(bool active);
void sg90_servo_configure_angle(uint16_t angle_degrees);
uint16_t sg90_servo_get_target_angle(void);
uint16_t sg90_servo_get_angle(void);   /* v0.9.21: 别名 (ui版 app_ui.c 用这名) */
bool sg90_servo_is_active(void);
bool sg90_servo_is_enabled(void);       /* v0.9.21: 别名 (ui版 app_ui.c 用这名) */

#ifdef __cplusplus
}
#endif

#endif /* SG90_SERVO_H */
