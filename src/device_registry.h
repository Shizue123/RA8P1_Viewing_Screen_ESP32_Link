#ifndef DEVICE_REGISTRY_H
#define DEVICE_REGISTRY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 改进.md §一/二: 设备注册表 — 功能类别 + 型号识别 */
typedef enum e_device_class
{
    DEVICE_CLASS_UNKNOWN = 0,
    DEVICE_CLASS_ENV_TEMP_HUMIDITY,   /* 温湿度类 — AHT20/AHT30 */
    DEVICE_CLASS_ENV_LIGHT,            /* 光照类 — BH1750 */
    DEVICE_CLASS_DISPLAY,              /* LCD ILI9488 */
    DEVICE_CLASS_TOUCH,                /* 触摸 FT6336 */
    DEVICE_CLASS_BRIDGE,               /* 网桥 ESP32-S3 */
    DEVICE_CLASS_COUNT
} device_class_t;

typedef enum e_device_model
{
    DEVICE_MODEL_UNKNOWN = 0,
    DEVICE_MODEL_AHT20,
    DEVICE_MODEL_AHT30,
    DEVICE_MODEL_BH1750,
    DEVICE_MODEL_ESP32_S3,
    DEVICE_MODEL_ILI9488,
    DEVICE_MODEL_FT6336,
    DEVICE_MODEL_COUNT
} device_model_t;

/* hw_row_t 由 app_ui.c 定义为匿名 struct — 此处仅前向声明,不重新定义 */
struct st_hw_row;
typedef struct st_hw_row hw_row_t;

#define DEVICE_REGISTRY_MAX (8U)

typedef struct st_device_registry_entry
{
    char key[16];                  /* "aht20", "bh1750" — 唯一 */
    device_class_t cls;
    device_model_t model;
    char title[32];                /* "温湿度传感器" / "光照传感器" */
    char subtitle[40];             /* "在线 · 采样正常" */
    char model_name[16];           /* "AHT20" / "BH1750" / "待确认" */
    char interface_text[24];       /* "I²C · 7-bit 0x38" */
    char address_text[8];          /* "0x38" */
    bool present;                  /* 扫描发现 */
    bool online;                   /* 真实采样 OK */
    uint32_t last_update_ms;
    /* 详情行模板 — 由调用方注入(避免 registry 依赖 ui 层) */
    const hw_row_t * rows;
    int row_count;
} device_registry_entry_t;

void device_registry_init(void);

/* 5ms tick — 由 hal_entry 调用,内部累计到 5000ms 触发 refresh */
void device_registry_tick_5ms(uint32_t now_ms);

/* 强制从 platform_ports 拉一遍最新状态 */
void device_registry_refresh_from_ports(void);

/* 查询接口(给 app_ui 调用) */
size_t device_registry_get_count(void);
size_t device_registry_get_count_by_class(device_class_t cls);
device_registry_entry_t const * device_registry_get_by_index(size_t index);
device_registry_entry_t const * device_registry_get_by_key(const char * key);
device_registry_entry_t const * device_registry_get_by_class(device_class_t cls, size_t index);

#ifdef __cplusplus
}
#endif

#endif /* DEVICE_REGISTRY_H */