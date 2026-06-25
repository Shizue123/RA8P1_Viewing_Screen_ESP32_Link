#include "i2c_bus_s1.h"

#include <stdio.h>
#include <string.h>

#include "hal_data.h"

#define PIN_I2C_S1_SDA         BSP_IO_PORT_03_PIN_09
#define PIN_I2C_S1_SCL         BSP_IO_PORT_03_PIN_06
#define I2C_BUS_S1_TIMEOUT     (250U)
#define I2C_BUS_S1_READ_OFFSET (1U)
#define I2C_BUS_S1_DELAY_US    (5U)
#define I2C_BUS_S1_MUX_ADDRESS (0x70U)
#define I2C_BUS_S1_MUX_CHANNEL_COUNT (8U)
#define I2C_BUS_S1_LINE_RELEASE_CFG ((uint32_t) IOPORT_CFG_PORT_DIRECTION_INPUT | (uint32_t) IOPORT_CFG_PULLUP_ENABLE)
#define I2C_BUS_S1_SCL_HIGH_CFG ((uint32_t) IOPORT_CFG_PORT_DIRECTION_OUTPUT | \
                                 (uint32_t) IOPORT_CFG_DRIVE_MID_IIC | \
                                 (uint32_t) IOPORT_CFG_PORT_OUTPUT_HIGH)
#define I2C_BUS_S1_SDA_HIGH_CFG ((uint32_t) IOPORT_CFG_PORT_DIRECTION_OUTPUT | \
                                 (uint32_t) IOPORT_CFG_DRIVE_MID_IIC | \
                                 (uint32_t) IOPORT_CFG_PORT_OUTPUT_HIGH)
#define I2C_BUS_S1_LINE_DRIVE_LOW_CFG ((uint32_t) IOPORT_CFG_PORT_DIRECTION_OUTPUT | \
                                       (uint32_t) IOPORT_CFG_NMOS_ENABLE | \
                                       (uint32_t) IOPORT_CFG_DRIVE_MID_IIC | \
                                       (uint32_t) IOPORT_CFG_PORT_OUTPUT_LOW)

static volatile i2c_bus_s1_diag_t g_i2c_bus_s1_diag = I2C_BUS_S1_DIAG_OK;

static void i2c_bus_s1_set_diag(i2c_bus_s1_diag_t diag)
{
    g_i2c_bus_s1_diag = diag;
}

static void i2c_bus_s1_delay(void)
{
    R_BSP_SoftwareDelay(I2C_BUS_S1_DELAY_US, BSP_DELAY_UNITS_MICROSECONDS);
}

static void i2c_bus_s1_sda_release(void)
{
    (void) R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_I2C_S1_SDA, I2C_BUS_S1_LINE_RELEASE_CFG);
}

static void i2c_bus_s1_sda_drive_high(void)
{
    (void) R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_I2C_S1_SDA, I2C_BUS_S1_SDA_HIGH_CFG);
}

static void i2c_bus_s1_sda_drive_low(void)
{
    (void) R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_I2C_S1_SDA, I2C_BUS_S1_LINE_DRIVE_LOW_CFG);
}

static void i2c_bus_s1_scl_release(void)
{
    (void) R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_I2C_S1_SCL, I2C_BUS_S1_SCL_HIGH_CFG);
}

static void i2c_bus_s1_scl_drive_low(void)
{
    (void) R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_I2C_S1_SCL, I2C_BUS_S1_LINE_DRIVE_LOW_CFG);
}

static bsp_io_level_t i2c_bus_s1_sda_read(void)
{
    bsp_io_level_t level = BSP_IO_LEVEL_LOW;
    (void) R_IOPORT_PinRead(&g_ioport_ctrl, PIN_I2C_S1_SDA, &level);
    return level;
}

static bool i2c_bus_s1_scl_release_wait(void)
{
    i2c_bus_s1_scl_release();
    i2c_bus_s1_delay();
    return true;
}

static void i2c_bus_s1_idle(void)
{
    i2c_bus_s1_sda_release();
    (void) i2c_bus_s1_scl_release_wait();
}

static void i2c_bus_s1_recover(void)
{
    i2c_bus_s1_idle();

    for (uint8_t i = 0U; i < 9U; i++) {
        i2c_bus_s1_scl_drive_low();
        i2c_bus_s1_delay();
        if (!i2c_bus_s1_scl_release_wait()) {
            break;
        }
    }

    i2c_bus_s1_sda_drive_low();
    i2c_bus_s1_delay();
    (void) i2c_bus_s1_scl_release_wait();
    i2c_bus_s1_sda_release();
    i2c_bus_s1_delay();
}

static bool i2c_bus_s1_prepare(void)
{
    i2c_bus_s1_set_diag(I2C_BUS_S1_DIAG_OK);
    i2c_bus_s1_idle();
    if (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SCL_STUCK) {
        return false;
    }
    if (i2c_bus_s1_sda_read() == BSP_IO_LEVEL_HIGH) {
        return true;
    }

    i2c_bus_s1_recover();
    if (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SCL_STUCK) {
        return false;
    }
    if (i2c_bus_s1_sda_read() == BSP_IO_LEVEL_HIGH) {
        return true;
    }

    i2c_bus_s1_set_diag(I2C_BUS_S1_DIAG_SDA_STUCK);
    return false;
}

static void i2c_bus_s1_start(void)
{
    i2c_bus_s1_sda_drive_high();
    (void) i2c_bus_s1_scl_release_wait();
    i2c_bus_s1_sda_drive_low();
    i2c_bus_s1_delay();
    i2c_bus_s1_scl_drive_low();
}

static void i2c_bus_s1_stop(void)
{
    i2c_bus_s1_sda_drive_low();
    i2c_bus_s1_delay();
    (void) i2c_bus_s1_scl_release_wait();
    i2c_bus_s1_sda_drive_high();
    i2c_bus_s1_delay();
    i2c_bus_s1_sda_release();
}

static bool i2c_bus_s1_wait_ack(i2c_bus_s1_diag_t nack_diag)
{
    uint16_t timeout = 0U;

    i2c_bus_s1_sda_release();
    i2c_bus_s1_scl_drive_low();
    i2c_bus_s1_delay();
    if (!i2c_bus_s1_scl_release_wait()) {
        i2c_bus_s1_stop();
        return false;
    }

    while (i2c_bus_s1_sda_read() != BSP_IO_LEVEL_LOW) {
        if (++timeout > I2C_BUS_S1_TIMEOUT) {
            i2c_bus_s1_recover();
            i2c_bus_s1_stop();
            i2c_bus_s1_set_diag(nack_diag);
            return false;
        }
        i2c_bus_s1_delay();
    }

    i2c_bus_s1_delay();
    i2c_bus_s1_scl_drive_low();
    return true;
}

static void i2c_bus_s1_send_byte(uint8_t data)
{
    for (uint8_t i = 0U; i < 8U; i++) {
        i2c_bus_s1_scl_drive_low();
        i2c_bus_s1_delay();
        if ((data & 0x80U) != 0U) {
            i2c_bus_s1_sda_drive_high();
        } else {
            i2c_bus_s1_sda_drive_low();
        }
        i2c_bus_s1_delay();
        (void) i2c_bus_s1_scl_release_wait();
        data <<= 1;
    }

    i2c_bus_s1_scl_drive_low();
    i2c_bus_s1_sda_release();
}

static uint8_t i2c_bus_s1_read_byte(bool send_ack)
{
    uint8_t byte = 0U;

    i2c_bus_s1_sda_release();
    for (uint8_t i = 0U; i < 8U; i++) {
        i2c_bus_s1_scl_drive_low();
        i2c_bus_s1_delay();
        (void) i2c_bus_s1_scl_release_wait();
        byte = (uint8_t) ((byte << 1) | (i2c_bus_s1_sda_read() != BSP_IO_LEVEL_LOW ? 1U : 0U));
    }

    i2c_bus_s1_scl_drive_low();
    if (send_ack) {
        i2c_bus_s1_sda_drive_low();
    } else {
        i2c_bus_s1_sda_release();
    }
    i2c_bus_s1_delay();
    (void) i2c_bus_s1_scl_release_wait();
    i2c_bus_s1_scl_drive_low();
    i2c_bus_s1_sda_release();
    return byte;
}

static bool i2c_bus_s1_raw_write(uint8_t address_7bit, uint8_t const * data, uint8_t length);
static bool i2c_bus_s1_raw_read(uint8_t address_7bit, uint8_t * data, uint8_t length);
static bool i2c_bus_s1_raw_probe(uint8_t address_7bit);

static bool i2c_bus_s1_mux_present_internal(void)
{
    i2c_bus_s1_diag_t diag_before_probe;
    bool present;

    diag_before_probe = i2c_bus_s1_last_diag();
    present = i2c_bus_s1_raw_probe(I2C_BUS_S1_MUX_ADDRESS);
    if (present) {
        i2c_bus_s1_set_diag(I2C_BUS_S1_DIAG_OK);
        return true;
    }

    if ((i2c_bus_s1_last_diag() != I2C_BUS_S1_DIAG_SDA_STUCK) &&
            (i2c_bus_s1_last_diag() != I2C_BUS_S1_DIAG_SCL_STUCK)) {
        i2c_bus_s1_set_diag(diag_before_probe);
    }

    return false;
}

static bool i2c_bus_s1_select_route(uint8_t channel)
{
    uint8_t mux_mask = 0U;

    if (channel == I2C_BUS_S1_CHANNEL_DIRECT) {
        if (!i2c_bus_s1_mux_present_internal()) {
            return true;
        }

        return i2c_bus_s1_raw_write(I2C_BUS_S1_MUX_ADDRESS, &mux_mask, 1U);
    }

    if (channel >= I2C_BUS_S1_MUX_CHANNEL_COUNT) {
        i2c_bus_s1_set_diag(I2C_BUS_S1_DIAG_ADDR_NACK);
        return false;
    }

    if (!i2c_bus_s1_mux_present_internal()) {
        if (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_OK) {
            i2c_bus_s1_set_diag(I2C_BUS_S1_DIAG_ADDR_NACK);
        }
        return false;
    }

    mux_mask = (uint8_t) (1U << channel);
    return i2c_bus_s1_raw_write(I2C_BUS_S1_MUX_ADDRESS, &mux_mask, 1U);
}

static void i2c_bus_s1_identify_device_on_channel(uint8_t channel, uint8_t address_7bit, i2c_bus_s1_device_t * device)
{
    uint8_t status = 0U;

    if (device == NULL) {
        return;
    }

    device->address = address_7bit;
    device->channel = channel;
    device->via_mux = channel != I2C_BUS_S1_CHANNEL_DIRECT;
    device->signature_matched = false;
    (void) snprintf(device->label, sizeof(device->label), "I2C-0x%02X", address_7bit);

    switch (address_7bit)
    {
        case I2C_BUS_S1_MUX_ADDRESS:
            (void) snprintf(device->label, sizeof(device->label), "9548A-MUX");
            device->signature_matched = true;
            break;

        case 0x38U:
            if (i2c_bus_s1_read_channel(channel, address_7bit, &status, 1U) && ((status & 0x08U) == 0x08U)) {
                (void) snprintf(device->label, sizeof(device->label), "AHT20");
                device->signature_matched = true;
            } else {
                (void) snprintf(device->label, sizeof(device->label), "0x38-class");
            }
            break;

        case 0x23U:
        case 0x5CU:
            (void) snprintf(device->label, sizeof(device->label), "BH1750");
            device->signature_matched = true;
            break;

        case 0x3CU:
        case 0x3DU:
            (void) snprintf(device->label, sizeof(device->label), "OLED-class");
            device->signature_matched = true;
            break;

        case 0x57U:
            (void) snprintf(device->label, sizeof(device->label), "EEPROM-class");
            device->signature_matched = true;
            break;

        case 0x68U:
            (void) snprintf(device->label, sizeof(device->label), "IMU-RTC-class");
            device->signature_matched = true;
            break;

        case 0x76U:
        case 0x77U:
            (void) snprintf(device->label, sizeof(device->label), "ENV-class");
            device->signature_matched = true;
            break;

        default:
            break;
    }
}

void i2c_bus_s1_init(void)
{
    i2c_bus_s1_idle();
}

bool i2c_bus_s1_mux_present(void)
{
    return i2c_bus_s1_mux_present_internal();
}

static bool i2c_bus_s1_raw_write(uint8_t address_7bit, uint8_t const * data, uint8_t length)
{
    if (!i2c_bus_s1_prepare()) {
        return false;
    }

    i2c_bus_s1_start();
    i2c_bus_s1_send_byte((uint8_t) (address_7bit << 1));
    if (!i2c_bus_s1_wait_ack(I2C_BUS_S1_DIAG_ADDR_NACK)) {
        return false;
    }

    for (uint8_t i = 0U; i < length; i++) {
        i2c_bus_s1_send_byte(data[i]);
        if (!i2c_bus_s1_wait_ack(I2C_BUS_S1_DIAG_DATA_NACK)) {
            return false;
        }
    }

    i2c_bus_s1_stop();
    return true;
}

static bool i2c_bus_s1_raw_read(uint8_t address_7bit, uint8_t * data, uint8_t length)
{
    if ((data == NULL) || (length == 0U)) {
        return false;
    }

    if (!i2c_bus_s1_prepare()) {
        return false;
    }

    i2c_bus_s1_start();
    i2c_bus_s1_send_byte((uint8_t) ((address_7bit << 1) | I2C_BUS_S1_READ_OFFSET));
    if (!i2c_bus_s1_wait_ack(I2C_BUS_S1_DIAG_ADDR_NACK)) {
        return false;
    }

    for (uint8_t i = 0U; i < length; i++) {
        data[i] = i2c_bus_s1_read_byte(i < (length - 1U));
    }

    i2c_bus_s1_stop();
    return true;
}

static bool i2c_bus_s1_raw_probe(uint8_t address_7bit)
{
    if (!i2c_bus_s1_prepare()) {
        return false;
    }

    i2c_bus_s1_start();
    i2c_bus_s1_send_byte((uint8_t) (address_7bit << 1));
    if (!i2c_bus_s1_wait_ack(I2C_BUS_S1_DIAG_ADDR_NACK)) {
        return false;
    }

    i2c_bus_s1_stop();
    i2c_bus_s1_set_diag(I2C_BUS_S1_DIAG_OK);
    return true;
}

bool i2c_bus_s1_write_channel(uint8_t channel, uint8_t address_7bit, uint8_t const * data, uint8_t length)
{
    if (!i2c_bus_s1_select_route(channel)) {
        return false;
    }

    return i2c_bus_s1_raw_write(address_7bit, data, length);
}

bool i2c_bus_s1_read_channel(uint8_t channel, uint8_t address_7bit, uint8_t * data, uint8_t length)
{
    if (!i2c_bus_s1_select_route(channel)) {
        return false;
    }

    return i2c_bus_s1_raw_read(address_7bit, data, length);
}

bool i2c_bus_s1_probe_channel(uint8_t channel, uint8_t address_7bit)
{
    if (!i2c_bus_s1_select_route(channel)) {
        return false;
    }

    return i2c_bus_s1_raw_probe(address_7bit);
}

bool i2c_bus_s1_write(uint8_t address_7bit, uint8_t const * data, uint8_t length)
{
    return i2c_bus_s1_write_channel(I2C_BUS_S1_CHANNEL_DIRECT, address_7bit, data, length);
}

bool i2c_bus_s1_read(uint8_t address_7bit, uint8_t * data, uint8_t length)
{
    return i2c_bus_s1_read_channel(I2C_BUS_S1_CHANNEL_DIRECT, address_7bit, data, length);
}

bool i2c_bus_s1_probe(uint8_t address_7bit)
{
    return i2c_bus_s1_probe_channel(I2C_BUS_S1_CHANNEL_DIRECT, address_7bit);
}

size_t i2c_bus_s1_scan(i2c_bus_s1_device_t * devices, size_t max_devices)
{
    size_t found = 0U;
    bool mux_present;

    mux_present = i2c_bus_s1_mux_present_internal();
    if (mux_present && (devices != NULL) && (found < max_devices)) {
        i2c_bus_s1_identify_device_on_channel(I2C_BUS_S1_CHANNEL_DIRECT, I2C_BUS_S1_MUX_ADDRESS, &devices[found]);
    }
    if (mux_present) {
        found++;
    }

    if (!i2c_bus_s1_select_route(I2C_BUS_S1_CHANNEL_DIRECT)) {
        return 0U;
    }

    for (uint8_t address = 0x08U; address <= 0x77U; address++) {
        if (mux_present && (address == I2C_BUS_S1_MUX_ADDRESS)) {
            continue;
        }

        if (!i2c_bus_s1_raw_probe(address)) {
            if ((i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SDA_STUCK) ||
                    (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SCL_STUCK)) {
                return found;
            }
            continue;
        }

        if ((devices != NULL) && (found < max_devices)) {
            i2c_bus_s1_identify_device_on_channel(I2C_BUS_S1_CHANNEL_DIRECT, address, &devices[found]);
        }
        found++;
    }

    if (mux_present) {
        for (uint8_t channel = 0U; channel < I2C_BUS_S1_MUX_CHANNEL_COUNT; channel++) {
            if (!i2c_bus_s1_select_route(channel)) {
                continue;
            }

            for (uint8_t address = 0x08U; address <= 0x77U; address++) {
                if (address == I2C_BUS_S1_MUX_ADDRESS) {
                    continue;
                }

                if (!i2c_bus_s1_raw_probe(address)) {
                    if ((i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SDA_STUCK) ||
                            (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SCL_STUCK)) {
                        return found;
                    }
                    continue;
                }

                if ((devices != NULL) && (found < max_devices)) {
                    i2c_bus_s1_identify_device_on_channel(channel, address, &devices[found]);
                }
                found++;
            }
        }

        (void) i2c_bus_s1_select_route(I2C_BUS_S1_CHANNEL_DIRECT);
    }

    i2c_bus_s1_set_diag(I2C_BUS_S1_DIAG_OK);
    return found;
}

i2c_bus_s1_diag_t i2c_bus_s1_last_diag(void)
{
    return g_i2c_bus_s1_diag;
}

const char * i2c_bus_s1_diag_text(i2c_bus_s1_diag_t diag)
{
    switch (diag)
    {
        case I2C_BUS_S1_DIAG_OK:
            return "ok";
        case I2C_BUS_S1_DIAG_SDA_STUCK:
            return "sda stuck";
        case I2C_BUS_S1_DIAG_SCL_STUCK:
            return "scl stuck";
        case I2C_BUS_S1_DIAG_ADDR_NACK:
            return "addr nack";
        case I2C_BUS_S1_DIAG_DATA_NACK:
            return "data nack";
        default:
            return "unknown";
    }
}
