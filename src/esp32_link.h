#ifndef ESP32_LINK_H
#define ESP32_LINK_H

#include <stdbool.h>
#include <stdint.h>

#include "aht20.h"

#ifdef __cplusplus
extern "C" {
#endif

#ifndef ESP32_LINK_ENABLE_FSP_UART
#define ESP32_LINK_ENABLE_FSP_UART (1)
#endif

void esp32_link_init(void);
void esp32_link_poll_5ms(void);
bool esp32_link_is_online(void);
void esp32_link_publish_aht20_status(bool online, int32_t temperature_tenths, uint32_t humidity_tenths, bool crc_ok);
void esp32_link_publish_aht20_offline(const char * diag_text);
void esp32_link_publish_i2c_scan(const char * diag_text, const char * devices_text, uint8_t count);
void esp32_link_publish_ra8p1_uid(void);
void esp32_link_publish_rule_state(const char * state_text, const char * reason_text, bool has_temperature, int32_t temperature_tenths);
void esp32_link_publish_platform_snapshot(void);
void esp32_link_submit_nl_text(const char * text);
void esp32_link_request_sync(void);
void esp32_link_request_wifi_scan(void);
void esp32_link_request_wifi_connect(const char * ssid);
void esp32_link_clear_rule_from_ui(void);
void esp32_link_run_local_servo_demo(void);
void esp32_link_center_servo(void);
void esp32_link_rule_init(void);
void esp32_link_rule_clear(void);
void esp32_link_rule_configure_threshold_temp(const char * op_text, int32_t threshold_tenths);
void esp32_link_rule_update_sample(aht20_sample_t const * sample);
void esp32_link_rule_tick_5ms(void);

#ifdef __cplusplus
}
#endif

#endif /* ESP32_LINK_H */
