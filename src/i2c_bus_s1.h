#ifndef I2C_BUS_S1_H
#define I2C_BUS_S1_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define I2C_BUS_S1_SCAN_MAX_DEVICES (16U)
#define I2C_BUS_S1_LABEL_MAX        (24U)
#define I2C_BUS_S1_CHANNEL_DIRECT   (0xFFU)

typedef enum e_i2c_bus_s1_diag
{
    I2C_BUS_S1_DIAG_OK = 0,
    I2C_BUS_S1_DIAG_SDA_STUCK,
    I2C_BUS_S1_DIAG_SCL_STUCK,
    I2C_BUS_S1_DIAG_ADDR_NACK,
    I2C_BUS_S1_DIAG_DATA_NACK,
} i2c_bus_s1_diag_t;

typedef struct st_i2c_bus_s1_device
{
    uint8_t address;
    uint8_t channel;
    bool via_mux;
    char label[I2C_BUS_S1_LABEL_MAX];
    bool signature_matched;
} i2c_bus_s1_device_t;

void i2c_bus_s1_init(void);
bool i2c_bus_s1_mux_present(void);
bool i2c_bus_s1_write_channel(uint8_t channel, uint8_t address_7bit, uint8_t const * data, uint8_t length);
bool i2c_bus_s1_read_channel(uint8_t channel, uint8_t address_7bit, uint8_t * data, uint8_t length);
bool i2c_bus_s1_probe_channel(uint8_t channel, uint8_t address_7bit);
bool i2c_bus_s1_write(uint8_t address_7bit, uint8_t const * data, uint8_t length);
bool i2c_bus_s1_read(uint8_t address_7bit, uint8_t * data, uint8_t length);
bool i2c_bus_s1_probe(uint8_t address_7bit);
size_t i2c_bus_s1_scan(i2c_bus_s1_device_t * devices, size_t max_devices);
i2c_bus_s1_diag_t i2c_bus_s1_last_diag(void);
const char * i2c_bus_s1_diag_text(i2c_bus_s1_diag_t diag);

#ifdef __cplusplus
}
#endif

#endif /* I2C_BUS_S1_H */
