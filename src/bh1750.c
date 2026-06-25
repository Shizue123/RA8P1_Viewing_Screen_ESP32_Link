#include "bh1750.h"

#include "hal_data.h"
#include "i2c_bus_s1.h"

#define BH1750_I2C_CHANNEL          (1U)
#define BH1750_I2C_ADDRESS_LOW      (0x23U)
#define BH1750_I2C_ADDRESS_HIGH     (0x5CU)
#define BH1750_CMD_POWER_ON         (0x01U)
#define BH1750_CMD_RESET            (0x07U)
#define BH1750_CMD_ONE_TIME_HI_RES  (0x20U)
#define BH1750_RETRY_LIMIT          (2U)
#define BH1750_MEASURE_DELAY_MS     (180U)
#define BH1750_MUX_CHANNEL_COUNT    (8U)

static volatile bh1750_diag_t g_bh1750_diag = BH1750_DIAG_OK;
static uint8_t g_bh1750_address = BH1750_I2C_ADDRESS_LOW;
static bool g_bh1750_route_mux;
static uint8_t g_bh1750_channel = BH1750_I2C_CHANNEL;
/* v0.9.23: 仿 aht20_last() 缓存,给 UI 详情页无侵入读真值 */
static bh1750_sample_t g_bh1750_last_sample;
static bool g_bh1750_last_valid = false;

static void bh1750_set_diag(bh1750_diag_t diag)
{
    g_bh1750_diag = diag;
}

static void bh1750_set_route(bool via_mux, uint8_t address)
{
    g_bh1750_route_mux = via_mux;
    g_bh1750_address = address;
}

static void bh1750_set_route_channel(bool via_mux, uint8_t channel, uint8_t address)
{
    g_bh1750_route_mux = via_mux;
    g_bh1750_channel = channel;
    g_bh1750_address = address;
}

static void bh1750_map_write_failure(void)
{
    switch (i2c_bus_s1_last_diag())
    {
        case I2C_BUS_S1_DIAG_SDA_STUCK:
            bh1750_set_diag(BH1750_DIAG_SDA_STUCK);
            break;
        case I2C_BUS_S1_DIAG_SCL_STUCK:
            bh1750_set_diag(BH1750_DIAG_SCL_STUCK);
            break;
        case I2C_BUS_S1_DIAG_DATA_NACK:
            bh1750_set_diag(BH1750_DIAG_WRITE_DATA_NACK);
            break;
        case I2C_BUS_S1_DIAG_ADDR_NACK:
        default:
            bh1750_set_diag(BH1750_DIAG_WRITE_ADDR_NACK);
            break;
    }
}

static void bh1750_map_read_failure(void)
{
    if (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SDA_STUCK) {
        bh1750_set_diag(BH1750_DIAG_SDA_STUCK);
    } else if (i2c_bus_s1_last_diag() == I2C_BUS_S1_DIAG_SCL_STUCK) {
        bh1750_set_diag(BH1750_DIAG_SCL_STUCK);
    } else {
        bh1750_set_diag(BH1750_DIAG_READ_ADDR_NACK);
    }
}

static bool bh1750_probe_on_route(bool via_mux, uint8_t address)
{
    bool ok;

    if (via_mux) {
        ok = i2c_bus_s1_probe_channel(g_bh1750_channel, address);
    } else {
        ok = i2c_bus_s1_probe(address);
    }

    if (ok) {
        bh1750_set_route_channel(via_mux, g_bh1750_channel, address);
        bh1750_set_diag(BH1750_DIAG_OK);
    }

    return ok;
}

static bool bh1750_probe_channel_address(uint8_t channel, uint8_t address)
{
    bool ok = i2c_bus_s1_probe_channel(channel, address);

    if (ok) {
        bh1750_set_route_channel(true, channel, address);
        bh1750_set_diag(BH1750_DIAG_OK);
    }

    return ok;
}

static bool bh1750_resolve_route(void)
{
    bool mux_present = i2c_bus_s1_mux_present();

    if (mux_present) {
        if ((g_bh1750_channel < BH1750_MUX_CHANNEL_COUNT) &&
                bh1750_probe_channel_address(g_bh1750_channel, g_bh1750_address)) {
            return true;
        }

        for (uint8_t channel = 0U; channel < BH1750_MUX_CHANNEL_COUNT; channel++) {
            if ((channel == g_bh1750_channel) && (g_bh1750_channel < BH1750_MUX_CHANNEL_COUNT)) {
                continue;
            }
            if (bh1750_probe_channel_address(channel, BH1750_I2C_ADDRESS_LOW)) {
                return true;
            }
            if (bh1750_probe_channel_address(channel, BH1750_I2C_ADDRESS_HIGH)) {
                return true;
            }
        }
    } else {
        if (bh1750_probe_on_route(false, BH1750_I2C_ADDRESS_LOW)) {
            return true;
        }
        if (bh1750_probe_on_route(false, BH1750_I2C_ADDRESS_HIGH)) {
            return true;
        }
    }

    bh1750_map_read_failure();
    return false;
}

static bool bh1750_write_command(uint8_t command)
{
    bool ok;

    if (g_bh1750_route_mux) {
        ok = i2c_bus_s1_write_channel(g_bh1750_channel, g_bh1750_address, &command, 1U);
    } else {
        ok = i2c_bus_s1_write(g_bh1750_address, &command, 1U);
    }

    if (!ok) {
        bh1750_map_write_failure();
    }

    return ok;
}

static bool bh1750_read_raw(uint8_t * data)
{
    bool ok;

    if (g_bh1750_route_mux) {
        ok = i2c_bus_s1_read_channel(g_bh1750_channel, g_bh1750_address, data, 2U);
    } else {
        ok = i2c_bus_s1_read(g_bh1750_address, data, 2U);
    }

    if (!ok) {
        bh1750_map_read_failure();
    }

    return ok;
}

bool bh1750_init(void)
{
    bh1750_set_diag(BH1750_DIAG_OK);
    if (!bh1750_resolve_route()) {
        return false;
    }

    if (!bh1750_write_command(BH1750_CMD_POWER_ON)) {
        return false;
    }

    R_BSP_SoftwareDelay(10U, BSP_DELAY_UNITS_MILLISECONDS);
    if (!bh1750_write_command(BH1750_CMD_RESET)) {
        return false;
    }

    return true;
}

bool bh1750_read(bh1750_sample_t * sample)
{
    uint8_t raw[2];
    uint16_t raw_value;

    if (sample == NULL) {
        return false;
    }

    bh1750_set_diag(BH1750_DIAG_OK);
    for (uint8_t attempt = 0U; attempt < BH1750_RETRY_LIMIT; attempt++) {
        if (!bh1750_resolve_route()) {
            continue;
        }
        if (!bh1750_write_command(BH1750_CMD_POWER_ON)) {
            continue;
        }
        if (!bh1750_write_command(BH1750_CMD_ONE_TIME_HI_RES)) {
            continue;
        }

        R_BSP_SoftwareDelay(BH1750_MEASURE_DELAY_MS, BSP_DELAY_UNITS_MILLISECONDS);
        if (!bh1750_read_raw(raw)) {
            continue;
        }

        raw_value = (uint16_t) (((uint16_t) raw[0] << 8) | raw[1]);
        sample->lux = ((float) raw_value) / 1.2f;
        sample->address = g_bh1750_address;
        sample->via_mux = g_bh1750_route_mux;
        sample->channel = g_bh1750_route_mux ? g_bh1750_channel : I2C_BUS_S1_CHANNEL_DIRECT;
        bh1750_set_diag(BH1750_DIAG_OK);
        /* v0.9.23: 成功读取时缓存,给 bh1750_last() */
        g_bh1750_last_sample = *sample;
        g_bh1750_last_valid = true;
        return true;
    }

    if (g_bh1750_diag == BH1750_DIAG_OK) {
        bh1750_set_diag(BH1750_DIAG_MEASURE_TIMEOUT);
    }
    return false;
}

bh1750_diag_t bh1750_last_diag(void)
{
    return g_bh1750_diag;
}

/* v0.9.23: 仿 aht20_last(),UI 详情页无侵入读最近一次成功采样的 lux */
bool bh1750_last(bh1750_sample_t * sample)
{
    if (sample == NULL || !g_bh1750_last_valid) {
        return false;
    }
    *sample = g_bh1750_last_sample;
    return true;
}

const char * bh1750_diag_text(bh1750_diag_t diag)
{
    switch (diag)
    {
        case BH1750_DIAG_OK:
            return "ok";
        case BH1750_DIAG_SDA_STUCK:
            return "sda stuck";
        case BH1750_DIAG_SCL_STUCK:
            return "scl stuck";
        case BH1750_DIAG_WRITE_ADDR_NACK:
            return "write addr nack";
        case BH1750_DIAG_WRITE_DATA_NACK:
            return "write data nack";
        case BH1750_DIAG_READ_ADDR_NACK:
            return "read addr nack";
        case BH1750_DIAG_MEASURE_TIMEOUT:
            return "measure timeout";
        default:
            return "unknown";
    }
}
