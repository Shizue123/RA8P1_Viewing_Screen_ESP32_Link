#ifndef BH1750_H
#define BH1750_H

#include <stdbool.h>
#include <stdint.h>

typedef struct st_bh1750_sample
{
    float lux;
    uint8_t address;
    uint8_t channel;
    bool via_mux;
} bh1750_sample_t;

typedef enum e_bh1750_diag
{
    BH1750_DIAG_OK = 0,
    BH1750_DIAG_SDA_STUCK,
    BH1750_DIAG_SCL_STUCK,
    BH1750_DIAG_WRITE_ADDR_NACK,
    BH1750_DIAG_WRITE_DATA_NACK,
    BH1750_DIAG_READ_ADDR_NACK,
    BH1750_DIAG_MEASURE_TIMEOUT,
} bh1750_diag_t;

bool bh1750_init(void);
bool bh1750_read(bh1750_sample_t * sample);
bool bh1750_last(bh1750_sample_t * sample);   /* v0.9.23: 仿 aht20_last() 缓存接口 */
bh1750_diag_t bh1750_last_diag(void);
const char * bh1750_diag_text(bh1750_diag_t diag);

#endif /* BH1750_H */
