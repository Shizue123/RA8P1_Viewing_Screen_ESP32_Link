/* app_ui.h - 新版 UI 公共接口（保持与 esp32_link.c / hal_entry.c 兼容）
 * v0.9.20: 并集 (ui版 + 除ui版独有 setter)
 *  - 来自 ui版: is_aht20_mock (hal_entry.c L82 用)
 *  - 来自除ui版: device_id / i2c_s1_scan / refresh_platform_state / clock_time / wifi_networks
 */
#ifndef APP_UI_H
#define APP_UI_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 主入口 */
void app_ui_create(void);

/* === 兼容旧 API（esp32_link.c 仍在调用）=== */
void app_ui_set_esp32_status(const char * text);
void app_ui_set_wifi_status(const char * text);
void app_ui_set_wifi_name(const char * text);
void app_ui_set_mqtt_status(const char * text);
void app_ui_set_device_id(const char * text);
void app_ui_set_aht20_status(const char * text);
void app_ui_set_aht20_measurement(const char * text);
void app_ui_set_i2c_s1_scan(const char * diag_text, const char * devices_text, uint8_t count);
void app_ui_refresh_platform_state(void);
void app_ui_set_last_rx(const char * text);
void app_ui_set_last_tx(const char * text);
void app_ui_set_request_id(const char * text);
void app_ui_set_script_id(const char * text);
void app_ui_set_intent_type(const char * text);
void app_ui_set_command_text(const char * text);
void app_ui_set_ack_status(const char * text);
void app_ui_set_control_status(const char * text);
void app_ui_set_touch_state(bool pressed, uint16_t x, uint16_t y);
void app_ui_set_touch_signal(const char * text);
void app_ui_set_touch_probe(const char * text);
void app_ui_set_input_status(const char * text);
void app_ui_set_candidate_status(const char * text);
void app_ui_mark_input_forwarded(const char * text);
void app_ui_set_clock_time(uint8_t hour, uint8_t minute, uint8_t second);
void app_ui_clear_wifi_networks(void);
void app_ui_add_wifi_network(const char * ssid, int16_t rssi_dbm, bool connected);
bool app_ui_touch_hits_input(int32_t x, int32_t y);
bool app_ui_take_input_submission(char * text, size_t text_size);

/* AHT20 详情页"模拟数据"开关状态查询；hal_entry.c 用它短路 aht20_refresh_ui */
bool app_ui_is_aht20_mock(void);

#ifdef __cplusplus
}
#endif

#endif /* APP_UI_H */