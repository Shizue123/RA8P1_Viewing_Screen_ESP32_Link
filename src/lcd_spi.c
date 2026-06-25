#include "lcd_spi.h"

/* ===== Software SPI ===== */
void spi_delay(void) { }

void spi_write_byte(uint8_t data)
{
    for (int i = 0; i < 8; i++) {
        if (data & 0x80) mosi_write(BSP_IO_LEVEL_HIGH);
        else             mosi_write(BSP_IO_LEVEL_LOW);
        data <<= 1;
        sck_low();  spi_delay();
        sck_high(); spi_delay();
    }
}

/* ===== LCD command / data / window ===== */
void lcd_cmd(uint8_t cmd)  { cs_low(); dc_low();  spi_write_byte(cmd); cs_high(); }
void lcd_data(uint8_t d)   { cs_low(); dc_high(); spi_write_byte(d);   cs_high(); }

void lcd_set_window(uint16_t x1, uint16_t y1, uint16_t x2, uint16_t y2)
{
    lcd_cmd(0x2A);
    lcd_data((uint8_t)(x1 >> 8));
    lcd_data((uint8_t)(x1 & 0xFF));
    lcd_data((uint8_t)(x2 >> 8));
    lcd_data((uint8_t)(x2 & 0xFF));

    lcd_cmd(0x2B);
    lcd_data((uint8_t)(y1 >> 8));
    lcd_data((uint8_t)(y1 & 0xFF));
    lcd_data((uint8_t)(y2 >> 8));
    lcd_data((uint8_t)(y2 & 0xFF));

    lcd_cmd(0x2C);
}

void lcd_fill_screen(uint16_t color)
{
    lcd_fill_rect(0, 0, 319, 479, color);
}

void lcd_fill_rect(uint16_t x1, uint16_t y1, uint16_t x2, uint16_t y2, uint16_t color)
{
    uint8_t r5 = (uint8_t)((color >> 11) & 0x1F);
    uint8_t g6 = (uint8_t)((color >> 5) & 0x3F);
    uint8_t b5 = (uint8_t)(color & 0x1F);
    uint8_t r8 = (uint8_t)((r5 << 3) | (r5 >> 2));
    uint8_t g8 = (uint8_t)((g6 << 2) | (g6 >> 4));
    uint8_t b8 = (uint8_t)((b5 << 3) | (b5 >> 2));
    uint32_t pixel_count = (uint32_t)(x2 - x1 + 1U) * (uint32_t)(y2 - y1 + 1U);

    lcd_set_window(x1, y1, x2, y2);

    dc_high();
    cs_low();
    for (uint32_t i = 0; i < pixel_count; i++) {
        spi_write_byte(r8);
        spi_write_byte(g8);
        spi_write_byte(b8);
    }
    cs_high();
}

/* ===== ILI9488 init (STM32 4SPI reference, 18-bit RGB666) ===== */
void lcd_init(void)
{
    R_BSP_PinAccessEnable();
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_SCK,  IOPORT_CFG_PORT_DIRECTION_OUTPUT | IOPORT_CFG_DRIVE_HIGH | IOPORT_CFG_PORT_OUTPUT_LOW);
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_MOSI, IOPORT_CFG_PORT_DIRECTION_OUTPUT | IOPORT_CFG_DRIVE_HIGH | IOPORT_CFG_PORT_OUTPUT_LOW);
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_CS,   IOPORT_CFG_PORT_DIRECTION_OUTPUT | IOPORT_CFG_DRIVE_HIGH | IOPORT_CFG_PORT_OUTPUT_HIGH);
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_RST,  IOPORT_CFG_PORT_DIRECTION_OUTPUT | IOPORT_CFG_DRIVE_HIGH | IOPORT_CFG_PORT_OUTPUT_HIGH);
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_DC,   IOPORT_CFG_PORT_DIRECTION_OUTPUT | IOPORT_CFG_DRIVE_HIGH | IOPORT_CFG_PORT_OUTPUT_LOW);
    R_IOPORT_PinCfg(&g_ioport_ctrl, PIN_LED,  IOPORT_CFG_PORT_DIRECTION_OUTPUT | IOPORT_CFG_DRIVE_HIGH | IOPORT_CFG_PORT_OUTPUT_LOW);

    cs_high();
    sck_low();

    R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_RST, BSP_IO_LEVEL_HIGH);
    R_BSP_SoftwareDelay(1, BSP_DELAY_UNITS_MILLISECONDS);
    R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_RST, BSP_IO_LEVEL_LOW);
    R_BSP_SoftwareDelay(10, BSP_DELAY_UNITS_MILLISECONDS);
    R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_RST, BSP_IO_LEVEL_HIGH);
    R_BSP_SoftwareDelay(150, BSP_DELAY_UNITS_MILLISECONDS);
    led_write(BSP_IO_LEVEL_HIGH);

    lcd_cmd(0xF7); lcd_data(0xA9); lcd_data(0x51); lcd_data(0x2C); lcd_data(0x82);
    lcd_cmd(0xEC); lcd_data(0x00); lcd_data(0x02); lcd_data(0x03); lcd_data(0x7A);
    lcd_cmd(0xC0); lcd_data(0x13); lcd_data(0x13);
    lcd_cmd(0xC1); lcd_data(0x41);
    lcd_cmd(0xC5); lcd_data(0x00); lcd_data(0x28); lcd_data(0x80);
    lcd_cmd(0xB0); lcd_data(0x00);
    lcd_cmd(0xB1); lcd_data(0xB0); lcd_data(0x11);
    lcd_cmd(0xB4); lcd_data(0x02);
    lcd_cmd(0xB6); lcd_data(0x02); lcd_data(0x22);
    lcd_cmd(0xB7); lcd_data(0xC6);
    lcd_cmd(0xBE); lcd_data(0x00); lcd_data(0x04);
    lcd_cmd(0xE9); lcd_data(0x00);
    lcd_cmd(0xF4); lcd_data(0x00); lcd_data(0x00); lcd_data(0x0F);

    lcd_cmd(0xE0);
    { const uint8_t g[] = {0x00,0x04,0x0E,0x08,0x17,0x0A,0x40,0x79,0x4D,0x07,0x0E,0x0A,0x1A,0x1D,0x0F};
      dc_high(); cs_low(); for (int i=0;i<15;i++) spi_write_byte(g[i]); cs_high(); }

    lcd_cmd(0xE1);
    { const uint8_t g[] = {0x00,0x1B,0x1F,0x02,0x10,0x05,0x32,0x34,0x43,0x02,0x0A,0x09,0x33,0x37,0x0F};
      dc_high(); cs_low(); for (int i=0;i<15;i++) spi_write_byte(g[i]); cs_high(); }

    lcd_cmd(0xF4); lcd_data(0x00); lcd_data(0x00); lcd_data(0x0F);
    lcd_cmd(0x36); lcd_data(0x08);
    lcd_cmd(0x3A); lcd_data(0x66);
    lcd_cmd(0x21);
    lcd_cmd(0x11); R_BSP_SoftwareDelay(120, BSP_DELAY_UNITS_MILLISECONDS);
    lcd_cmd(0x29); R_BSP_SoftwareDelay(50, BSP_DELAY_UNITS_MILLISECONDS);
}
