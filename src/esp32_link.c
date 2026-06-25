#include "esp32_link.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "app_ui.h"
#include "hal_data.h"
#include "lcd_spi.h"
#include "platform_ports.h"
#include "sg90_servo.h"

#if ESP32_LINK_ENABLE_FSP_UART
#include "r_uart_api.h"
#endif

#define ESP32_PING_INTERVAL_MS (2000U)
#define ESP32_TIMEOUT_MS       (15000U)
#define ESP32_RX_LINE_MAX      (320U)
#define ESP32_RX_QUEUE_DEPTH   (24U)
#define ESP32_TX_QUEUE_DEPTH   (12U)
#define ESP32_ID_TEXT_MAX      (64U)
#define ESP32_RULE_SEQUENCE_MAX_STEPS (16U)

static uint32_t g_elapsed_ms;
static uint32_t g_last_ping_ms;
static uint32_t g_last_rx_ms;
static bool g_waiting_pong;
static bool g_online;
static char g_current_request_id[ESP32_ID_TEXT_MAX];
static char g_current_script_id[ESP32_ID_TEXT_MAX];
static bool g_rule_active;
static bool g_rule_has_last_condition;
static bool g_rule_last_condition_met;
static bool g_rule_flash_active;
static uint32_t g_rule_flash_elapsed_ms;
static int32_t g_rule_threshold_tenths;
static uint8_t g_rule_operator;
static uint16_t g_rule_servo_angle_degrees;
static bool g_rule_has_last_temperature;
static int32_t g_rule_last_temperature_tenths;
static uint16_t g_rule_sequence_angles[ESP32_RULE_SEQUENCE_MAX_STEPS];
static uint16_t g_rule_sequence_durations_ms[ESP32_RULE_SEQUENCE_MAX_STEPS];
static uint8_t g_rule_sequence_step_count;
static uint8_t g_rule_sequence_step_index;
static uint32_t g_rule_sequence_step_elapsed_ms;
static bool g_rule_sequence_running;
static bool g_manual_sequence_running;
static uint32_t g_rule_cooldown_ms;
static uint32_t g_rule_cooldown_remaining_ms;

static void esp32_link_rule_clear_sequence(void);
static bool esp32_link_rule_add_sequence_step(uint16_t angle_degrees, uint16_t duration_ms);
static void esp32_link_rule_start_sequence(int32_t temperature_tenths);
static void esp32_link_manual_start_sequence(void);
static void esp32_link_publish_platform_port(platform_port_t const * port);
static void esp32_link_publish_platform_sample(platform_sample_t const * sample);
static bool esp32_link_copy_field_value(const char * text, const char * key, char * dest, size_t dest_size);
static bool esp32_link_parse_int_field(const char * text, const char * key, int32_t * value);
static bool esp32_link_parse_time_hms(const char * text, uint8_t * hour, uint8_t * minute, uint8_t * second);

enum
{
    RULE_OPERATOR_NONE = 0U,
    RULE_OPERATOR_GT,
    RULE_OPERATOR_GE,
    RULE_OPERATOR_LT,
    RULE_OPERATOR_LE,
};

#if ESP32_LINK_ENABLE_FSP_UART
static char g_rx_line[ESP32_RX_LINE_MAX];
static uint32_t g_rx_len;
static char g_rx_queue[ESP32_RX_QUEUE_DEPTH][ESP32_RX_LINE_MAX];
static volatile uint32_t g_rx_queue_head;
static volatile uint32_t g_rx_queue_tail;
static volatile uint32_t g_rx_queue_count;
static char g_tx_frame[ESP32_RX_LINE_MAX];
static char g_tx_queue[ESP32_TX_QUEUE_DEPTH][ESP32_RX_LINE_MAX];
static uint32_t g_tx_queue_head;
static uint32_t g_tx_queue_tail;
static uint32_t g_tx_queue_count;
static volatile bool g_tx_busy;
static volatile bool g_uart_error;
static volatile bool g_rx_overflow;

static bool esp32_link_enqueue_tx_line(const char * text);
static void esp32_link_try_send_next(void);

static const char * esp32_link_rule_operator_text(void)
{
    switch (g_rule_operator)
    {
        case RULE_OPERATOR_GT:
            return ">";
        case RULE_OPERATOR_GE:
            return ">=";
        case RULE_OPERATOR_LT:
            return "<";
        case RULE_OPERATOR_LE:
            return "<=";
        case RULE_OPERATOR_NONE:
        default:
            return "-";
    }
}

static uint8_t esp32_link_parse_rule_operator(const char * op_text)
{
    if (op_text == NULL) {
        return RULE_OPERATOR_NONE;
    }

    if (0 == strcmp(op_text, ">")) {
        return RULE_OPERATOR_GT;
    }
    if (0 == strcmp(op_text, ">=")) {
        return RULE_OPERATOR_GE;
    }
    if (0 == strcmp(op_text, "<")) {
        return RULE_OPERATOR_LT;
    }
    if (0 == strcmp(op_text, "<=")) {
        return RULE_OPERATOR_LE;
    }

    return RULE_OPERATOR_NONE;
}

static bool esp32_link_rule_compare_temp(int32_t temperature_tenths)
{
    switch (g_rule_operator)
    {
        case RULE_OPERATOR_GT:
            return temperature_tenths > g_rule_threshold_tenths;
        case RULE_OPERATOR_GE:
            return temperature_tenths >= g_rule_threshold_tenths;
        case RULE_OPERATOR_LT:
            return temperature_tenths < g_rule_threshold_tenths;
        case RULE_OPERATOR_LE:
            return temperature_tenths <= g_rule_threshold_tenths;
        case RULE_OPERATOR_NONE:
        default:
            return false;
    }
}

static void esp32_link_copy_id(char * dest, const char * text)
{
    size_t text_len;

    if (dest == NULL) {
        return;
    }

    if (text == NULL) {
        dest[0] = '\0';
        return;
    }

    text_len = strlen(text);
    if (text_len >= (ESP32_ID_TEXT_MAX - 1U)) {
        text_len = ESP32_ID_TEXT_MAX - 1U;
    }
    (void) memcpy(dest, text, text_len);
    dest[text_len] = '\0';
}

static bool esp32_link_copy_field_value(const char * text, const char * key, char * dest, size_t dest_size)
{
    const char * start;
    const char * end;
    size_t len;

    if ((text == NULL) || (key == NULL) || (dest == NULL) || (dest_size == 0U))
    {
        return false;
    }

    start = strstr(text, key);
    if (start == NULL)
    {
        dest[0] = '\0';
        return false;
    }

    start += strlen(key);
    end = strchr(start, ';');
    len = (end == NULL) ? strlen(start) : (size_t) (end - start);
    if (len >= dest_size)
    {
        len = dest_size - 1U;
    }

    (void) memcpy(dest, start, len);
    dest[len] = '\0';
    return true;
}

static bool esp32_link_parse_int_field(const char * text, const char * key, int32_t * value)
{
    char buffer[16];
    char * parse_end;
    long parsed_value;

    if ((value == NULL) || !esp32_link_copy_field_value(text, key, buffer, sizeof(buffer)))
    {
        return false;
    }

    parsed_value = strtol(buffer, &parse_end, 10);
    if ((parse_end == NULL) || (*parse_end != '\0'))
    {
        return false;
    }

    *value = (int32_t) parsed_value;
    return true;
}

static bool esp32_link_parse_time_hms(const char * text, uint8_t * hour, uint8_t * minute, uint8_t * second)
{
    const char * clock_text;
    int32_t parsed_hour;
    int32_t parsed_minute;
    int32_t parsed_second;

    if ((text == NULL) || (hour == NULL) || (minute == NULL) || (second == NULL))
    {
        return false;
    }

    clock_text = text;
    if ((strlen(text) >= 19U) &&
            (text[4] == '-') && (text[7] == '-') &&
            ((text[10] == 'T') || (text[10] == ' '))) {
        clock_text = text + 11U;
    } else if (strlen(text) != 8U) {
        return false;
    }

    if ((clock_text[2] != ':') || (clock_text[5] != ':'))
    {
        return false;
    }

    parsed_hour = ((int32_t) (clock_text[0] - '0') * 10) + (int32_t) (clock_text[1] - '0');
    parsed_minute = ((int32_t) (clock_text[3] - '0') * 10) + (int32_t) (clock_text[4] - '0');
    parsed_second = ((int32_t) (clock_text[6] - '0') * 10) + (int32_t) (clock_text[7] - '0');

    if ((parsed_hour < 0) || (parsed_hour >= 24) ||
            (parsed_minute < 0) || (parsed_minute >= 60) ||
            (parsed_second < 0) || (parsed_second >= 60))
    {
        return false;
    }

    *hour = (uint8_t) parsed_hour;
    *minute = (uint8_t) parsed_minute;
    *second = (uint8_t) parsed_second;
    return true;
}

static bool esp32_link_publish_ping_if_idle(void)
{
    if (g_waiting_pong) {
        return false;
    }

    if (!esp32_link_enqueue_tx_line("ping")) {
        return false;
    }

    g_waiting_pong = true;
    esp32_link_try_send_next();
    g_last_ping_ms = g_elapsed_ms;
    return true;
}

static void esp32_link_queue_rx_line(void)
{
    uint32_t write_index = g_rx_queue_tail;

    if (g_rx_queue_count >= ESP32_RX_QUEUE_DEPTH) {
        g_rx_overflow = true;
        return;
    }

    (void) memcpy(g_rx_queue[write_index], g_rx_line, ESP32_RX_LINE_MAX);
    g_rx_queue_tail = (write_index + 1U) % ESP32_RX_QUEUE_DEPTH;
    g_rx_queue_count++;
}

static bool esp32_link_fetch_rx_line(char * dest, size_t dest_size)
{
    bool ready = false;

    if ((dest == NULL) || (dest_size == 0U)) {
        return false;
    }

    __disable_irq();
    if (g_rx_queue_count > 0U) {
        uint32_t read_index = g_rx_queue_head;
        (void) strncpy(dest, g_rx_queue[read_index], dest_size - 1U);
        dest[dest_size - 1U] = '\0';
        g_rx_queue_head = (read_index + 1U) % ESP32_RX_QUEUE_DEPTH;
        g_rx_queue_count--;
        ready = true;
    }
    __enable_irq();

    return ready;
}

static void esp32_link_set_last_tx_summary(const char * text)
{
    if (text == NULL) {
        app_ui_set_last_tx("-");
        return;
    }

    if (strcmp(text, "ping") == 0) {
        app_ui_set_last_tx("ping");
    } else if (strcmp(text, "ra8p1-uart-link-boot") == 0) {
        app_ui_set_last_tx("boot");
    } else if (strcmp(text, "ra8p1-ready") == 0) {
        app_ui_set_last_tx("ready");
    } else if (strncmp(text, "ack:req=", 8U) == 0) {
        app_ui_set_last_tx("deploy_ack");
    } else if (strncmp(text, "aht20:", 6U) == 0) {
        app_ui_set_last_tx("aht20 sample");
    } else if (strncmp(text, "i2c:", 4U) == 0) {
        app_ui_set_last_tx("i2c scan");
    } else if (strcmp(text, "wifi:scan") == 0) {
        app_ui_set_last_tx("wifi scan");
    } else if (strncmp(text, "wifi:connect:", 13U) == 0) {
        app_ui_set_last_tx("wifi connect");
    } else {
        app_ui_set_last_tx(text);
    }
}

static bool esp32_link_enqueue_tx_line(const char * text)
{
    size_t text_len;

    if (text == NULL) {
        return false;
    }

    text_len = strlen(text);
    if (text_len > (ESP32_RX_LINE_MAX - 3U)) {
        app_ui_set_last_tx("tx line too long");
        return false;
    }

    if (g_tx_queue_count >= ESP32_TX_QUEUE_DEPTH) {
        app_ui_set_last_tx("tx queue full");
        return false;
    }

    (void) strncpy(g_tx_queue[g_tx_queue_tail], text, ESP32_RX_LINE_MAX - 1U);
    g_tx_queue[g_tx_queue_tail][ESP32_RX_LINE_MAX - 1U] = '\0';
    g_tx_queue_tail = (g_tx_queue_tail + 1U) % ESP32_TX_QUEUE_DEPTH;
    g_tx_queue_count++;
    return true;
}

static void esp32_link_try_send_next(void)
{
    char label_text[ESP32_RX_LINE_MAX];
    size_t text_len;
    fsp_err_t err;

    if (g_tx_busy || (g_tx_queue_count == 0U)) {
        return;
    }

    (void) strncpy(g_tx_frame, g_tx_queue[g_tx_queue_head], sizeof(g_tx_frame) - 1U);
    g_tx_frame[sizeof(g_tx_frame) - 1U] = '\0';
    (void) strncpy(label_text, g_tx_frame, sizeof(label_text) - 1U);
    label_text[sizeof(label_text) - 1U] = '\0';
    text_len = strlen(g_tx_frame);
    g_tx_frame[text_len] = '\r';
    g_tx_frame[text_len + 1U] = '\n';
    g_tx_frame[text_len + 2U] = '\0';

    err = g_uart_esp32.p_api->write(g_uart_esp32.p_ctrl, (uint8_t const *) g_tx_frame, text_len + 2U);
    if (err != FSP_SUCCESS) {
        app_ui_set_esp32_status("uart write fail");
        return;
    }

    g_tx_busy = true;
    g_tx_queue_head = (g_tx_queue_head + 1U) % ESP32_TX_QUEUE_DEPTH;
    g_tx_queue_count--;
    esp32_link_set_last_tx_summary(label_text);
}

static void esp32_link_publish_line(const char * text)
{
    if (!esp32_link_enqueue_tx_line(text)) {
        return;
    }

    esp32_link_try_send_next();
}

static void esp32_link_publish_platform_port(platform_port_t const * port)
{
    char capability_text[160];
    char line[ESP32_RX_LINE_MAX];
    size_t written = 0U;

    if (port == NULL) {
        return;
    }

    capability_text[0] = '\0';
    for (uint8_t i = 0U; i < port->capability_count; i++) {
        platform_capability_t const * capability = &port->capabilities[i];
        written += (size_t) snprintf(capability_text + written,
                sizeof(capability_text) - written,
                "%s%s|%s|%s|%s",
                (i == 0U) ? "" : ",",
                capability->id,
                capability->unit,
                capability->access,
                capability->status);
        if (written >= (sizeof(capability_text) - 1U)) {
            break;
        }
    }

    (void) snprintf(line,
            sizeof(line),
            "port:id=%s;physical=%s;channel=%s;type=%s;act=%s;status=%s;diag=%s;mid=%s;mtype=%s;mclass=%s;drv=%s;mstate=%s;bind=%s;dkey=%s;conf=%s;addr=%s;caps=%s;ts=%lu",
            port->port_id,
            port->physical_port,
            port->channel,
            port->type,
            port->activation,
            port->status,
            port->diag,
            port->module.module_id,
            port->module.module_type,
            port->module.module_class,
            port->module.driver,
            port->module.model_state,
            port->module.binding_source,
            port->module.device_key,
            port->module.confidence,
            port->module.address,
            capability_text,
            (unsigned long) port->last_sample_ms);
    esp32_link_publish_line(line);
}

static void esp32_link_publish_platform_sample(platform_sample_t const * sample)
{
    char line[ESP32_RX_LINE_MAX];
    int32_t value_tenths;

    if ((sample == NULL) || !sample->valid) {
        return;
    }

    value_tenths = (int32_t) (sample->value >= 0.0f ? ((sample->value * 10.0f) + 0.5f)
            : ((sample->value * 10.0f) - 0.5f));
    (void) snprintf(line,
            sizeof(line),
            "sample:port=%s;module=%s;cap=%s;value=%ld.%ld;unit=%s;ts=%lu",
            sample->port_id,
            sample->module_type,
            sample->capability,
            (long) (value_tenths / 10),
            (long) labs((long) (value_tenths % 10)),
            sample->unit,
            (unsigned long) sample->ts_ms);
    esp32_link_publish_line(line);
}

void esp32_link_publish_platform_snapshot(void)
{
    size_t count;

    count = platform_ports_get_port_count();
    for (size_t i = 0U; i < count; i++) {
        esp32_link_publish_platform_port(platform_ports_get_port(i));
    }

    count = platform_ports_get_sample_count();
    for (size_t i = 0U; i < count; i++) {
        esp32_link_publish_platform_sample(platform_ports_get_sample(i));
    }
}

void esp32_link_submit_nl_text(const char * text)
{
    char line[ESP32_RX_LINE_MAX];

    if ((text == NULL) || (text[0] == '\0')) {
        app_ui_set_control_status("输入为空");
        return;
    }

    (void) snprintf(line, sizeof(line), "nl:%s", text);
    if (!esp32_link_enqueue_tx_line(line)) {
        app_ui_set_control_status("上云队列满");
        return;
    }

    esp32_link_try_send_next();
    app_ui_set_control_status("已送云端");
}

void esp32_link_request_sync(void)
{
#if ESP32_LINK_ENABLE_FSP_UART
    esp32_link_publish_line("ra8p1-ready");
    esp32_link_publish_ra8p1_uid();
    (void) esp32_link_publish_ping_if_idle();
#endif
    app_ui_set_input_status("sync sent");
    app_ui_set_control_status("sync requested");
}

void esp32_link_request_wifi_scan(void)
{
#if ESP32_LINK_ENABLE_FSP_UART
    esp32_link_publish_line("wifi:scan");
#endif
}

void esp32_link_request_wifi_connect(const char * ssid)
{
    char line[ESP32_RX_LINE_MAX];

    if ((ssid == NULL) || (ssid[0] == '\0'))
    {
        return;
    }

    (void) snprintf(line, sizeof(line), "wifi:connect:%s", ssid);
#if ESP32_LINK_ENABLE_FSP_UART
    esp32_link_publish_line(line);
#endif
}

void esp32_link_publish_ra8p1_uid(void)
{
#if ESP32_LINK_ENABLE_FSP_UART
    bsp_unique_id_t const * uid = R_BSP_UniqueIdGet();
    char text[64];

    if (uid == NULL) {
        return;
    }

    (void) snprintf(text,
            sizeof(text),
            "ra8p1_uid:%08lX%08lX%08lX%08lX",
            (unsigned long) uid->unique_id_words[0],
            (unsigned long) uid->unique_id_words[1],
            (unsigned long) uid->unique_id_words[2],
            (unsigned long) uid->unique_id_words[3]);
    esp32_link_publish_line(text);
#endif
}

void esp32_link_clear_rule_from_ui(void)
{
    esp32_link_rule_clear();
    esp32_link_publish_rule_state("IDLE", "UI_CLEAR", g_rule_has_last_temperature, g_rule_last_temperature_tenths);
    app_ui_set_input_status("rule cleared");
    app_ui_set_control_status("rule cleared");
}

void esp32_link_run_local_servo_demo(void)
{
    esp32_link_rule_clear();
    esp32_link_rule_clear_sequence();
    (void) esp32_link_rule_add_sequence_step(30U, 300U);
    (void) esp32_link_rule_add_sequence_step(150U, 300U);
    (void) esp32_link_rule_add_sequence_step(30U, 300U);
    (void) esp32_link_rule_add_sequence_step(150U, 300U);
    (void) esp32_link_rule_add_sequence_step(90U, 260U);
    g_rule_cooldown_remaining_ms = 0U;
    app_ui_set_input_status("servo demo");
    esp32_link_rule_start_sequence(g_rule_has_last_temperature ? g_rule_last_temperature_tenths : 0);
}

void esp32_link_center_servo(void)
{
    esp32_link_rule_clear();
    sg90_servo_configure_angle(90U);
    sg90_servo_set_enabled(true);
    sg90_servo_set_active(false);
    platform_ports_set_pwm0_execution_feedback(90U, "execution_feedback");
    app_ui_set_input_status("servo center");
    app_ui_set_control_status("servo center");
    esp32_link_publish_platform_snapshot();
}

static void esp32_link_publish_deploy_ack(void)
{
    char text[ESP32_RX_LINE_MAX];

    if ((g_current_request_id[0] == '\0') || (g_current_script_id[0] == '\0')) {
        return;
    }

    (void) snprintf(text, sizeof(text), "ack:req=%s;script=%s;code=0;msg=accepted",
            g_current_request_id,
            g_current_script_id);
    esp32_link_publish_line(text);
}

void esp32_link_rule_init(void)
{
    g_rule_active = false;
    g_rule_has_last_condition = false;
    g_rule_last_condition_met = false;
    g_rule_flash_active = false;
    g_rule_flash_elapsed_ms = 0U;
    g_manual_sequence_running = false;
    g_rule_threshold_tenths = 0;
    g_rule_operator = RULE_OPERATOR_NONE;
    g_rule_servo_angle_degrees = 180U;
    g_rule_has_last_temperature = false;
    g_rule_last_temperature_tenths = 0;
    esp32_link_rule_clear_sequence();
    g_rule_cooldown_ms = 30000U;
    g_rule_cooldown_remaining_ms = 0U;
    sg90_servo_configure_angle(g_rule_servo_angle_degrees);
    sg90_servo_set_enabled(false);
    sg90_servo_set_active(false);
    platform_ports_set_pwm0_configured();
    led_write(BSP_IO_LEVEL_HIGH);
    app_ui_set_control_status("本地待命");
}

void esp32_link_rule_clear(void)
{
    g_rule_active = false;
    g_rule_has_last_condition = false;
    g_rule_last_condition_met = false;
    g_rule_flash_active = false;
    g_rule_flash_elapsed_ms = 0U;
    g_manual_sequence_running = false;
    g_rule_threshold_tenths = 0;
    g_rule_operator = RULE_OPERATOR_NONE;
    g_rule_servo_angle_degrees = 180U;
    esp32_link_rule_clear_sequence();
    g_rule_cooldown_remaining_ms = 0U;
    sg90_servo_configure_angle(g_rule_servo_angle_degrees);
    sg90_servo_set_enabled(false);
    sg90_servo_set_active(false);
    platform_ports_set_pwm0_configured();
    led_write(BSP_IO_LEVEL_HIGH);
    app_ui_set_control_status("本地待命");
}

static bool esp32_link_extract_servo_config(const char * text, uint16_t * angle_degrees)
{
    long parsed_angle;
    char * end_ptr = NULL;

    if ((text == NULL) || (angle_degrees == NULL)) {
        return false;
    }

    if (strstr(text, "angle=") != text) {
        return false;
    }

    parsed_angle = strtol(text + 6, &end_ptr, 10);
    if ((end_ptr == NULL) || (*end_ptr != '\0')) {
        return false;
    }

    if (parsed_angle < 0L) {
        parsed_angle = 0L;
    }
    if (parsed_angle > 180L) {
        parsed_angle = 180L;
    }

    *angle_degrees = (uint16_t) parsed_angle;
    return true;
}

static void esp32_link_rule_clear_sequence(void)
{
    g_rule_sequence_step_count = 0U;
    g_rule_sequence_step_index = 0U;
    g_rule_sequence_step_elapsed_ms = 0U;
    g_rule_sequence_running = false;
    g_manual_sequence_running = false;
    sg90_servo_set_active(false);
}

static bool esp32_link_extract_sequence_step(const char * text, uint16_t * angle_degrees, uint16_t * duration_ms)
{
    const char * angle_start;
    const char * duration_start;
    long parsed_angle;
    long parsed_duration;
    char * end_ptr = NULL;

    if ((text == NULL) || (angle_degrees == NULL) || (duration_ms == NULL)) {
        return false;
    }

    angle_start = strstr(text, "angle=");
    duration_start = strstr(text, ";ms=");
    if ((angle_start == NULL) || (duration_start == NULL)) {
        return false;
    }

    angle_start += 6;
    parsed_angle = strtol(angle_start, &end_ptr, 10);
    if ((end_ptr == NULL) || (end_ptr != duration_start)) {
        return false;
    }

    duration_start += 4;
    parsed_duration = strtol(duration_start, &end_ptr, 10);
    if ((end_ptr == NULL) || (*end_ptr != '\0')) {
        return false;
    }

    if (parsed_angle < 0L) {
        parsed_angle = 0L;
    }
    if (parsed_angle > 180L) {
        parsed_angle = 180L;
    }
    if (parsed_duration < 50L) {
        parsed_duration = 50L;
    }
    if (parsed_duration > 5000L) {
        parsed_duration = 5000L;
    }

    *angle_degrees = (uint16_t) parsed_angle;
    *duration_ms = (uint16_t) parsed_duration;
    return true;
}

static bool esp32_link_rule_add_sequence_step(uint16_t angle_degrees, uint16_t duration_ms)
{
    if (g_rule_sequence_step_count >= ESP32_RULE_SEQUENCE_MAX_STEPS) {
        return false;
    }

    g_rule_sequence_angles[g_rule_sequence_step_count] = angle_degrees;
    g_rule_sequence_durations_ms[g_rule_sequence_step_count] = duration_ms;
    g_rule_sequence_step_count++;
    return true;
}

static bool esp32_link_extract_cooldown_config(const char * text, uint32_t * cooldown_ms)
{
    const char * value_start;
    long parsed_value;
    char * end_ptr = NULL;

    if ((text == NULL) || (cooldown_ms == NULL)) {
        return false;
    }

    if (strstr(text, "ms=") != text) {
        return false;
    }

    value_start = text + 3;
    parsed_value = strtol(value_start, &end_ptr, 10);
    if ((end_ptr == NULL) || (*end_ptr != '\0')) {
        return false;
    }

    if (parsed_value < 0L) {
        parsed_value = 0L;
    }
    if (parsed_value > 600000L) {
        parsed_value = 600000L;
    }

    *cooldown_ms = (uint32_t) parsed_value;
    return true;
}

static void esp32_link_rule_start_sequence(int32_t temperature_tenths)
{
    if (g_rule_sequence_step_count == 0U) {
        return;
    }

    g_rule_sequence_running = true;
    g_manual_sequence_running = false;
    g_rule_sequence_step_index = 0U;
    g_rule_sequence_step_elapsed_ms = 0U;
    g_rule_servo_angle_degrees = g_rule_sequence_angles[0];
    sg90_servo_configure_angle(g_rule_servo_angle_degrees);
    sg90_servo_set_enabled(true);
    sg90_servo_set_active(true);
    platform_ports_set_pwm0_execution_feedback(g_rule_servo_angle_degrees, "execution_feedback");
    g_rule_flash_active = true;
    g_rule_flash_elapsed_ms = 0U;
    app_ui_set_control_status("执行 SG90 序列");
    esp32_link_publish_rule_state("TRIGGERED", "PROGRAM_START", true, temperature_tenths);
}

static void esp32_link_manual_start_sequence(void)
{
    if (g_rule_sequence_step_count == 0U) {
        app_ui_set_control_status("手动序列为空");
        esp32_link_publish_rule_state("ERROR", "MANUAL_EMPTY", false, 0);
        return;
    }

    g_rule_active = false;
    g_rule_sequence_running = true;
    g_manual_sequence_running = true;
    g_rule_sequence_step_index = 0U;
    g_rule_sequence_step_elapsed_ms = 0U;
    g_rule_cooldown_remaining_ms = 0U;
    g_rule_servo_angle_degrees = g_rule_sequence_angles[0];
    sg90_servo_configure_angle(g_rule_servo_angle_degrees);
    sg90_servo_set_enabled(true);
    sg90_servo_set_active(true);
    platform_ports_set_pwm0_execution_feedback(g_rule_servo_angle_degrees, "execution_feedback");
    g_rule_flash_active = true;
    g_rule_flash_elapsed_ms = 0U;
    app_ui_set_control_status("手动执行 SG90");
    esp32_link_publish_rule_state("TRIGGERED", "MANUAL_START", false, 0);
}

void esp32_link_rule_configure_threshold_temp(const char * op_text, int32_t threshold_tenths)
{
    char summary[32];
    int32_t absolute_tenths;

    g_rule_operator = esp32_link_parse_rule_operator(op_text);
    if (g_rule_operator == RULE_OPERATOR_NONE) {
        esp32_link_rule_clear();
        app_ui_set_control_status("规则无效");
        esp32_link_publish_rule_state("ERROR", "RULE_INVALID", g_rule_has_last_temperature, g_rule_last_temperature_tenths);
        return;
    }

    g_rule_active = true;
    g_rule_has_last_condition = false;
    g_rule_last_condition_met = false;
    g_rule_threshold_tenths = threshold_tenths;
    g_rule_cooldown_remaining_ms = 0U;
    sg90_servo_set_enabled(true);
    sg90_servo_set_active(false);
    absolute_tenths = threshold_tenths >= 0 ? threshold_tenths : -threshold_tenths;

    (void) snprintf(summary, sizeof(summary), "阈值 %s %ld.%ldC",
            op_text,
            (long) (threshold_tenths / 10),
            (long) (absolute_tenths % 10));
    app_ui_set_control_status(summary);
    esp32_link_publish_rule_state("ARMED", "RULE_UPDATED", g_rule_has_last_temperature, g_rule_last_temperature_tenths);
}

void esp32_link_rule_update_sample(aht20_sample_t const * sample)
{
    int32_t temperature_tenths;
    bool condition_met;

    if (sample == NULL) {
        return;
    }

    temperature_tenths = (int32_t) (sample->temperature_c >= 0.0f ? ((sample->temperature_c * 10.0f) + 0.5f)
            : ((sample->temperature_c * 10.0f) - 0.5f));
    g_rule_has_last_temperature = true;
    g_rule_last_temperature_tenths = temperature_tenths;

    if (!g_rule_active) {
        return;
    }

    condition_met = esp32_link_rule_compare_temp(temperature_tenths);

    if (g_rule_sequence_running) {
        g_rule_has_last_condition = true;
        g_rule_last_condition_met = condition_met;
        return;
    }

    if (g_rule_has_last_condition && (condition_met == g_rule_last_condition_met)) {
        return;
    }

    g_rule_has_last_condition = true;
    g_rule_last_condition_met = condition_met;

    if (condition_met) {
        if (g_rule_sequence_step_count > 0U) {
            if (g_rule_sequence_running) {
                app_ui_set_control_status("序列执行中");
                return;
            }
            if (g_rule_cooldown_remaining_ms > 0U) {
                app_ui_set_control_status("规则冷却中");
                return;
            }
            esp32_link_rule_start_sequence(temperature_tenths);
            return;
        }
        g_rule_flash_active = true;
        g_rule_flash_elapsed_ms = 0U;
        sg90_servo_set_active(true);
        app_ui_set_control_status("已触发 SG90");
        esp32_link_publish_rule_state("TRIGGERED", "COND_TRUE", true, temperature_tenths);
        return;
    }

    led_write(BSP_IO_LEVEL_HIGH);
    sg90_servo_set_active(false);
    app_ui_set_control_status("规则待命");
    esp32_link_publish_rule_state("ARMED", "COND_FALSE", true, temperature_tenths);
}

void esp32_link_rule_tick_5ms(void)
{
    sg90_servo_tick_5ms();

    if (g_rule_cooldown_remaining_ms > 0U) {
        g_rule_cooldown_remaining_ms = (g_rule_cooldown_remaining_ms > 5U) ? (g_rule_cooldown_remaining_ms - 5U) : 0U;
    }

    if (g_rule_sequence_running) {
        uint16_t duration_ms = g_rule_sequence_durations_ms[g_rule_sequence_step_index];

        g_rule_sequence_step_elapsed_ms += 5U;
        if (g_rule_sequence_step_elapsed_ms >= duration_ms) {
            g_rule_sequence_step_elapsed_ms = 0U;
            g_rule_sequence_step_index++;

            if (g_rule_sequence_step_index < g_rule_sequence_step_count) {
                g_rule_servo_angle_degrees = g_rule_sequence_angles[g_rule_sequence_step_index];
                sg90_servo_configure_angle(g_rule_servo_angle_degrees);
                platform_ports_set_pwm0_execution_feedback(g_rule_servo_angle_degrees, "execution_feedback");
            } else {
                g_rule_sequence_running = false;
                if (g_manual_sequence_running) {
                    g_rule_cooldown_remaining_ms = 0U;
                } else {
                    g_rule_cooldown_remaining_ms = g_rule_cooldown_ms;
                }
                if (g_manual_sequence_running) {
                    g_manual_sequence_running = false;
                    /*
                     * Manual actions hold the last requested angle.  An explicit
                     * auto-reset request is represented by a final 90 degree
                     * sequence step, so this remains backward compatible.
                     */
                    sg90_servo_set_active(true);
                    platform_ports_set_pwm0_execution_feedback(g_rule_servo_angle_degrees, "execution_feedback");
                    app_ui_set_control_status("手动序列完成");
                    esp32_link_publish_rule_state("DONE", "MANUAL_DONE", false, 0);
                } else {
                    g_rule_servo_angle_degrees = 90U;
                    sg90_servo_configure_angle(g_rule_servo_angle_degrees);
                    sg90_servo_set_active(false);
                    platform_ports_set_pwm0_execution_feedback(g_rule_servo_angle_degrees, "execution_feedback");
                    app_ui_set_control_status("序列完成");
                    esp32_link_publish_rule_state("DONE", "PROGRAM_DONE", g_rule_has_last_temperature, g_rule_last_temperature_tenths);
                }
            }
        }
    }

    if (!g_rule_flash_active) {
        return;
    }

    g_rule_flash_elapsed_ms += 5U;
    if (g_rule_flash_elapsed_ms >= 600U) {
        g_rule_flash_active = false;
        led_write(BSP_IO_LEVEL_HIGH);
        return;
    }

    if (((g_rule_flash_elapsed_ms / 100U) % 2U) == 0U) {
        led_write(BSP_IO_LEVEL_LOW);
    } else {
        led_write(BSP_IO_LEVEL_HIGH);
    }
}

static bool esp32_link_extract_rule_config(const char * text, char * op_text, size_t op_text_size, int32_t * value_tenths)
{
    const char * op_start;
    const char * value_start;
    int sign = 1;
    int32_t parsed_value = 0;

    if ((text == NULL) || (op_text == NULL) || (op_text_size < 2U) || (value_tenths == NULL)) {
        return false;
    }

    if (strstr(text, "sensor=temp;") != text) {
        return false;
    }

    op_start = strstr(text, "op=");
    if (op_start == NULL) {
        return false;
    }
    op_start += 3;

    if ((*op_start != '>') && (*op_start != '<')) {
        return false;
    }

    op_text[0] = *op_start;
    op_text[1] = '\0';
    if ((op_start[1] == '=') && (op_text_size >= 3U)) {
        op_text[1] = '=';
        op_text[2] = '\0';
    }

    if (!strstr(text, "value=")) {
        return false;
    }

    value_start = strstr(text, "value=");
    value_start += 6;
    if (*value_start == '-') {
        sign = -1;
        value_start++;
    }
    if ((*value_start < '0') || (*value_start > '9')) {
        return false;
    }

    while ((*value_start >= '0') && (*value_start <= '9')) {
        parsed_value = (parsed_value * 10) + (int32_t) (*value_start - '0');
        value_start++;
    }

    if (*value_start != '\0') {
        return false;
    }

    *value_tenths = parsed_value * sign;
    return true;
}

static void esp32_link_handle_line(const char * line)
{
    if ((line == NULL) || (line[0] == '\0')) {
        return;
    }

    g_last_rx_ms = g_elapsed_ms;
    app_ui_set_last_rx(line);

    if (strcmp(line, "pong") == 0) {
        bool was_online = g_online;
        g_waiting_pong = false;
        g_online = true;
        app_ui_set_esp32_status("online");
        platform_ports_set_uart_bridge(true, "ok");
        if (!was_online) {
            esp32_link_publish_platform_snapshot();
        }
        return;
    }

    if (strcmp(line, "esp32-ready") == 0) {
        bool was_online = g_online;
        g_waiting_pong = false;
        g_online = true;
        app_ui_set_esp32_status("online");
        platform_ports_set_uart_bridge(true, "ok");
        if (!was_online) {
            esp32_link_publish_platform_snapshot();
        }
        (void) esp32_link_publish_ping_if_idle();
        return;
    }

    if (strcmp(line, "esp32-heartbeat") == 0) {
        bool was_online = g_online;
        g_online = true;
        app_ui_set_esp32_status("online");
        platform_ports_set_uart_bridge(true, "ok");
        if (!was_online) {
            esp32_link_publish_platform_snapshot();
        }
        return;
    }

    if (strncmp(line, "wifi:", 5U) == 0) {
        app_ui_set_wifi_status(line + 5);
        return;
    }

    if (strncmp(line, "wifi-ssid:", 10U) == 0) {
        app_ui_set_wifi_name(line + 10);
        return;
    }

    if (strncmp(line, "time:", 5U) == 0) {
        uint8_t hour = 0U;
        uint8_t minute = 0U;
        uint8_t second = 0U;

        if (esp32_link_parse_time_hms(line + 5, &hour, &minute, &second)) {
            app_ui_set_clock_time(hour, minute, second);
        }
        return;
    }

    if (strncmp(line, "wifi-scan:clear", 15U) == 0) {
        app_ui_clear_wifi_networks();
        return;
    }

    if (strncmp(line, "wifi-scan:item=", 15U) == 0) {
        char ssid[64];
        char state[24];
        int32_t rssi_dbm = 0;

        if (!esp32_link_copy_field_value(line, "item=", ssid, sizeof(ssid))) {
            return;
        }
        if (!esp32_link_parse_int_field(line, "rssi=", &rssi_dbm)) {
            rssi_dbm = 0;
        }
        if (!esp32_link_copy_field_value(line, "state=", state, sizeof(state))) {
            state[0] = '\0';
        }
        app_ui_add_wifi_network(ssid, (int16_t) rssi_dbm, (strcmp(state, "connected") == 0));
        return;
    }

    if (strncmp(line, "mqtt:", 5U) == 0) {
        app_ui_set_mqtt_status(line + 5);
        return;
    }

    if (strncmp(line, "device-id:", 10U) == 0) {
        app_ui_set_device_id(line + 10);
        return;
    }

    if (strncmp(line, "req:", 4U) == 0) {
        esp32_link_copy_id(g_current_request_id, line + 4);
        app_ui_set_request_id(line + 4);
        app_ui_set_ack_status("pending");
        return;
    }

    if (strncmp(line, "script:", 7U) == 0) {
        esp32_link_copy_id(g_current_script_id, line + 7);
        app_ui_set_script_id(line + 7);
        app_ui_set_ack_status("pending");
        return;
    }

    if (strncmp(line, "cmd:", 4U) == 0) {
        app_ui_set_command_text(line + 4);
        return;
    }

    if (strncmp(line, "input:", 6U) == 0) {
        app_ui_set_input_status(line + 6);
        app_ui_set_control_status(line + 6);
        return;
    }

    if (strncmp(line, "rule:", 5U) == 0) {
        char op_text[3];
        int32_t threshold_tenths = 0;

        if (strcmp(line + 5, "clear") == 0) {
            esp32_link_rule_clear();
            app_ui_set_control_status("规则已清除");
            esp32_link_publish_rule_state("IDLE", "RULE_CLEARED", g_rule_has_last_temperature, g_rule_last_temperature_tenths);
        } else if (esp32_link_extract_rule_config(line + 5, op_text, sizeof(op_text), &threshold_tenths)) {
            esp32_link_rule_configure_threshold_temp(op_text, threshold_tenths);
        } else {
            esp32_link_rule_clear();
            app_ui_set_control_status("规则无效");
            esp32_link_publish_rule_state("ERROR", "RULE_INVALID", g_rule_has_last_temperature, g_rule_last_temperature_tenths);
        }
        return;
    }

    if (strncmp(line, "servo:", 6U) == 0) {
        uint16_t angle_degrees = 180U;

        if (esp32_link_extract_servo_config(line + 6, &angle_degrees)) {
            g_rule_servo_angle_degrees = angle_degrees;
            sg90_servo_configure_angle(angle_degrees);
        }
        return;
    }

    if (strncmp(line, "seq:", 4U) == 0) {
        uint16_t angle_degrees = 90U;
        uint16_t duration_ms = 350U;

        if (strcmp(line + 4, "clear") == 0) {
            esp32_link_rule_clear_sequence();
        } else if (esp32_link_extract_sequence_step(line + 4, &angle_degrees, &duration_ms)) {
            if (!esp32_link_rule_add_sequence_step(angle_degrees, duration_ms)) {
                app_ui_set_control_status("序列过长");
                esp32_link_publish_rule_state("ERROR", "SEQ_FULL", g_rule_has_last_temperature, g_rule_last_temperature_tenths);
            }
        }
        return;
    }

    if (strncmp(line, "cooldown:", 9U) == 0) {
        uint32_t cooldown_ms = 30000U;

        if (esp32_link_extract_cooldown_config(line + 9, &cooldown_ms)) {
            g_rule_cooldown_ms = cooldown_ms;
        }
        return;
    }

    if (strncmp(line, "manual:", 7U) == 0) {
        if (strstr(line + 7, "start") == line + 7) {
            esp32_link_manual_start_sequence();
        }
        return;
    }

    if (strncmp(line, "intent:", 7U) == 0) {
        app_ui_set_intent_type(line + 7);
        app_ui_set_ack_status("accepted");
        esp32_link_publish_deploy_ack();
        return;
    }
}

void esp32_uart_callback(uart_callback_args_t * p_args)
{
    char ch;

    if (p_args == NULL) {
        return;
    }

    if (p_args->event == UART_EVENT_TX_COMPLETE) {
        g_tx_busy = false;
        return;
    }

    if ((p_args->event == UART_EVENT_ERR_PARITY) || (p_args->event == UART_EVENT_ERR_FRAMING)
            || (p_args->event == UART_EVENT_ERR_OVERFLOW) || (p_args->event == UART_EVENT_BREAK_DETECT)) {
        g_uart_error = true;
        return;
    }

    if (p_args->event != UART_EVENT_RX_CHAR) {
        return;
    }

    ch = (char) p_args->data;
    if (ch == '\r') {
        return;
    }

    if (ch == '\n') {
        g_rx_line[g_rx_len] = '\0';
        esp32_link_queue_rx_line();
        g_rx_len = 0U;
        return;
    }

    if (g_rx_len < (ESP32_RX_LINE_MAX - 1U)) {
        g_rx_line[g_rx_len++] = ch;
    } else {
        g_rx_len = 0U;
        g_rx_overflow = true;
    }
}
#endif

void esp32_link_init(void)
{
    g_elapsed_ms = 0U;
    g_last_ping_ms = 0U;
    g_last_rx_ms = 0U;
    g_waiting_pong = false;
    g_online = false;
    g_current_request_id[0] = '\0';
    g_current_script_id[0] = '\0';
    platform_ports_set_uart_bridge(false, "waiting");

#if ESP32_LINK_ENABLE_FSP_UART
    g_tx_busy = false;
    g_uart_error = false;
    g_rx_len = 0U;
    g_rx_overflow = false;
    g_rx_queue_head = 0U;
    g_rx_queue_tail = 0U;
    g_rx_queue_count = 0U;
    g_tx_queue_head = 0U;
    g_tx_queue_tail = 0U;
    g_tx_queue_count = 0U;
    g_rx_line[0] = '\0';
    g_tx_frame[0] = '\0';

    if (g_uart_esp32.p_api->open(g_uart_esp32.p_ctrl, g_uart_esp32.p_cfg) == FSP_SUCCESS) {
        app_ui_set_esp32_status("waiting");
        esp32_link_publish_line("ra8p1-uart-link-boot");
        esp32_link_publish_line("ra8p1-ready");
        esp32_link_publish_platform_snapshot();
        (void) esp32_link_publish_ping_if_idle();
    } else {
        app_ui_set_esp32_status("uart open fail");
        platform_ports_set_uart_bridge(false, "uart_open_fail");
    }
#else
    app_ui_set_esp32_status("uart cfg needed");
    app_ui_set_last_rx("add g_uart_esp32");
    app_ui_set_last_tx("-");
#endif
}

void esp32_link_poll_5ms(void)
{
#if ESP32_LINK_ENABLE_FSP_UART
    char line[ESP32_RX_LINE_MAX];
#endif

    g_elapsed_ms += 5U;

#if ESP32_LINK_ENABLE_FSP_UART
    if (g_rx_overflow) {
        g_rx_overflow = false;
        app_ui_set_last_rx("line too long");
    }

    if (g_uart_error) {
        g_uart_error = false;
        g_waiting_pong = false;
        g_online = false;
        app_ui_set_esp32_status("uart error");
        platform_ports_set_uart_bridge(false, "uart_error");
        esp32_link_publish_platform_snapshot();
    }

    esp32_link_try_send_next();

    while (esp32_link_fetch_rx_line(line, sizeof(line))) {
        esp32_link_handle_line(line);
    }

    if ((g_elapsed_ms - g_last_ping_ms) >= ESP32_PING_INTERVAL_MS) {
        (void) esp32_link_publish_ping_if_idle();
    }

    if (g_online && ((g_elapsed_ms - g_last_rx_ms) >= ESP32_TIMEOUT_MS)) {
        g_waiting_pong = false;
        g_online = false;
        app_ui_set_esp32_status("timeout");
        platform_ports_set_uart_bridge(false, "timeout");
        esp32_link_publish_platform_snapshot();
    }
#else
    (void) g_last_ping_ms;
    (void) g_last_rx_ms;
#endif
}

bool esp32_link_is_online(void)
{
    return g_online;
}

void esp32_link_publish_aht20_status(bool online, int32_t temperature_tenths, uint32_t humidity_tenths, bool crc_ok)
{
    char text[ESP32_RX_LINE_MAX];

    if (!online) {
        esp32_link_publish_aht20_offline(NULL);
        return;
    }

    (void) snprintf(text, sizeof(text), "aht20:status=online;t=%ld.%ld;h=%lu.%lu;crc=%u",
            (long) (temperature_tenths / 10),
            (long) labs((long) (temperature_tenths % 10)),
            (unsigned long) (humidity_tenths / 10U),
            (unsigned long) (humidity_tenths % 10U),
            crc_ok ? 1U : 0U);
    esp32_link_publish_line(text);
}

void esp32_link_publish_aht20_offline(const char * diag_text)
{
    char text[ESP32_RX_LINE_MAX];

    if ((diag_text == NULL) || (diag_text[0] == '\0')) {
        esp32_link_publish_line("aht20:status=offline");
        return;
    }

    (void) snprintf(text, sizeof(text), "aht20:status=offline;diag=%s", diag_text);
    esp32_link_publish_line(text);
}

void esp32_link_publish_i2c_scan(const char * diag_text, const char * devices_text, uint8_t count)
{
    char text[ESP32_RX_LINE_MAX];

    (void) snprintf(text, sizeof(text), "i2c:bus=s1;diag=%s;count=%u;devices=%s",
            ((diag_text != NULL) && (diag_text[0] != '\0')) ? diag_text : "unknown",
            (unsigned int) count,
            ((devices_text != NULL) && (devices_text[0] != '\0')) ? devices_text : "-");
    esp32_link_publish_line(text);
}

void esp32_link_publish_rule_state(const char * state_text, const char * reason_text, bool has_temperature, int32_t temperature_tenths)
{
    char text[ESP32_RX_LINE_MAX];

    if ((state_text == NULL) || (g_current_request_id[0] == '\0') || (g_current_script_id[0] == '\0')) {
        return;
    }

    (void) snprintf(text, sizeof(text),
            "exec:req=%s;script=%s;state=%s;reason=%s;sample=%u;t=%ld;op=%s;value=%ld;action=SG90;angle=%u",
            g_current_request_id,
            g_current_script_id,
            state_text,
            (reason_text == NULL) ? "-" : reason_text,
            has_temperature ? 1U : 0U,
            (long) temperature_tenths,
            esp32_link_rule_operator_text(),
            (long) g_rule_threshold_tenths,
            (unsigned int) g_rule_servo_angle_degrees);
    esp32_link_publish_line(text);

    if ((strcmp(state_text, "IDLE") == 0) || (strcmp(state_text, "ARMED") == 0)) {
        platform_ports_set_pwm0_configured();
    } else {
        platform_ports_set_pwm0_execution_feedback(g_rule_servo_angle_degrees, "execution_feedback");
    }
    esp32_link_publish_platform_snapshot();
}
