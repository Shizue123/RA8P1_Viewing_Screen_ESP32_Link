#ifndef AHT20_H
#define AHT20_H

#include <stdbool.h>
#include <stdint.h>

typedef struct st_aht20_sample
{
    float temperature_c;
    float humidity_rh;
    uint8_t status;
    bool crc_ok;
} aht20_sample_t;

typedef enum e_aht20_diag
{
    AHT20_DIAG_OK = 0,
    AHT20_DIAG_SDA_STUCK,
    AHT20_DIAG_SCL_STUCK,
    AHT20_DIAG_WRITE_ADDR_NACK,
    AHT20_DIAG_WRITE_DATA_NACK,
    AHT20_DIAG_READ_ADDR_NACK,
    AHT20_DIAG_NOT_CALIBRATED,
    AHT20_DIAG_BUSY_TIMEOUT,
    AHT20_DIAG_CRC_FAIL,
} aht20_diag_t;

bool aht20_init(void);
bool aht20_read(aht20_sample_t * sample);
aht20_diag_t aht20_last_diag(void);
const char * aht20_diag_text(aht20_diag_t diag);
bool aht20_route_via_mux(void);
uint8_t aht20_active_channel(void);

/* v0.9.20: 给 app_ui.c ports_timer_cb 用，返回最近一次成功 read 的缓存值 */
bool aht20_last(aht20_sample_t * sample);

#endif /* AHT20_H */
