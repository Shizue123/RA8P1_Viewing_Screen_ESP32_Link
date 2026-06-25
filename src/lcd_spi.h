#ifndef LCD_SPI_H
#define LCD_SPI_H

#include "hal_data.h"

/* ===== Pin definitions ===== */
#define PIN_CS      BSP_IO_PORT_05_PIN_15  // P515
#define PIN_RST     BSP_IO_PORT_06_PIN_00  // P600
#define PIN_DC      BSP_IO_PORT_01_PIN_02  // P102
#define PIN_LED     BSP_IO_PORT_01_PIN_06  // P106
#define PIN_SCK     BSP_IO_PORT_05_PIN_14  // P514
#define PIN_MOSI    BSP_IO_PORT_07_PIN_14  // P714

#ifdef __cplusplus
extern "C" {
#endif

/* ===== GPIO helpers ===== */
static inline void cs_low(void)  { R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_CS, BSP_IO_LEVEL_LOW); }
static inline void cs_high(void) { R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_CS, BSP_IO_LEVEL_HIGH); }
static inline void dc_low(void)  { R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_DC, BSP_IO_LEVEL_LOW); }
static inline void dc_high(void) { R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_DC, BSP_IO_LEVEL_HIGH); }
static inline void sck_low(void) { R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_SCK, BSP_IO_LEVEL_LOW); }
static inline void sck_high(void){ R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_SCK, BSP_IO_LEVEL_HIGH); }
static inline void mosi_write(bsp_io_level_t v) { R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_MOSI, v); }
static inline void led_write(bsp_io_level_t v)  { R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_LED, v); }

/* ===== Software SPI ===== */
void spi_delay(void);
void spi_write_byte(uint8_t data);

/* ===== LCD command / data / window ===== */
void lcd_cmd(uint8_t cmd);
void lcd_data(uint8_t d);
void lcd_set_window(uint16_t x1, uint16_t y1, uint16_t x2, uint16_t y2);
void lcd_fill_rect(uint16_t x1, uint16_t y1, uint16_t x2, uint16_t y2, uint16_t color);
void lcd_fill_screen(uint16_t color);

/* ===== LCD initialization ===== */
void lcd_init(void);

#ifdef __cplusplus
}
#endif

#endif /* LCD_SPI_H */
