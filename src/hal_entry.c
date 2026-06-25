#include "hal_data.h"

#include <stdio.h>
#include <stdlib.h>

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsign-conversion"
#include "lvgl.h"
#pragma GCC diagnostic pop

#include "aht20.h"
#include "app_ui.h"
#include "bh1750.h"
#include "device_registry.h"  /* v0.9.23: 设备注册表 hook */
#include "esp32_link.h"
#include "i2c_bus_s1.h"
#include "lcd_spi.h"
#include "lv_port_disp.h"
#include "lv_port_indev.h"
#include "platform_ports.h"
#include "sg90_servo.h"
#include "touch_debug_rtt.h"

#define AHT20_POLL_INTERVAL_MS       (2000U)
#define BH1750_POLL_INTERVAL_MS      (2500U)
#define I2C_SCAN_INTERVAL_MS         (5000U)

static void i2c_bus_s1_publish_scan(void)
{
    i2c_bus_s1_device_t devices[I2C_BUS_S1_SCAN_MAX_DEVICES];
    char summary[128];
    size_t found;
    size_t written = 0U;

    found = i2c_bus_s1_scan(devices, I2C_BUS_S1_SCAN_MAX_DEVICES);
    summary[0] = '\0';

    if (found == 0U) {
        (void) snprintf(summary, sizeof(summary), "none");
    } else {
        size_t limit = found < I2C_BUS_S1_SCAN_MAX_DEVICES ? found : I2C_BUS_S1_SCAN_MAX_DEVICES;

        for (size_t i = 0U; i < limit; i++) {
            written += (size_t) snprintf(summary + written,
                    sizeof(summary) - written,
                    "%s0x%02X/%s",
                    (i == 0U) ? "" : ",",
                    devices[i].address,
                    devices[i].label);
            if (written >= (sizeof(summary) - 1U)) {
                break;
            }
        }

        if (found > limit && written < (sizeof(summary) - 4U)) {
            (void) snprintf(summary + written, sizeof(summary) - written, ",...");
        }
    }

    platform_ports_set_i2c_s1_scan(i2c_bus_s1_last_diag(), devices, found);
    app_ui_set_i2c_s1_scan(i2c_bus_s1_diag_text(i2c_bus_s1_last_diag()), summary, (uint8_t) found);
    app_ui_refresh_platform_state();
    /* v0.9.23: 扫描结果驱动设备注册表 — 动态入口数据源 */
    device_registry_refresh_from_ports();
    esp32_link_publish_i2c_scan(i2c_bus_s1_diag_text(i2c_bus_s1_last_diag()), summary, (uint8_t) found);
    esp32_link_publish_platform_snapshot();
}

static void aht20_update_ui_from_sample(aht20_sample_t const * sample)
{
    char text[48];
    int32_t temperature_tenths;
    uint32_t humidity_tenths;

    if (sample == NULL) {
        return;
    }

    temperature_tenths = (int32_t) (sample->temperature_c >= 0.0f ? ((sample->temperature_c * 10.0f) + 0.5f)
            : ((sample->temperature_c * 10.0f) - 0.5f));
    humidity_tenths = (uint32_t) ((sample->humidity_rh * 10.0f) + 0.5f);

    (void) snprintf(text, sizeof(text), "%ld.%ldC %lu.%lu%%",
            (long) (temperature_tenths / 10),
            labs((long) (temperature_tenths % 10)),
            (unsigned long) (humidity_tenths / 10U),
            (unsigned long) (humidity_tenths % 10U));

    app_ui_set_aht20_status("online");
    app_ui_set_aht20_measurement(text);
    platform_ports_set_i2c_s1_aht20_sample(sample);
    app_ui_refresh_platform_state();
    /* v0.9.23: AHT20 真值出来后立即刷新注册表,UI 显示在线 */
    device_registry_refresh_from_ports();
    esp32_link_publish_aht20_status(true, temperature_tenths, humidity_tenths, sample->crc_ok);
    esp32_link_rule_update_sample(sample);
    esp32_link_publish_platform_snapshot();
}

void aht20_refresh_ui(void)   /* v0.9.20: 非 static, app_ui.c on_mock_switch_toggle 调用 */
{
    aht20_sample_t sample;

    /* v0.9.20: ui版 P0#7 + mock 短路 — mock 开关打开时不读真实传感器 */
    if (app_ui_is_aht20_mock()) {
        return;
    }

    if (aht20_read(&sample)) {
        aht20_update_ui_from_sample(&sample);
        return;
    }

    if (aht20_init()) {
        app_ui_set_aht20_status("online");
        app_ui_set_aht20_measurement("retrying");
        return;
    }

    app_ui_set_aht20_status("offline");
    app_ui_set_aht20_measurement(aht20_diag_text(aht20_last_diag()));
    platform_ports_set_i2c_s1_aht20_offline(aht20_diag_text(aht20_last_diag()));
    app_ui_refresh_platform_state();
    esp32_link_publish_aht20_offline(aht20_diag_text(aht20_last_diag()));
    esp32_link_publish_platform_snapshot();
}

static void bh1750_refresh_runtime(void)
{
    bh1750_sample_t sample;

    if (bh1750_read(&sample)) {
        platform_ports_set_i2c_s1_bh1750_sample(&sample);
        app_ui_refresh_platform_state();
        /* v0.9.23: BH1750 真值出来后立即刷新注册表 */
        device_registry_refresh_from_ports();
        esp32_link_publish_platform_snapshot();
        return;
    }

    if (bh1750_init()) {
        return;
    }

    platform_ports_set_i2c_s1_bh1750_offline(bh1750_diag_text(bh1750_last_diag()));
    app_ui_refresh_platform_state();
    esp32_link_publish_platform_snapshot();
}

void hal_entry(void)
{
    uint32_t aht20_poll_elapsed_ms = 0U;
    uint32_t bh1750_poll_elapsed_ms = 0U;
    uint32_t i2c_scan_elapsed_ms = 0U;
    char submitted_text[96];

#if BSP_TZ_SECURE_BUILD
    R_BSP_NonSecureEnter();
#endif

#if (0 == _RA_CORE) && (1 == BSP_MULTICORE_PROJECT) && !BSP_TZ_NONSECURE_BUILD
    R_BSP_SecondaryCoreStart();
#endif

    lcd_init();
    lv_init();
    lv_port_disp_init();
    lv_port_indev_init();
    platform_ports_init();
    app_ui_create();
    touch_debug_rtt_init();
    sg90_servo_init();
    platform_ports_set_pwm0_configured();
    esp32_link_rule_init();
    esp32_link_init();
    esp32_link_publish_ra8p1_uid();
    i2c_bus_s1_publish_scan();

    if (aht20_init()) {
        app_ui_set_aht20_status("online");
        app_ui_set_aht20_measurement("warming");
        aht20_refresh_ui();
    } else {
        app_ui_set_aht20_status("offline");
        app_ui_set_aht20_measurement(aht20_diag_text(aht20_last_diag()));
        platform_ports_set_i2c_s1_aht20_offline(aht20_diag_text(aht20_last_diag()));
        app_ui_refresh_platform_state();
        esp32_link_publish_aht20_offline(aht20_diag_text(aht20_last_diag()));
        esp32_link_publish_platform_snapshot();
    }

    lv_tick_inc(1);
    lv_refr_now(NULL);

    while (1) {
        platform_ports_tick_5ms();
        lv_tick_inc(5);
        esp32_link_poll_5ms();
        (void) lv_timer_handler();

        aht20_poll_elapsed_ms += 5U;
        bh1750_poll_elapsed_ms += 5U;
        i2c_scan_elapsed_ms += 5U;
        /* v0.9.23: device_registry tick — 内部 5000ms 自动 refresh */
        device_registry_tick_5ms(platform_ports_now_ms());
        if (aht20_poll_elapsed_ms >= AHT20_POLL_INTERVAL_MS) {
            aht20_poll_elapsed_ms = 0U;
            aht20_refresh_ui();
        }
        if (bh1750_poll_elapsed_ms >= BH1750_POLL_INTERVAL_MS) {
            bh1750_poll_elapsed_ms = 0U;
            bh1750_refresh_runtime();
        }
        if (i2c_scan_elapsed_ms >= I2C_SCAN_INTERVAL_MS) {
            i2c_scan_elapsed_ms = 0U;
            i2c_bus_s1_publish_scan();
        }

        if (app_ui_take_input_submission(submitted_text, sizeof(submitted_text))) {
            app_ui_mark_input_forwarded(submitted_text);
            esp32_link_submit_nl_text(submitted_text);
        }

        esp32_link_rule_tick_5ms();
        R_BSP_SoftwareDelay(5, BSP_DELAY_UNITS_MILLISECONDS);
    }
}
