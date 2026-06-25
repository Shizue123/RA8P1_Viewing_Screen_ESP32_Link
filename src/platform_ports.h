#ifndef PLATFORM_PORTS_H
#define PLATFORM_PORTS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "aht20.h"
#include "bh1750.h"
#include "i2c_bus_s1.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PLATFORM_PORT_CAP_MAX    (4U)
#define PLATFORM_PORT_COUNT      (4U)
#define PLATFORM_SAMPLE_COUNT    (4U)
#define PLATFORM_TEXT_SMALL_MAX  (16U)
#define PLATFORM_TEXT_MEDIUM_MAX (24U)
#define PLATFORM_TEXT_LARGE_MAX  (40U)
#define PLATFORM_TEXT_XLARGE_MAX (48U)

typedef struct st_platform_capability
{
    char id[PLATFORM_TEXT_LARGE_MAX];
    char unit[PLATFORM_TEXT_SMALL_MAX];
    char access[PLATFORM_TEXT_SMALL_MAX];
    char status[PLATFORM_TEXT_SMALL_MAX];
} platform_capability_t;

typedef struct st_platform_module
{
    char module_id[PLATFORM_TEXT_MEDIUM_MAX];
    char module_type[PLATFORM_TEXT_MEDIUM_MAX];
    char module_class[PLATFORM_TEXT_MEDIUM_MAX];
    char driver[PLATFORM_TEXT_MEDIUM_MAX];
    char model_state[PLATFORM_TEXT_SMALL_MAX];
    char binding_source[PLATFORM_TEXT_MEDIUM_MAX];
    char confidence[PLATFORM_TEXT_SMALL_MAX];
    char address[PLATFORM_TEXT_SMALL_MAX];
    char device_key[PLATFORM_TEXT_XLARGE_MAX];
} platform_module_t;

typedef struct st_platform_port
{
    char port_id[PLATFORM_TEXT_SMALL_MAX];
    char physical_port[PLATFORM_TEXT_SMALL_MAX];
    char channel[PLATFORM_TEXT_MEDIUM_MAX];
    char type[PLATFORM_TEXT_SMALL_MAX];
    char activation[PLATFORM_TEXT_SMALL_MAX];
    char status[PLATFORM_TEXT_SMALL_MAX];
    char diag[PLATFORM_TEXT_MEDIUM_MAX];
    platform_module_t module;
    platform_capability_t capabilities[PLATFORM_PORT_CAP_MAX];
    uint8_t capability_count;
    uint32_t last_sample_ms;
} platform_port_t;

typedef struct st_platform_sample
{
    bool valid;
    char port_id[PLATFORM_TEXT_SMALL_MAX];
    char module_type[PLATFORM_TEXT_MEDIUM_MAX];
    char capability[PLATFORM_TEXT_LARGE_MAX];
    char unit[PLATFORM_TEXT_SMALL_MAX];
    float value;
    uint32_t ts_ms;
} platform_sample_t;

void platform_ports_init(void);
void platform_ports_tick_5ms(void);
uint32_t platform_ports_now_ms(void);

void platform_ports_set_uart_bridge(bool online, const char * diag_text);
void platform_ports_set_i2c_s1_scan(i2c_bus_s1_diag_t diag, i2c_bus_s1_device_t const * devices, size_t count);
void platform_ports_set_i2c_s1_aht20_sample(aht20_sample_t const * sample);
void platform_ports_set_i2c_s1_aht20_offline(const char * diag_text);
void platform_ports_set_i2c_s1_bh1750_sample(bh1750_sample_t const * sample);
void platform_ports_set_i2c_s1_bh1750_offline(const char * diag_text);
void platform_ports_set_pwm0_configured(void);
void platform_ports_set_pwm0_execution_feedback(uint16_t angle_degrees, const char * capability_status);

size_t platform_ports_get_port_count(void);
platform_port_t const * platform_ports_get_port(size_t index);
size_t platform_ports_get_sample_count(void);
platform_sample_t const * platform_ports_get_sample(size_t index);

#ifdef __cplusplus
}
#endif

#endif /* PLATFORM_PORTS_H */
