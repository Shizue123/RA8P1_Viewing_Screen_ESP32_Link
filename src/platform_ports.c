#include "platform_ports.h"

#include <stdio.h>
#include <string.h>

#include "sg90_servo.h"

enum
{
    PLATFORM_PORT_INDEX_I2C_S1 = 0,
    PLATFORM_PORT_INDEX_I2C_S2,
    PLATFORM_PORT_INDEX_PWM_0,
    PLATFORM_PORT_INDEX_UART_BRIDGE
};

enum
{
    PLATFORM_SAMPLE_INDEX_TEMP = 0,
    PLATFORM_SAMPLE_INDEX_HUMIDITY,
    PLATFORM_SAMPLE_INDEX_LIGHT_LUX,
    PLATFORM_SAMPLE_INDEX_SERVO_ANGLE
};

static platform_port_t g_ports[PLATFORM_PORT_COUNT];
static platform_sample_t g_samples[PLATFORM_SAMPLE_COUNT];
static uint32_t g_now_ms;

typedef struct st_platform_i2c_s1_state
{
    bool mux_present;
    bool aht20_detected;
    bool aht20_online;
    bool bh1750_detected;
    bool bh1750_online;
    uint8_t bh1750_address;
    bool unknown_detected;
    i2c_bus_s1_device_t unknown_device;
    char diag[PLATFORM_TEXT_MEDIUM_MAX];
} platform_i2c_s1_state_t;

static platform_i2c_s1_state_t g_i2c_s1_state;

static void platform_ports_set_i2c_s1_empty(const char * diag_text);
static void platform_ports_set_i2c_s1_unknown_device(const i2c_bus_s1_device_t * device, const char * diag_text);
static void platform_ports_set_i2c_s1_aht20_identity(const char * status_text, const char * diag_text);

static void platform_ports_copy_text(char * dest, size_t dest_size, const char * src)
{
    if ((dest == NULL) || (dest_size == 0U)) {
        return;
    }

    (void) snprintf(dest, dest_size, "%s", (src == NULL) ? "" : src);
}

static void platform_ports_clear_capabilities(platform_port_t * port)
{
    if (port == NULL) {
        return;
    }

    (void) memset(port->capabilities, 0, sizeof(port->capabilities));
    port->capability_count = 0U;
}

static void platform_ports_add_capability(platform_port_t * port,
        const char * id,
        const char * unit,
        const char * access,
        const char * status)
{
    platform_capability_t * capability;

    if ((port == NULL) || (port->capability_count >= PLATFORM_PORT_CAP_MAX)) {
        return;
    }

    capability = &port->capabilities[port->capability_count++];
    platform_ports_copy_text(capability->id, sizeof(capability->id), id);
    platform_ports_copy_text(capability->unit, sizeof(capability->unit), unit);
    platform_ports_copy_text(capability->access, sizeof(capability->access), access);
    platform_ports_copy_text(capability->status, sizeof(capability->status), status);
}

static void platform_ports_clear_module(platform_module_t * module)
{
    if (module == NULL) {
        return;
    }

    (void) memset(module, 0, sizeof(*module));
}

static const char * platform_ports_guess_i2c_module_class(const char * label)
{
    if (label == NULL) {
        return "unknown";
    }

    if ((strcmp(label, "AHT20") == 0) || (strcmp(label, "0x38-class") == 0)) {
        return "env.th";
    }
    if (strcmp(label, "BH1750") == 0) {
        return "env.light";
    }
    if (strcmp(label, "ENV-class") == 0) {
        return "env.multi";
    }
    if (strcmp(label, "9548A-MUX") == 0) {
        return "i2c.mux";
    }
    if (strcmp(label, "OLED-class") == 0) {
        return "display.i2c";
    }
    if (strcmp(label, "EEPROM-class") == 0) {
        return "storage.eeprom";
    }
    if (strcmp(label, "IMU-RTC-class") == 0) {
        return "motion_time";
    }

    return "unknown";
}

static void platform_ports_build_device_key(char * dest,
        size_t dest_size,
        const char * port_id,
        const char * address_text,
        const char * module_type)
{
    if ((dest == NULL) || (dest_size == 0U)) {
        return;
    }

    (void) snprintf(dest,
            dest_size,
            "%s:%s:%s",
            (port_id == NULL) ? "-" : port_id,
            ((address_text != NULL) && (address_text[0] != '\0')) ? address_text : "-",
            ((module_type != NULL) && (module_type[0] != '\0')) ? module_type : "-");
}

static void platform_ports_set_module_identity(platform_port_t * port,
        const char * module_id,
        const char * module_type,
        const char * module_class,
        const char * driver,
        const char * model_state,
        const char * binding_source,
        const char * confidence,
        const char * address_text)
{
    if (port == NULL) {
        return;
    }

    platform_ports_clear_module(&port->module);
    platform_ports_copy_text(port->module.module_id, sizeof(port->module.module_id), module_id);
    platform_ports_copy_text(port->module.module_type, sizeof(port->module.module_type), module_type);
    platform_ports_copy_text(port->module.module_class, sizeof(port->module.module_class), module_class);
    platform_ports_copy_text(port->module.driver, sizeof(port->module.driver), driver);
    platform_ports_copy_text(port->module.model_state, sizeof(port->module.model_state), model_state);
    platform_ports_copy_text(port->module.binding_source, sizeof(port->module.binding_source), binding_source);
    platform_ports_copy_text(port->module.confidence, sizeof(port->module.confidence), confidence);
    platform_ports_copy_text(port->module.address, sizeof(port->module.address), address_text);
    platform_ports_build_device_key(port->module.device_key,
            sizeof(port->module.device_key),
            port->port_id,
            port->module.address,
            port->module.module_type);
}

static const char * platform_ports_i2c_cap_status(bool detected, bool online)
{
    if (online) {
        return "online";
    }
    if (detected) {
        return "detected";
    }

    return "offline";
}

static void platform_ports_refresh_i2c_s1_port(void)
{
    platform_port_t * port = &g_ports[PLATFORM_PORT_INDEX_I2C_S1];

    platform_ports_clear_capabilities(port);

    if (g_i2c_s1_state.mux_present) {
        platform_ports_copy_text(port->activation, sizeof(port->activation), "confirmed");
        platform_ports_copy_text(port->status, sizeof(port->status), "online");
        platform_ports_copy_text(port->diag, sizeof(port->diag), g_i2c_s1_state.diag);
        platform_ports_set_module_identity(port,
                "i2c_mux",
                "9548A-MUX",
                "i2c.mux",
                "pca9548a",
                "candidate",
                "auto_detected",
                "class",
                "0x70");

        if (g_i2c_s1_state.aht20_detected || g_i2c_s1_state.aht20_online) {
            platform_ports_add_capability(port,
                    "env.temperature",
                    "C",
                    "read",
                    platform_ports_i2c_cap_status(g_i2c_s1_state.aht20_detected, g_i2c_s1_state.aht20_online));
            platform_ports_add_capability(port,
                    "env.humidity",
                    "%RH",
                    "read",
                    platform_ports_i2c_cap_status(g_i2c_s1_state.aht20_detected, g_i2c_s1_state.aht20_online));
        }
        if (g_i2c_s1_state.bh1750_detected || g_i2c_s1_state.bh1750_online) {
            platform_ports_add_capability(port,
                    "env.light.lux",
                    "lux",
                    "read",
                    platform_ports_i2c_cap_status(g_i2c_s1_state.bh1750_detected, g_i2c_s1_state.bh1750_online));
        }
        port->last_sample_ms = g_now_ms;
        return;
    }

    if (g_i2c_s1_state.aht20_detected || g_i2c_s1_state.aht20_online) {
        platform_ports_set_i2c_s1_aht20_identity(g_i2c_s1_state.aht20_online ? "online" : "offline",
                g_i2c_s1_state.diag);
        return;
    }

    if (g_i2c_s1_state.bh1750_detected || g_i2c_s1_state.bh1750_online) {
        platform_ports_copy_text(port->activation, sizeof(port->activation), "channel_active");
        platform_ports_copy_text(port->status,
                sizeof(port->status),
                g_i2c_s1_state.bh1750_online ? "online" : "offline");
        platform_ports_copy_text(port->diag, sizeof(port->diag), g_i2c_s1_state.diag);
        platform_ports_set_module_identity(port,
                "bh1750",
                "BH1750",
                "env.light",
                "bh1750",
                g_i2c_s1_state.bh1750_online ? "candidate" : "unknown",
                "auto_detected",
                "class",
                (g_i2c_s1_state.bh1750_address == 0x5CU) ? "0x5C" : "0x23");
        platform_ports_add_capability(port,
                "env.light.lux",
                "lux",
                "read",
                platform_ports_i2c_cap_status(g_i2c_s1_state.bh1750_detected, g_i2c_s1_state.bh1750_online));
        port->last_sample_ms = g_now_ms;
        return;
    }

    if (g_i2c_s1_state.unknown_detected) {
        platform_ports_set_i2c_s1_unknown_device(&g_i2c_s1_state.unknown_device, g_i2c_s1_state.diag);
        return;
    }

    platform_ports_set_i2c_s1_empty(g_i2c_s1_state.diag);
}

static void platform_ports_set_i2c_s1_empty(const char * diag_text)
{
    platform_port_t * port = &g_ports[PLATFORM_PORT_INDEX_I2C_S1];

    platform_ports_copy_text(port->activation, sizeof(port->activation), "inactive");
    /* v0.9.17 真实数据: 扫描发现 0 模块 → status="not_inserted" 红色 */
    platform_ports_copy_text(port->status, sizeof(port->status), "not_inserted");
    platform_ports_copy_text(port->diag, sizeof(port->diag), diag_text);
    platform_ports_set_module_identity(port,
            "none",
            "none",
            "none",
            "",
            "none",
            "none",
            "none",
            "");
    platform_ports_clear_capabilities(port);
    port->last_sample_ms = g_now_ms;
}

static void platform_ports_set_i2c_s1_unknown_device(const i2c_bus_s1_device_t * device, const char * diag_text)
{
    platform_port_t * port = &g_ports[PLATFORM_PORT_INDEX_I2C_S1];
    char address_text[PLATFORM_TEXT_SMALL_MAX];

    platform_ports_copy_text(port->status, sizeof(port->status), "online");
    platform_ports_copy_text(port->activation, sizeof(port->activation), "channel_active");
    platform_ports_copy_text(port->diag, sizeof(port->diag), diag_text);
    (void) snprintf(address_text, sizeof(address_text), "0x%02X", device->address);
    platform_ports_set_module_identity(port,
            "i2c-s1-device",
            device->label,
            platform_ports_guess_i2c_module_class(device->label),
            device->label,
            device->signature_matched ? "candidate" : "unknown",
            "auto_detected",
            device->signature_matched ? "class" : "unknown",
            address_text);
    platform_ports_clear_capabilities(port);
    port->last_sample_ms = g_now_ms;
}

static void platform_ports_set_i2c_s1_aht20_identity(const char * status_text, const char * diag_text)
{
    platform_port_t * port = &g_ports[PLATFORM_PORT_INDEX_I2C_S1];

    platform_ports_copy_text(port->activation, sizeof(port->activation), "confirmed");
    platform_ports_copy_text(port->status, sizeof(port->status), status_text);
    platform_ports_copy_text(port->diag, sizeof(port->diag), diag_text);
    platform_ports_set_module_identity(port,
            "aht20",
            "AHT20",
            "env.th",
            "aht20",
            "exact",
            "auto_exact",
            "exact",
            "0x38");
    platform_ports_clear_capabilities(port);
    platform_ports_add_capability(port, "env.temperature", "C", "read", status_text);
    platform_ports_add_capability(port, "env.humidity", "%RH", "read", status_text);
    port->last_sample_ms = g_now_ms;
}

static void platform_ports_set_sample(platform_sample_t * sample,
        const char * port_id,
        const char * module_type,
        const char * capability,
        const char * unit,
        float value)
{
    if (sample == NULL) {
        return;
    }

    sample->valid = true;
    platform_ports_copy_text(sample->port_id, sizeof(sample->port_id), port_id);
    platform_ports_copy_text(sample->module_type, sizeof(sample->module_type), module_type);
    platform_ports_copy_text(sample->capability, sizeof(sample->capability), capability);
    platform_ports_copy_text(sample->unit, sizeof(sample->unit), unit);
    sample->value = value;
    sample->ts_ms = g_now_ms;
}

void platform_ports_init(void)
{
    platform_port_t * port;

    g_now_ms = 0U;
    (void) memset(g_ports, 0, sizeof(g_ports));
    (void) memset(g_samples, 0, sizeof(g_samples));
    (void) memset(&g_i2c_s1_state, 0, sizeof(g_i2c_s1_state));
    platform_ports_copy_text(g_i2c_s1_state.diag, sizeof(g_i2c_s1_state.diag), "unknown");

    port = &g_ports[PLATFORM_PORT_INDEX_I2C_S1];
    platform_ports_copy_text(port->port_id, sizeof(port->port_id), "i2c.s1");
    platform_ports_copy_text(port->physical_port, sizeof(port->physical_port), "I2C-1");
    platform_ports_copy_text(port->channel, sizeof(port->channel), "Bus S1");
    platform_ports_copy_text(port->type, sizeof(port->type), "i2c");
    platform_ports_set_i2c_s1_empty("unknown");

    port = &g_ports[PLATFORM_PORT_INDEX_I2C_S2];
    platform_ports_copy_text(port->port_id, sizeof(port->port_id), "i2c.s2");
    platform_ports_copy_text(port->physical_port, sizeof(port->physical_port), "I2C-2");
    platform_ports_copy_text(port->channel, sizeof(port->channel), "Bus S2");
    platform_ports_copy_text(port->type, sizeof(port->type), "i2c");
    platform_ports_copy_text(port->activation, sizeof(port->activation), "reserved");
    /* v0.9.18: status="not_inserted" 红色规则触发 (扫描发现 0 模块) */
    platform_ports_copy_text(port->status, sizeof(port->status), "not_inserted");
    platform_ports_copy_text(port->diag, sizeof(port->diag), "not_supported");
    platform_ports_set_module_identity(port,
            "\xE4\xBF\x9D\xE7\x95\x99",                  /* 保留 */
            "\xE4\xBF\x9D\xE7\x95\x99",                  /* 保留 */
            "\xE4\xBF\x9D\xE7\x95\x99",                  /* 保留 */
            "",
            "reserved",
            "reserved",
            "reserved",
            "");

    port = &g_ports[PLATFORM_PORT_INDEX_PWM_0];
    platform_ports_copy_text(port->port_id, sizeof(port->port_id), "pwm.0");
    platform_ports_copy_text(port->physical_port, sizeof(port->physical_port), "PWM-0");
    platform_ports_copy_text(port->channel, sizeof(port->channel), "P105");
    platform_ports_copy_text(port->type, sizeof(port->type), "pwm");
    platform_ports_set_module_identity(port,
            "sg90",
            "SG90",
            "act.servo",
            "sg90_servo",
            "exact",
            "user_confirmed",
            "user_confirmed",
            "");
    platform_ports_set_pwm0_configured();

    port = &g_ports[PLATFORM_PORT_INDEX_UART_BRIDGE];
    platform_ports_copy_text(port->port_id, sizeof(port->port_id), "uart.bridge");
    platform_ports_copy_text(port->physical_port, sizeof(port->physical_port), "UART-BRIDGE");
    platform_ports_copy_text(port->channel, sizeof(port->channel), "UART0");
    platform_ports_copy_text(port->type, sizeof(port->type), "uart");
    platform_ports_set_module_identity(port,
            "esp32_bridge",
            "ESP32-S3",
            "bridge.uart",
            "esp32_uart_link",
            "exact",
            "system_fixed",
            "exact",
            "");
    platform_ports_set_uart_bridge(false, "waiting");
}

void platform_ports_tick_5ms(void)
{
    g_now_ms += 5U;
}

uint32_t platform_ports_now_ms(void)
{
    return g_now_ms;
}

void platform_ports_set_uart_bridge(bool online, const char * diag_text)
{
    platform_port_t * port = &g_ports[PLATFORM_PORT_INDEX_UART_BRIDGE];

    platform_ports_copy_text(port->activation, sizeof(port->activation), "confirmed");
    platform_ports_copy_text(port->status, sizeof(port->status), online ? "online" : "offline");
    platform_ports_copy_text(port->diag, sizeof(port->diag), diag_text);
    platform_ports_clear_capabilities(port);
    platform_ports_add_capability(port, "bridge.uart.mqtt", "-", "readwrite", online ? "online" : "degraded");
    port->last_sample_ms = g_now_ms;
}

void platform_ports_set_i2c_s1_scan(i2c_bus_s1_diag_t diag, i2c_bus_s1_device_t const * devices, size_t count)
{
    const char * diag_text = i2c_bus_s1_diag_text(diag);
    bool unknown_set = false;

    g_i2c_s1_state.mux_present = false;
    g_i2c_s1_state.aht20_detected = false;
    g_i2c_s1_state.bh1750_detected = false;
    g_i2c_s1_state.unknown_detected = false;
    platform_ports_copy_text(g_i2c_s1_state.diag, sizeof(g_i2c_s1_state.diag), diag_text);

    if (count == 0U) {
        g_i2c_s1_state.aht20_online = false;
        g_i2c_s1_state.bh1750_online = false;
        if (diag != I2C_BUS_S1_DIAG_OK) {
            platform_ports_set_i2c_s1_empty(diag_text);
            platform_ports_copy_text(g_ports[PLATFORM_PORT_INDEX_I2C_S1].status,
                    sizeof(g_ports[PLATFORM_PORT_INDEX_I2C_S1].status),
                    "error");
            return;
        }

        platform_ports_refresh_i2c_s1_port();
        return;
    }

    if (devices != NULL) {
        for (size_t i = 0U; i < count; i++) {
            if (strcmp(devices[i].label, "9548A-MUX") == 0) {
                g_i2c_s1_state.mux_present = true;
                continue;
            }
            if ((strcmp(devices[i].label, "AHT20") == 0) || (strcmp(devices[i].label, "0x38-class") == 0)) {
                g_i2c_s1_state.aht20_detected = true;
                continue;
            }
            if (strcmp(devices[i].label, "BH1750") == 0) {
                g_i2c_s1_state.bh1750_detected = true;
                continue;
            }
            if (!unknown_set) {
                g_i2c_s1_state.unknown_detected = true;
                g_i2c_s1_state.unknown_device = devices[i];
                unknown_set = true;
            }
        }
    }

    if (!g_i2c_s1_state.aht20_detected) {
        g_i2c_s1_state.aht20_online = false;
        g_samples[PLATFORM_SAMPLE_INDEX_TEMP].valid = false;
        g_samples[PLATFORM_SAMPLE_INDEX_HUMIDITY].valid = false;
    }
    if (!g_i2c_s1_state.bh1750_detected) {
        g_i2c_s1_state.bh1750_online = false;
        g_samples[PLATFORM_SAMPLE_INDEX_LIGHT_LUX].valid = false;
    }

    platform_ports_refresh_i2c_s1_port();
}

void platform_ports_set_i2c_s1_aht20_sample(aht20_sample_t const * sample)
{
    if (sample == NULL) {
        return;
    }

    g_i2c_s1_state.aht20_detected = true;
    g_i2c_s1_state.aht20_online = true;
    platform_ports_copy_text(g_i2c_s1_state.diag,
            sizeof(g_i2c_s1_state.diag),
            sample->crc_ok ? "ok" : "crc_fail");
    platform_ports_refresh_i2c_s1_port();
    platform_ports_set_sample(&g_samples[PLATFORM_SAMPLE_INDEX_TEMP],
            "i2c.s1",
            "AHT20",
            "env.temperature",
            "C",
            sample->temperature_c);
    platform_ports_set_sample(&g_samples[PLATFORM_SAMPLE_INDEX_HUMIDITY],
            "i2c.s1",
            "AHT20",
            "env.humidity",
            "%RH",
            sample->humidity_rh);
}

void platform_ports_set_i2c_s1_aht20_offline(const char * diag_text)
{
    g_i2c_s1_state.aht20_online = false;
    platform_ports_copy_text(g_i2c_s1_state.diag, sizeof(g_i2c_s1_state.diag), diag_text);
    platform_ports_refresh_i2c_s1_port();
    g_samples[PLATFORM_SAMPLE_INDEX_TEMP].valid = false;
    g_samples[PLATFORM_SAMPLE_INDEX_HUMIDITY].valid = false;
}

void platform_ports_set_i2c_s1_bh1750_sample(bh1750_sample_t const * sample)
{
    if (sample == NULL) {
        return;
    }

    g_i2c_s1_state.bh1750_detected = true;
    g_i2c_s1_state.bh1750_online = true;
    g_i2c_s1_state.bh1750_address = sample->address;
    platform_ports_copy_text(g_i2c_s1_state.diag, sizeof(g_i2c_s1_state.diag), "ok");
    platform_ports_refresh_i2c_s1_port();
    platform_ports_set_sample(&g_samples[PLATFORM_SAMPLE_INDEX_LIGHT_LUX],
            "i2c.s1",
            "BH1750",
            "env.light.lux",
            "lux",
            sample->lux);
}

void platform_ports_set_i2c_s1_bh1750_offline(const char * diag_text)
{
    g_i2c_s1_state.bh1750_online = false;
    platform_ports_copy_text(g_i2c_s1_state.diag, sizeof(g_i2c_s1_state.diag), diag_text);
    platform_ports_refresh_i2c_s1_port();
    g_samples[PLATFORM_SAMPLE_INDEX_LIGHT_LUX].valid = false;
}

void platform_ports_set_pwm0_configured(void)
{
    platform_port_t * port = &g_ports[PLATFORM_PORT_INDEX_PWM_0];

    platform_ports_copy_text(port->activation, sizeof(port->activation), "confirmed");
    platform_ports_copy_text(port->status, sizeof(port->status), "configured");
    platform_ports_copy_text(port->diag, sizeof(port->diag), "no_feedback_open_loop");
    platform_ports_clear_capabilities(port);
    platform_ports_add_capability(port, "motor.servo.angle", "degree", "write", "configured");
    platform_ports_add_capability(port, "buzzer.active", "-", "write", "configured");
    port->last_sample_ms = g_now_ms;
}

void platform_ports_set_pwm0_execution_feedback(uint16_t angle_degrees, const char * capability_status)
{
    platform_port_t * port = &g_ports[PLATFORM_PORT_INDEX_PWM_0];

    platform_ports_copy_text(port->activation, sizeof(port->activation), "confirmed");
    platform_ports_copy_text(port->status, sizeof(port->status), "online");
    platform_ports_copy_text(port->diag, sizeof(port->diag), "execution_feedback");
    platform_ports_clear_capabilities(port);
    platform_ports_add_capability(port,
            "motor.servo.angle",
            "degree",
            "write",
            (capability_status == NULL) ? "execution_feedback" : capability_status);
    platform_ports_add_capability(port,
            "buzzer.active",
            "-",
            "write",
            (capability_status == NULL) ? "execution_feedback" : capability_status);
    port->last_sample_ms = g_now_ms;
    platform_ports_set_sample(&g_samples[PLATFORM_SAMPLE_INDEX_SERVO_ANGLE],
            "pwm.0",
            "SG90",
            "motor.servo.angle",
            "degree",
            (float) angle_degrees);
}

size_t platform_ports_get_port_count(void)
{
    return PLATFORM_PORT_COUNT;
}

platform_port_t const * platform_ports_get_port(size_t index)
{
    if (index >= PLATFORM_PORT_COUNT) {
        return NULL;
    }

    return &g_ports[index];
}

size_t platform_ports_get_sample_count(void)
{
    return PLATFORM_SAMPLE_COUNT;
}

platform_sample_t const * platform_ports_get_sample(size_t index)
{
    if (index >= PLATFORM_SAMPLE_COUNT) {
        return NULL;
    }

    return &g_samples[index];
}
