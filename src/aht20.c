#include "aht20.h"

#include "hal_data.h"
#include "i2c_bus_s1.h"

#define AHT20_I2C_ADDRESS            (0x38U)
#define AHT20_I2C_CHANNEL            (0U)
#define AHT20_CMD_INIT               (0xBEU)
#define AHT20_CMD_MEASURE            (0xACU)
#define AHT20_CMD_SOFT_RESET         (0xBAU)
#define AHT20_STATUS_BUSY            (0x80U)
#define AHT20_STATUS_CALIBRATED_MASK (0x08U)
#define AHT20_RETRY_LIMIT            (3U)
#define AHT20_MUX_CHANNEL_COUNT      (8U)

static volatile aht20_diag_t g_aht20_diag = AHT20_DIAG_OK;
static bool g_aht20_route_mux;
static uint8_t g_aht20_channel = AHT20_I2C_CHANNEL;
static aht20_sample_t g_last_sample;          /* v0.9.20: aht20_last() 缓存 */
static bool g_last_sample_valid = false;

static void aht20_set_diag(aht20_diag_t diag)
{
    g_aht20_diag = diag;
}

static void aht20_set_route(bool via_mux, uint8_t channel)
{
    g_aht20_route_mux = via_mux;
    g_aht20_channel = channel;
}

static bool aht20_probe_on_route(bool via_mux, uint8_t channel)
{
    bool ok;

    if (via_mux) {
        ok = i2c_bus_s1_probe_channel(channel, AHT20_I2C_ADDRESS);
    } else {
        ok = i2c_bus_s1_probe(AHT20_I2C_ADDRESS);
    }

    if (ok) {
        aht20_set_route(via_mux, channel);
        aht20_set_diag(AHT20_DIAG_OK);
    }

    return ok;
}

static bool aht20_resolve_route(void)
{
    bool mux_present = i2c_bus_s1_mux_present();

    if (mux_present) {
        if ((g_aht20_channel < AHT20_MUX_CHANNEL_COUNT) &&
                aht20_probe_on_route(true, g_aht20_channel)) {
            return true;
        }

        for (uint8_t channel = 0U; channel < AHT20_MUX_CHANNEL_COUNT; channel++) {
            if ((channel == g_aht20_channel) && (g_aht20_channel < AHT20_MUX_CHANNEL_COUNT)) {
                continue;
            }
            if (aht20_probe_on_route(true, channel)) {
                return true;
            }
        }
    } else if (aht20_probe_on_route(false, I2C_BUS_S1_CHANNEL_DIRECT)) {
        return true;
    }

    if (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SDA_STUCK) {
        aht20_set_diag(AHT20_DIAG_SDA_STUCK);
    } else if (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SCL_STUCK) {
        aht20_set_diag(AHT20_DIAG_SCL_STUCK);
    } else {
        aht20_set_diag(AHT20_DIAG_READ_ADDR_NACK);
    }

    return false;
}

static bool aht20_write_bytes(uint8_t const * data, uint8_t length)
{
    if (!aht20_resolve_route()) {
        return false;
    }

    if ((g_aht20_route_mux && i2c_bus_s1_write_channel(g_aht20_channel, AHT20_I2C_ADDRESS, data, length)) ||
            ((!g_aht20_route_mux) && i2c_bus_s1_write(AHT20_I2C_ADDRESS, data, length))) {
        return true;
    }

    switch (i2c_bus_s1_last_diag())
    {
        case I2C_BUS_S1_DIAG_SDA_STUCK:
            aht20_set_diag(AHT20_DIAG_SDA_STUCK);
            break;
        case I2C_BUS_S1_DIAG_SCL_STUCK:
            aht20_set_diag(AHT20_DIAG_SCL_STUCK);
            break;
        case I2C_BUS_S1_DIAG_DATA_NACK:
            aht20_set_diag(AHT20_DIAG_WRITE_DATA_NACK);
            break;
        case I2C_BUS_S1_DIAG_ADDR_NACK:
        default:
            aht20_set_diag(AHT20_DIAG_WRITE_ADDR_NACK);
            break;
    }

    return false;
}

static bool aht20_read_bytes(uint8_t * data, uint8_t length)
{
    if (!aht20_resolve_route()) {
        return false;
    }

    if ((g_aht20_route_mux && i2c_bus_s1_read_channel(g_aht20_channel, AHT20_I2C_ADDRESS, data, length)) ||
            ((!g_aht20_route_mux) && i2c_bus_s1_read(AHT20_I2C_ADDRESS, data, length))) {
        return true;
    }

    if (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SDA_STUCK) {
        aht20_set_diag(AHT20_DIAG_SDA_STUCK);
    } else if (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SCL_STUCK) {
        aht20_set_diag(AHT20_DIAG_SCL_STUCK);
    } else {
        aht20_set_diag(AHT20_DIAG_READ_ADDR_NACK);
    }

    return false;
}

static uint8_t aht20_crc8(uint8_t const * data, uint8_t length)
{
    uint8_t crc = 0xFFU;

    for (uint8_t i = 0; i < length; i++) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8U; bit++) {
            if ((crc & 0x80U) != 0U) {
                crc = (uint8_t) ((uint8_t) (crc << 1) ^ 0x31U);
            } else {
                crc = (uint8_t) (crc << 1);
            }
        }
    }

    return crc;
}

bool aht20_init(void)
{
    uint8_t status = 0U;
    uint8_t init_cmd[3] = { AHT20_CMD_INIT, 0x08U, 0x00U };
    uint8_t soft_reset = AHT20_CMD_SOFT_RESET;
    bool saw_status = false;

    aht20_set_diag(AHT20_DIAG_OK);
    g_aht20_route_mux = false;
    g_aht20_channel = AHT20_I2C_CHANNEL;
    i2c_bus_s1_init();
    R_BSP_SoftwareDelay(120U, BSP_DELAY_UNITS_MILLISECONDS);

    for (uint8_t attempt = 0U; attempt < AHT20_RETRY_LIMIT; attempt++) {
        i2c_bus_s1_init();
        if (!aht20_write_bytes(&soft_reset, 1U)) {
            continue;
        }
        R_BSP_SoftwareDelay(20U, BSP_DELAY_UNITS_MILLISECONDS);

        if (!aht20_read_bytes(&status, 1U)) {
            continue;
        }
        saw_status = true;

        if ((status & AHT20_STATUS_CALIBRATED_MASK) != AHT20_STATUS_CALIBRATED_MASK) {
            if (!aht20_write_bytes(init_cmd, 3U)) {
                continue;
            }
            R_BSP_SoftwareDelay(20U, BSP_DELAY_UNITS_MILLISECONDS);
            if (!aht20_read_bytes(&status, 1U)) {
                continue;
            }
            saw_status = true;
        }

        if ((status & AHT20_STATUS_CALIBRATED_MASK) == AHT20_STATUS_CALIBRATED_MASK) {
            aht20_set_diag(AHT20_DIAG_OK);
            return true;
        }
    }

    if (saw_status) {
        aht20_set_diag(AHT20_DIAG_NOT_CALIBRATED);
    }
    return false;
}

bool aht20_read(aht20_sample_t * sample)
{
    uint8_t trigger_cmd[3] = { AHT20_CMD_MEASURE, 0x33U, 0x00U };
    uint8_t raw[7];
    uint32_t humidity_raw;
    uint32_t temperature_raw;

    if (sample == NULL) {
        return false;
    }

    aht20_set_diag(AHT20_DIAG_OK);
    for (uint8_t attempt = 0U; attempt < AHT20_RETRY_LIMIT; attempt++) {
        if (!aht20_write_bytes(trigger_cmd, 3U)) {
            (void) aht20_init();
            continue;
        }

        R_BSP_SoftwareDelay(85U, BSP_DELAY_UNITS_MILLISECONDS);

        if (!aht20_read_bytes(raw, 7U)) {
            (void) aht20_init();
            continue;
        }

        if ((raw[0] & AHT20_STATUS_BUSY) == 0U) {
            humidity_raw = ((uint32_t) raw[1] << 12) | ((uint32_t) raw[2] << 4) | ((uint32_t) raw[3] >> 4);
            temperature_raw = (((uint32_t) raw[3] & 0x0FU) << 16) | ((uint32_t) raw[4] << 8) | raw[5];

            sample->status = raw[0];
            sample->humidity_rh = ((float) humidity_raw * 100.0f) / 1048576.0f;
            sample->temperature_c = (((float) temperature_raw * 200.0f) / 1048576.0f) - 50.0f;
            sample->crc_ok = aht20_crc8(raw, 6U) == raw[6];
            if (sample->crc_ok) {
                aht20_set_diag(AHT20_DIAG_OK);
                g_last_sample = *sample;
                g_last_sample_valid = true;
                return true;
            }
            aht20_set_diag(AHT20_DIAG_CRC_FAIL);
            break;
        }

        for (uint8_t attempts = 0; attempts < 10U; attempts++) {
            R_BSP_SoftwareDelay(10U, BSP_DELAY_UNITS_MILLISECONDS);
            if (!aht20_read_bytes(raw, 7U)) {
                break;
            }
            if ((raw[0] & AHT20_STATUS_BUSY) != 0U) {
                continue;
            }

            humidity_raw = ((uint32_t) raw[1] << 12) | ((uint32_t) raw[2] << 4) | ((uint32_t) raw[3] >> 4);
            temperature_raw = (((uint32_t) raw[3] & 0x0FU) << 16) | ((uint32_t) raw[4] << 8) | raw[5];

            sample->status = raw[0];
            sample->humidity_rh = ((float) humidity_raw * 100.0f) / 1048576.0f;
            sample->temperature_c = (((float) temperature_raw * 200.0f) / 1048576.0f) - 50.0f;
            sample->crc_ok = aht20_crc8(raw, 6U) == raw[6];
            if (sample->crc_ok) {
                aht20_set_diag(AHT20_DIAG_OK);
                g_last_sample = *sample;
                g_last_sample_valid = true;
                return true;
            }
            aht20_set_diag(AHT20_DIAG_CRC_FAIL);
            break;
        }

        if (g_aht20_diag == AHT20_DIAG_OK) {
            aht20_set_diag(AHT20_DIAG_BUSY_TIMEOUT);
        }
        (void) aht20_init();
    }

    return false;
}

aht20_diag_t aht20_last_diag(void)
{
    return g_aht20_diag;
}

const char * aht20_diag_text(aht20_diag_t diag)
{
    switch (diag) {
        case AHT20_DIAG_OK:
            return "ok";
        case AHT20_DIAG_SDA_STUCK:
            return "sda stuck";
        case AHT20_DIAG_SCL_STUCK:
            return "scl stuck";
        case AHT20_DIAG_WRITE_ADDR_NACK:
            return "write addr nack";
        case AHT20_DIAG_WRITE_DATA_NACK:
            return "write data nack";
        case AHT20_DIAG_READ_ADDR_NACK:
            return "read addr nack";
        case AHT20_DIAG_NOT_CALIBRATED:
            return "not calibrated";
        case AHT20_DIAG_BUSY_TIMEOUT:
            return "busy timeout";
        case AHT20_DIAG_CRC_FAIL:
            return "crc fail";
        default:
            return "unknown";
    }
}

bool aht20_route_via_mux(void)
{
    return g_aht20_route_mux;
}

uint8_t aht20_active_channel(void)
{
    return g_aht20_route_mux ? g_aht20_channel : I2C_BUS_S1_CHANNEL_DIRECT;
}

/* v0.9.20: 给 app_ui.c ports_timer_cb 用，UI 不直接触发 I2C 读 */
bool aht20_last(aht20_sample_t * sample)
{
    if (sample == NULL || !g_last_sample_valid) {
        return false;
    }
    *sample = g_last_sample;
    return true;
}
