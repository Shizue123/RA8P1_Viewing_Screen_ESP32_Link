#include "sg90_servo.h"

#include "hal_data.h"

#define SG90_SERVO_PIN               BSP_IO_PORT_01_PIN_05
#define SG90_SERVO_PERIOD_MS         (20U)
#define SG90_SERVO_NEUTRAL_ANGLE     (90U)
#define SG90_SERVO_MIN_ANGLE         (0U)
#define SG90_SERVO_MAX_ANGLE         (180U)
#define SG90_SERVO_MIN_PULSE_US      (500U)
#define SG90_SERVO_PULSE_RANGE_US    (2000U)

static bool g_sg90_initialized;
static bool g_sg90_enabled;
static bool g_sg90_active;
static uint32_t g_sg90_period_elapsed_ms;
static uint16_t g_sg90_target_angle = SG90_SERVO_MAX_ANGLE;

static uint16_t sg90_servo_clamp_angle(uint16_t angle_degrees)
{
    if (angle_degrees > SG90_SERVO_MAX_ANGLE) {
        return SG90_SERVO_MAX_ANGLE;
    }

    return angle_degrees;
}

static uint16_t sg90_servo_pulse_width_us(uint16_t angle_degrees)
{
    uint32_t scaled;

    scaled = SG90_SERVO_MIN_PULSE_US
            + ((uint32_t) sg90_servo_clamp_angle(angle_degrees) * SG90_SERVO_PULSE_RANGE_US) / SG90_SERVO_MAX_ANGLE;
    return (uint16_t) scaled;
}

static void sg90_servo_pin_write(bsp_io_level_t level)
{
    (void) R_IOPORT_PinWrite(&g_ioport_ctrl, SG90_SERVO_PIN, level);
}

static void sg90_servo_emit_pulse(uint16_t angle_degrees)
{
    uint16_t pulse_width_us = sg90_servo_pulse_width_us(angle_degrees);

    sg90_servo_pin_write(BSP_IO_LEVEL_HIGH);
    R_BSP_SoftwareDelay(pulse_width_us, BSP_DELAY_UNITS_MICROSECONDS);
    sg90_servo_pin_write(BSP_IO_LEVEL_LOW);
}

void sg90_servo_init(void)
{
    (void) R_IOPORT_PinCfg(&g_ioport_ctrl,
            SG90_SERVO_PIN,
            (uint32_t) IOPORT_CFG_PORT_DIRECTION_OUTPUT | (uint32_t) IOPORT_CFG_PORT_OUTPUT_LOW);

    g_sg90_initialized = true;
    g_sg90_enabled = false;
    g_sg90_active = false;
    g_sg90_period_elapsed_ms = 0U;
    g_sg90_target_angle = SG90_SERVO_MAX_ANGLE;
    sg90_servo_pin_write(BSP_IO_LEVEL_LOW);
}

void sg90_servo_configure_angle(uint16_t angle_degrees)
{
    g_sg90_target_angle = sg90_servo_clamp_angle(angle_degrees);
}

void sg90_servo_set_enabled(bool enabled)
{
    g_sg90_enabled = enabled;
    if (!enabled) {
        g_sg90_active = false;
        g_sg90_period_elapsed_ms = 0U;
        if (g_sg90_initialized) {
            sg90_servo_pin_write(BSP_IO_LEVEL_LOW);
        }
    }
}

void sg90_servo_set_active(bool active)
{
    if (!g_sg90_enabled) {
        g_sg90_active = false;
        return;
    }

    g_sg90_active = active;
}

uint16_t sg90_servo_get_target_angle(void)
{
    return g_sg90_target_angle;
}

bool sg90_servo_is_active(void)
{
    return g_sg90_enabled && g_sg90_active;
}

/* v0.9.20: ui版 app_ui.c 用的别名 (兼容 ui版 API 命名) */
uint16_t sg90_servo_get_angle(void)
{
    return g_sg90_target_angle;
}

bool sg90_servo_is_enabled(void)
{
    return g_sg90_enabled;
}

void sg90_servo_tick_5ms(void)
{
    uint16_t angle_degrees;

    if ((!g_sg90_initialized) || (!g_sg90_enabled)) {
        return;
    }

    g_sg90_period_elapsed_ms += 5U;
    if (g_sg90_period_elapsed_ms < SG90_SERVO_PERIOD_MS) {
        return;
    }

    g_sg90_period_elapsed_ms = 0U;
    angle_degrees = g_sg90_active ? g_sg90_target_angle : SG90_SERVO_NEUTRAL_ANGLE;
    sg90_servo_emit_pulse(angle_degrees);
}
