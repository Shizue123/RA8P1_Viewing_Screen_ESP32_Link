#include "ft6336.h"
#include "hal_data.h"

#define PIN_CTP_SDA BSP_IO_PORT_04_PIN_00
#define PIN_CTP_SCL BSP_IO_PORT_04_PIN_01
#define PIN_CTP_RST BSP_IO_PORT_04_PIN_02

#define FT6336_I2C_ADDR         0x38U
#define FT6336_REG_GESTURE_ID   0x01U
#define FT6336_REG_TD_STATUS    0x02U
#define FT6336_REG_TOUCH1_XH    0x03U
#define FT6336_REG_THRESHOLD    0x80U
#define FT6336_REG_CHIP_ID      0xA3U
#define FT6336_REG_VENDOR_ID    0xA8U
#define FT6336_REG_FOCALTECH_ID 0xACU
#define FT6336_TOUCH_FRAME_LEN  16U
#define FT6336_TOUCH_MAX        2U
#define FT6336_TOUCH_EVENT_MASK 0xC0U
#define FT6336_TOUCH_HIGH_MASK  0x0FU
#define FT6336_TOUCH_ID_MASK    0xF0U
#define FT6336_TOUCH_THRESHOLD  32U
#define FT6336_I2C_TIMEOUT      250U

volatile uint8_t g_ft6336_last_frame[FT6336_TOUCH_FRAME_LEN];
volatile uint8_t g_ft6336_last_read_ok;
volatile uint8_t g_ft6336_last_touches;
volatile uint8_t g_ft6336_last_chip_id;
volatile uint8_t g_ft6336_last_vendor_id;
volatile uint8_t g_ft6336_last_focaltech_id;

static void i2c_delay(void)
{
    R_BSP_SoftwareDelay(5U, BSP_DELAY_UNITS_MICROSECONDS);
}

static void ctp_sda_out(void)
{
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_CTP_SDA, IOPORT_CFG_PORT_DIRECTION_OUTPUT);
}

static void ctp_sda_in(void)
{
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_CTP_SDA, IOPORT_CFG_PORT_DIRECTION_INPUT);
}

static void ctp_sda_write(bsp_io_level_t v)
{
    R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_CTP_SDA, v);
}

static void ctp_scl_write(bsp_io_level_t v)
{
    R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_CTP_SCL, v);
}

static bsp_io_level_t ctp_sda_read(void)
{
    bsp_io_level_t v;
    R_IOPORT_PinRead(&g_ioport_ctrl, PIN_CTP_SDA, &v);
    return v;
}

static void i2c_bus_recover(void)
{
    ctp_sda_out();
    ctp_sda_write(BSP_IO_LEVEL_HIGH);
    for (int i = 0; i < 9; i++) {
        ctp_scl_write(BSP_IO_LEVEL_LOW);
        i2c_delay();
        ctp_scl_write(BSP_IO_LEVEL_HIGH);
        i2c_delay();
    }
    ctp_scl_write(BSP_IO_LEVEL_LOW);
}

static void i2c_start(void)
{
    ctp_sda_out();
    ctp_sda_write(BSP_IO_LEVEL_HIGH);
    ctp_scl_write(BSP_IO_LEVEL_HIGH);
    R_BSP_SoftwareDelay(30U, BSP_DELAY_UNITS_MICROSECONDS);
    ctp_sda_write(BSP_IO_LEVEL_LOW);
    i2c_delay();
    ctp_scl_write(BSP_IO_LEVEL_LOW);
}

static void i2c_stop(void)
{
    ctp_sda_out();
    ctp_scl_write(BSP_IO_LEVEL_HIGH);
    R_BSP_SoftwareDelay(30U, BSP_DELAY_UNITS_MICROSECONDS);
    ctp_sda_write(BSP_IO_LEVEL_LOW);
    i2c_delay();
    ctp_sda_write(BSP_IO_LEVEL_HIGH);
    i2c_delay();
}

static uint8_t i2c_wait_ack(void)
{
    uint16_t timeout = 0U;

    ctp_sda_in();
    ctp_sda_write(BSP_IO_LEVEL_HIGH);
    ctp_scl_write(BSP_IO_LEVEL_LOW);
    i2c_delay();
    ctp_scl_write(BSP_IO_LEVEL_HIGH);
    i2c_delay();
    while (ctp_sda_read() != BSP_IO_LEVEL_LOW) {
        timeout++;
        if (timeout > FT6336_I2C_TIMEOUT) {
            i2c_bus_recover();
            i2c_stop();
            return 1U;
        }
        i2c_delay();
    }

    ctp_scl_write(BSP_IO_LEVEL_LOW);
    return 0U;
}

static void i2c_send_byte(uint8_t data)
{
    ctp_sda_out();
    for (int i = 0; i < 8; i++) {
        ctp_scl_write(BSP_IO_LEVEL_LOW);
        i2c_delay();
        ctp_sda_write((data & 0x80U) ? BSP_IO_LEVEL_HIGH : BSP_IO_LEVEL_LOW);
        i2c_delay();
        ctp_scl_write(BSP_IO_LEVEL_HIGH);
        i2c_delay();
        data <<= 1;
    }
    ctp_scl_write(BSP_IO_LEVEL_LOW);
}

static uint8_t i2c_read_byte(uint8_t send_ack)
{
    uint8_t byte = 0U;

    ctp_sda_in();
    R_BSP_SoftwareDelay(30U, BSP_DELAY_UNITS_MICROSECONDS);
    for (int i = 0; i < 8; i++) {
        ctp_scl_write(BSP_IO_LEVEL_LOW);
        i2c_delay();
        ctp_scl_write(BSP_IO_LEVEL_HIGH);
        i2c_delay();
        byte = (uint8_t) ((byte << 1) | ((ctp_sda_read() != BSP_IO_LEVEL_LOW) ? 1U : 0U));
    }

    ctp_scl_write(BSP_IO_LEVEL_LOW);
    ctp_sda_out();
    ctp_sda_write(send_ack ? BSP_IO_LEVEL_LOW : BSP_IO_LEVEL_HIGH);
    i2c_delay();
    ctp_scl_write(BSP_IO_LEVEL_HIGH);
    i2c_delay();
    ctp_scl_write(BSP_IO_LEVEL_LOW);
    return byte;
}

static uint8_t ft6336_write_reg(uint8_t reg, uint8_t value)
{
    i2c_start();
    i2c_send_byte((uint8_t) ((FT6336_I2C_ADDR << 1) | 0U));
    if (i2c_wait_ack() != 0U) {
        return 1U;
    }
    i2c_send_byte(reg);
    if (i2c_wait_ack() != 0U) {
        return 1U;
    }
    i2c_send_byte(value);
    if (i2c_wait_ack() != 0U) {
        return 1U;
    }
    i2c_stop();
    return 0U;
}

static uint8_t ft6336_read_block(uint8_t reg, uint8_t * buf, uint8_t len)
{
    if ((buf == NULL) || (len == 0U)) {
        return 1U;
    }

    i2c_start();
    i2c_send_byte((uint8_t) ((FT6336_I2C_ADDR << 1) | 0U));
    if (i2c_wait_ack() != 0U) {
        return 1U;
    }
    i2c_send_byte(reg);
    if (i2c_wait_ack() != 0U) {
        return 1U;
    }

    i2c_start();
    i2c_send_byte((uint8_t) ((FT6336_I2C_ADDR << 1) | 1U));
    if (i2c_wait_ack() != 0U) {
        return 1U;
    }

    for (uint8_t i = 0U; i < len; i++) {
        buf[i] = i2c_read_byte((uint8_t) (i + 1U < len));
    }
    i2c_stop();
    return 0U;
}

static uint8_t ft6336_read_reg(uint8_t reg, uint8_t * value)
{
    if (value == NULL) {
        return 1U;
    }

    return ft6336_read_block(reg, value, 1U);
}

void ft6336_init(void)
{
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_CTP_SDA, IOPORT_CFG_PORT_DIRECTION_OUTPUT);
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_CTP_SCL, IOPORT_CFG_PORT_DIRECTION_OUTPUT);
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_CTP_RST, IOPORT_CFG_PORT_DIRECTION_OUTPUT);
    R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_CTP_SDA, BSP_IO_LEVEL_HIGH);
    R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_CTP_SCL, BSP_IO_LEVEL_HIGH);

    R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_CTP_RST, BSP_IO_LEVEL_LOW);
    R_BSP_SoftwareDelay(20, BSP_DELAY_UNITS_MILLISECONDS);
    R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_CTP_RST, BSP_IO_LEVEL_HIGH);
    R_BSP_SoftwareDelay(300, BSP_DELAY_UNITS_MILLISECONDS);

    (void) ft6336_write_reg(FT6336_REG_THRESHOLD, FT6336_TOUCH_THRESHOLD);
    g_ft6336_last_read_ok = 0U;
    g_ft6336_last_touches = 0U;
    for (uint8_t i = 0U; i < FT6336_TOUCH_FRAME_LEN; i++) {
        g_ft6336_last_frame[i] = 0U;
    }
    (void) ft6336_read_reg(FT6336_REG_CHIP_ID, (uint8_t *) &g_ft6336_last_chip_id);
    (void) ft6336_read_reg(FT6336_REG_VENDOR_ID, (uint8_t *) &g_ft6336_last_vendor_id);
    (void) ft6336_read_reg(FT6336_REG_FOCALTECH_ID, (uint8_t *) &g_ft6336_last_focaltech_id);
}

uint8_t ft6336_read_point(ft6336_point_t * point)
{
    uint8_t buf[4];
    uint8_t touches;

    if (point == NULL) {
        return 0U;
    }

    point->touches = 0U;
    point->event = 0U;
    point->track_id = 0U;
    point->x = 0U;
    point->y = 0U;

    for (uint8_t i = 0U; i < FT6336_TOUCH_FRAME_LEN; i++) {
        g_ft6336_last_frame[i] = 0U;
    }
    g_ft6336_last_read_ok = 0U;
    if (ft6336_read_reg(FT6336_REG_TD_STATUS, &touches) != 0U) {
        return 0U;
    }
    g_ft6336_last_frame[FT6336_REG_TD_STATUS] = touches;
    g_ft6336_last_read_ok = 1U;
    touches = (uint8_t) (touches & 0x0FU);
    g_ft6336_last_touches = touches;
    if ((touches == 0U) || (touches > FT6336_TOUCH_MAX)) {
        return 0U;
    }

    if (ft6336_read_block(FT6336_REG_TOUCH1_XH, buf, (uint8_t) sizeof(buf)) != 0U) {
        return 0U;
    }
    for (uint8_t i = 0U; i < (uint8_t) sizeof(buf); i++) {
        g_ft6336_last_frame[FT6336_REG_TOUCH1_XH + i] = buf[i];
    }

    point->touches = touches;
    point->event = (uint8_t) ((buf[0] & FT6336_TOUCH_EVENT_MASK) >> 6);
    point->x = (uint16_t) ((((uint16_t) buf[0] & FT6336_TOUCH_HIGH_MASK) << 8) |
                           (uint16_t) buf[1]);
    point->track_id = (uint8_t) ((buf[2] & FT6336_TOUCH_ID_MASK) >> 4);
    point->y = (uint16_t) ((((uint16_t) buf[2] & FT6336_TOUCH_HIGH_MASK) << 8) |
                           (uint16_t) buf[3]);
    return 1U;
}

uint8_t ft6336_scan(uint16_t * x, uint16_t * y)
{
    ft6336_point_t point;

    if (ft6336_read_point(&point) == 0U) {
        return 0U;
    }

    if (x != NULL) {
        *x = point.x;
    }
    if (y != NULL) {
        *y = point.y;
    }
    return 1U;
}
