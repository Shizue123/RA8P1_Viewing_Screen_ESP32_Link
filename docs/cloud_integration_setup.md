# Cloud Integration & Credentials Setup

This project connects an RA8P1 board to a cloud backend through an ESP32-S3
UART bridge. The published source contains **placeholder credentials only**.
Before building and flashing the firmware, replace the placeholders with your
own real values.

> See [../SECURITY.md](../SECURITY.md) for the security policy. Never commit
> real credentials to a public repository.

## 1. ESP32-S3 firmware

Open
`esp32-s3-uart-link-arduino/esp32_s3_uart_link/esp32_s3_uart_link.ino` and
edit the credential constants block (marked with the
`CLOUD / NETWORK CREDENTIALS` comment):

```cpp
// Built-in WiFi profile (fallback when no saved network is available)
constexpr WifiProfile kWifiProfiles[] = {
  {"YOUR_WIFI_SSID", "YOUR_WIFI_PASSWORD"},
};

constexpr char kMqttHost[] = "your-mqtt-broker-host";        // e.g. 192.168.1.10
constexpr uint16_t kMqttPort = 1883;
constexpr char kMqttUser[] = "your-mqtt-username";
constexpr char kMqttPassword[] = "your-mqtt-password";
constexpr char kDefaultDeviceId[] = "ra8p1_demo_001";

constexpr char kCloudDeviceRegisterUrl[] = "http://your-cloud-host/api/devices/register";
constexpr char kCloudHermesChatUrl[]     = "http://your-cloud-host/agent/hermes/chat";
constexpr char kCloudApiToken[]          = "your-cloud-api-token";
```

### RA8P1 default WiFi display name

`src/app_ui.c` holds a default SSID shown on the HMI before the ESP32 reports
the active network:

```c
static char s_wifi_name[32] = "YOUR_WIFI_SSID";
```

## 2. Validation / tooling scripts

The helper scripts under `tools/` accept the cloud host via `--host`:

```
python tools/validate_rule_program_loop.py --host your-cloud-host
python tools/validate_threshold_loop.py    --host your-cloud-host
python tools/validate_delivery_baseline.py --host your-cloud-host
```

The default `--host` value in each script is `your-cloud-host`; pass the real
host explicitly or edit the default before running.

## 3. Cloud backend (self-hosted)

The project expects a self-hosted backend exposing:

| Endpoint                          | Method | Purpose                                  |
|-----------------------------------|--------|------------------------------------------|
| `/health`                         | GET    | Liveness probe                           |
| `/api/devices/register`           | POST   | Device registration, returns device_id   |
| `/agent/hermes/chat`              | POST   | Natural-language → rule_program.v1       |
| MQTT broker (port 1883 / 8883)    | —      | Deploy / status / telemetry / event topics |

Deploy the backend on your own server and point the ESP32 firmware at it.

## 4. Production hardening checklist

- [ ] Switch MQTT to TLS (port 8883) with valid certificates.
- [ ] Use per-device credentials instead of a shared MQTT user.
- [ ] Place the backend behind a reverse proxy (nginx) with TLS and rate
      limiting.
- [ ] Rotate the cloud API token periodically.
- [ ] Restrict the MQTT broker to authenticated clients only.

## 5. Keeping credentials out of git

If you maintain a private fork, keep real credentials in a file excluded by
`.gitignore` (e.g. `secrets.local.h`) and include it from the `.ino`, or read
them from ESP32 NVS at runtime via the web provisioning flow already
implemented in the firmware.
