#include "device_registry.h"
#include "platform_ports.h"

#include <stdio.h>
#include <string.h>

#define DEVICE_REGISTRY_REFRESH_INTERVAL_MS (5000U)

static device_registry_entry_t g_entries[DEVICE_REGISTRY_MAX];
static size_t g_entry_count = 0U;
static uint32_t g_last_refresh_ms = 0U;
static uint32_t g_elapsed_ms = 0U;

static void device_registry_copy(char * dst, size_t cap, const char * src)
{
    if (src == NULL) {
        dst[0] = '\0';
        return;
    }
    size_t i;
    for (i = 0U; i + 1U < cap && src[i] != '\0'; i++) {
        dst[i] = src[i];
    }
    dst[i] = '\0';
}

static device_registry_entry_t * find_or_create(const char * key)
{
    /* 查找 */
    for (size_t i = 0U; i < g_entry_count; i++) {
        if (strcmp(g_entries[i].key, key) == 0) {
            return &g_entries[i];
        }
    }
    /* 新建 */
    if (g_entry_count >= DEVICE_REGISTRY_MAX) {
        return NULL;
    }
    device_registry_entry_t * e = &g_entries[g_entry_count++];
    memset(e, 0, sizeof(*e));
    device_registry_copy(e->key, sizeof(e->key), key);
    return e;
}

static const char * model_to_name(device_model_t m)
{
    switch (m) {
        case DEVICE_MODEL_AHT20:    return "AHT20";
        case DEVICE_MODEL_AHT30:    return "AHT30";
        case DEVICE_MODEL_BH1750:   return "BH1750";
        case DEVICE_MODEL_ESP32_S3: return "ESP32-S3";
        case DEVICE_MODEL_ILI9488:  return "ILI9488";
        case DEVICE_MODEL_FT6336:   return "FT6336";
        default:                    return "待确认";
    }
}

static device_model_t label_to_model(const char * label)
{
    if (label == NULL) return DEVICE_MODEL_UNKNOWN;
    if (strcmp(label, "AHT20") == 0) return DEVICE_MODEL_AHT20;
    if (strcmp(label, "BH1750") == 0) return DEVICE_MODEL_BH1750;
    if (strcmp(label, "9548A-MUX") == 0) return DEVICE_MODEL_UNKNOWN;
    return DEVICE_MODEL_UNKNOWN;
}

static void refresh_static_entries(void)
{
    /* v0.9.23: 基本设备始终存在(ESP32 网桥 / LCD / 触摸) — SG90 不进注册表 */
    device_registry_entry_t * e;

    e = find_or_create("esp32");
    if (e != NULL) {
        e->cls = DEVICE_CLASS_BRIDGE;
        e->model = DEVICE_MODEL_ESP32_S3;
        device_registry_copy(e->title, sizeof(e->title), "ESP32-S3 网桥");
        device_registry_copy(e->model_name, sizeof(e->model_name), "ESP32-S3 Dev Module");
        device_registry_copy(e->interface_text, sizeof(e->interface_text), "UART-BRIDGE · 115200 bps");
        e->present = (platform_ports_get_port(3U) != NULL); /* uart.bridge */
        e->online  = e->present && (strcmp(platform_ports_get_port(3U)->status, "online") == 0);
    }

    e = find_or_create("lcd");
    if (e != NULL) {
        e->cls = DEVICE_CLASS_DISPLAY;
        e->model = DEVICE_MODEL_ILI9488;
        device_registry_copy(e->title, sizeof(e->title), "LCD 显示屏");
        device_registry_copy(e->model_name, sizeof(e->model_name), "ILI9488");
        device_registry_copy(e->interface_text, sizeof(e->interface_text), "SPI · 320×480");
        e->present = true;
        e->online  = true;
    }

    e = find_or_create("touch");
    if (e != NULL) {
        e->cls = DEVICE_CLASS_TOUCH;
        e->model = DEVICE_MODEL_FT6336;
        device_registry_copy(e->title, sizeof(e->title), "触摸控制器");
        device_registry_copy(e->model_name, sizeof(e->model_name), "FT6336");
        device_registry_copy(e->interface_text, sizeof(e->interface_text), "I²C · 7-bit 0x38");
        e->present = true;
        e->online  = true;
    }
}

static void refresh_from_i2c_s1(void)
{
    platform_port_t const * port = platform_ports_get_port(0U); /* i2c.s1 */
    if (port == NULL) return;

    /* 温湿度类: capability "env.temperature" + module "aht20" */
    bool has_aht20 = false;
    bool has_bh1750 = false;
    bool aht20_online = false;
    bool bh1750_online = false;
    char aht20_addr[8] = "--";
    char bh1750_addr[8] = "--";

    for (uint8_t i = 0U; i < port->capability_count; i++) {
        const char * cap = port->capabilities[i].id;
        const char * status = port->capabilities[i].status;
        if (strcmp(cap, "env.temperature") == 0 || strcmp(cap, "env.humidity") == 0) {
            has_aht20 = true;
            if (strcmp(status, "online") == 0 || strcmp(status, "read") == 0) {
                aht20_online = true;
            }
        }
        if (strcmp(cap, "env.light.lux") == 0) {
            has_bh1750 = true;
            if (strcmp(status, "online") == 0 || strcmp(status, "read") == 0) {
                bh1750_online = true;
            }
        }
    }

    /* 从 port.module 读地址 */
    if (port->module.module_id[0] != '\0') {
        device_model_t mm = label_to_model(port->module.module_id);
        if (mm == DEVICE_MODEL_AHT20) {
            device_registry_copy(aht20_addr, sizeof(aht20_addr), "0x38");
        } else if (mm == DEVICE_MODEL_BH1750) {
            if (port->module.address[0] != '\0') {
                device_registry_copy(bh1750_addr, sizeof(bh1750_addr), port->module.address);
            } else {
                device_registry_copy(bh1750_addr, sizeof(bh1750_addr), "0x23");
            }
        }
    }

    /* 更新或删除 aht20 entry */
    if (has_aht20) {
        device_registry_entry_t * e = find_or_create("aht20");
        if (e != NULL) {
            e->cls = DEVICE_CLASS_ENV_TEMP_HUMIDITY;
            e->model = DEVICE_MODEL_AHT20;
            device_registry_copy(e->title, sizeof(e->title), "温湿度传感器");
            device_registry_copy(e->subtitle, sizeof(e->subtitle), aht20_online ? "在线 · 采样正常" : "已识别 · 离线");
            device_registry_copy(e->model_name, sizeof(e->model_name), model_to_name(e->model));
            snprintf(e->interface_text, sizeof(e->interface_text), "I²C · 7-bit %s", aht20_addr);
            device_registry_copy(e->address_text, sizeof(e->address_text), aht20_addr);
            e->present = true;
            e->online = aht20_online;
            e->last_update_ms = g_last_refresh_ms;
        }
    } else {
        /* 删 aht20 entry — 改进.md §三-4: 不允许空壳 */
        for (size_t i = 0U; i < g_entry_count; i++) {
            if (strcmp(g_entries[i].key, "aht20") == 0) {
                memmove(&g_entries[i], &g_entries[i + 1], (g_entry_count - i - 1) * sizeof(device_registry_entry_t));
                g_entry_count--;
                break;
            }
        }
    }

    /* 更新或删除 bh1750 entry */
    if (has_bh1750) {
        device_registry_entry_t * e = find_or_create("bh1750");
        if (e != NULL) {
            e->cls = DEVICE_CLASS_ENV_LIGHT;
            e->model = DEVICE_MODEL_BH1750;
            device_registry_copy(e->title, sizeof(e->title), "光照传感器");
            device_registry_copy(e->subtitle, sizeof(e->subtitle), bh1750_online ? "在线 · 采样正常" : "已识别 · 离线");
            device_registry_copy(e->model_name, sizeof(e->model_name), model_to_name(e->model));
            snprintf(e->interface_text, sizeof(e->interface_text), "I²C · 7-bit %s", bh1750_addr);
            device_registry_copy(e->address_text, sizeof(e->address_text), bh1750_addr);
            e->present = true;
            e->online = bh1750_online;
            e->last_update_ms = g_last_refresh_ms;
        }
    } else {
        for (size_t i = 0U; i < g_entry_count; i++) {
            if (strcmp(g_entries[i].key, "bh1750") == 0) {
                memmove(&g_entries[i], &g_entries[i + 1], (g_entry_count - i - 1) * sizeof(device_registry_entry_t));
                g_entry_count--;
                break;
            }
        }
    }
}

void device_registry_init(void)
{
    memset(g_entries, 0, sizeof(g_entries));
    g_entry_count = 0U;
    g_elapsed_ms = 0U;
    g_last_refresh_ms = 0U;
    refresh_static_entries();
    /* 启动时先刷一次(让 i2c 扫描数据到位) */
    device_registry_refresh_from_ports();
}

void device_registry_refresh_from_ports(void)
{
    refresh_static_entries();
    refresh_from_i2c_s1();
}

void device_registry_tick_5ms(uint32_t now_ms)
{
    g_elapsed_ms += 5U;
    g_last_refresh_ms = now_ms;
    if (g_elapsed_ms >= DEVICE_REGISTRY_REFRESH_INTERVAL_MS) {
        g_elapsed_ms = 0U;
        device_registry_refresh_from_ports();
    }
}

size_t device_registry_get_count(void)
{
    return g_entry_count;
}

size_t device_registry_get_count_by_class(device_class_t cls)
{
    size_t n = 0U;
    for (size_t i = 0U; i < g_entry_count; i++) {
        if (g_entries[i].cls == cls) n++;
    }
    return n;
}

device_registry_entry_t const * device_registry_get_by_index(size_t index)
{
    if (index >= g_entry_count) return NULL;
    return &g_entries[index];
}

device_registry_entry_t const * device_registry_get_by_key(const char * key)
{
    if (key == NULL) return NULL;
    for (size_t i = 0U; i < g_entry_count; i++) {
        if (strcmp(g_entries[i].key, key) == 0) {
            return &g_entries[i];
        }
    }
    return NULL;
}

device_registry_entry_t const * device_registry_get_by_class(device_class_t cls, size_t nth)
{
    size_t n = 0U;
    for (size_t i = 0U; i < g_entry_count; i++) {
        if (g_entries[i].cls == cls) {
            if (n == nth) return &g_entries[i];
            n++;
        }
    }
    return NULL;
}