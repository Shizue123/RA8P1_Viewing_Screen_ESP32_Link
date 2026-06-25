#ifndef ARDUINO_USB_CDC_ON_BOOT
#define ARDUINO_USB_CDC_ON_BOOT 1
#endif

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <time.h>

namespace
{
HardwareSerial kLinkUart(1);
WiFiClient g_wifi_client;
PubSubClient g_mqtt(g_wifi_client);
Preferences g_wifi_preferences;

constexpr uint32_t kBaudRate = 115200;
constexpr int kTxPin = 43;
constexpr int kRxPin = 44;
constexpr size_t kLineBufferSize = 320;
constexpr size_t kUsbLineBufferSize = 512;
constexpr size_t kWifiCredentialSize = 96;
constexpr uint32_t kHeartbeatIntervalMs = 5000;
constexpr uint32_t kStatusIntervalMs = 15000;
constexpr uint32_t kTelemetryIntervalMs = 15000;
constexpr uint32_t kUartStatusIntervalMs = 10000;
constexpr uint32_t kWifiRetryMs = 15000;
constexpr uint32_t kMqttRetryMs = 10000;
constexpr uint32_t kLinkActiveTimeoutMs = 2500;
constexpr uint32_t kEventFlashMs = 120;
constexpr uint32_t kFaultHoldMs = 1500;
constexpr uint32_t kWaitBlinkIntervalMs = 250;
constexpr uint32_t kFaultBlinkIntervalMs = 100;
constexpr uint32_t kTimeRetryMs = 5000;
constexpr uint32_t kTimeResyncMs = 3600000;
constexpr uint16_t kMqttPacketBufferSize = 4096;
constexpr size_t kMqttScriptMessageBufferSize = 4096;
constexpr size_t kI2cScanMaxDevices = 8U;
constexpr size_t kPortCapabilityMax = 4U;
constexpr size_t kBoardPortCount = 4U;
constexpr size_t kBoardSampleCount = 6U;

struct WifiProfile
{
  char const * ssid;
  char const * password;
};

struct CapabilityState
{
  bool valid;
  char id[40];
  char unit[12];
  char access[16];
  char status[16];
};

struct BoardPortState
{
  bool valid;
  char port_id[16];
  char physical_port[16];
  char channel[24];
  char type[16];
  char activation[16];
  char status[16];
  char diag[24];
  char module_id[24];
  char module_type[24];
  char module_class[24];
  char driver[24];
  char model_state[16];
  char binding_source[24];
  char confidence[16];
  char address[16];
  char device_key[48];
  uint32_t last_sample_ms;
  size_t capability_count;
  CapabilityState capabilities[kPortCapabilityMax];
};

struct BoardSampleState
{
  bool valid;
  char port_id[16];
  char module_type[24];
  char capability[40];
  char unit[12];
  char source[24];
  float value;
  uint32_t ts_ms;
};

// ============================================================================
// CLOUD / NETWORK CREDENTIALS  --  EDIT THESE BEFORE FLASHING
// ----------------------------------------------------------------------------
// The values below are PLACEHOLDERS. The real credentials were stripped before
// publishing this repository. Fill in your own WiFi SSID/password, MQTT broker
// host/credentials and cloud API token before building the firmware.
// See SECURITY.md and docs/cloud_integration_setup.md for details.
// ============================================================================
constexpr WifiProfile kWifiProfiles[] = {
  {"YOUR_WIFI_SSID", "YOUR_WIFI_PASSWORD"},
};
constexpr size_t kWifiProfileCount = sizeof(kWifiProfiles) / sizeof(kWifiProfiles[0]);
constexpr char kMqttHost[] = "your-mqtt-broker-host";
constexpr uint16_t kMqttPort = 1883;
constexpr char kMqttUser[] = "your-mqtt-username";
constexpr char kMqttPassword[] = "your-mqtt-password";
constexpr char kDefaultDeviceId[] = "ra8p1_demo_001";
constexpr char kCloudDeviceRegisterUrl[] = "http://your-cloud-host/api/devices/register";
constexpr char kCloudDeviceRegistrationSecret[] = "";
constexpr char kCloudHermesChatUrl[] = "http://your-cloud-host/agent/hermes/chat";
constexpr char kCloudApiToken[] = "your-cloud-api-token";
constexpr long kTimeZoneOffsetSeconds = 8L * 3600L;
constexpr int kTimeDaylightOffsetSeconds = 0;

char g_line_buffer[kLineBufferSize];
size_t g_line_length = 0U;
char g_usb_line_buffer[kUsbLineBufferSize];
size_t g_usb_line_length = 0U;
uint32_t g_last_rx_ms = 0U;
uint32_t g_rx_flash_until_ms = 0U;
uint32_t g_tx_flash_until_ms = 0U;
uint32_t g_fault_until_ms = 0U;
uint32_t g_last_heartbeat_ms = 0U;
uint32_t g_last_status_ms = 0U;
uint32_t g_last_telemetry_ms = 0U;
uint32_t g_last_uart_status_ms = 0U;
uint32_t g_last_wifi_attempt_ms = 0U;
uint32_t g_last_mqtt_attempt_ms = 0U;
uint32_t g_last_time_sync_ms = 0U;

bool g_wifi_connected = false;
bool g_mqtt_connected = false;
bool g_status_dirty = true;
bool g_telemetry_dirty = false;
bool g_uart_online = false;
bool g_saved_wifi_available = false;
bool g_device_registered = false;
bool g_time_service_started = false;
bool g_time_synced = false;

char g_status_topic[96];
char g_telemetry_topic[96];
char g_event_topic[96];
char g_script_topic[96];
char g_device_id[64] = "ra8p1_demo_001";
char g_device_secret[64] = "";
char g_ra8p1_uid[40] = "";
char g_esp32_mac[24] = "";
char g_esp32_chip_id[24] = "";
char g_last_request_id[64];
char g_last_script_id[64];
char g_last_intent_type[40];
char g_last_display_text[48];
char g_script_state[20] = "IDLE";
char g_last_execution_state[20] = "";
char g_last_execution_reason[24] = "";
char g_last_execution_operator[4] = "";
char g_last_execution_action[16] = "";
char g_saved_wifi_ssid[kWifiCredentialSize] = "";
char g_saved_wifi_password[kWifiCredentialSize] = "";
bool g_last_execution_has_sample = false;
bool g_last_execution_valid = false;
int32_t g_last_execution_temp_tenths = 0;
int32_t g_last_execution_threshold_tenths = 0;
int32_t g_last_execution_angle_degrees = 0;
uint32_t g_last_execution_ms = 0U;

bool g_aht20_online = false;
bool g_aht20_crc_ok = false;
bool g_aht20_has_sample = false;
float g_aht20_temp_c = 0.0f;
float g_aht20_humidity = 0.0f;
char g_aht20_diag[32] = "";
uint32_t g_aht20_last_sample_ms = 0U;
char g_i2c_diag[32] = "unknown";
uint8_t g_i2c_device_count = 0U;
uint8_t g_i2c_addresses[kI2cScanMaxDevices];
char g_i2c_labels[kI2cScanMaxDevices][24];
uint32_t g_i2c_last_scan_ms = 0U;
BoardPortState g_board_ports[kBoardPortCount];
BoardSampleState g_board_samples[kBoardSampleCount];

void publish_uart_line(char const * text);
void publish_usb_line(char const * text);
void copy_text(char * dest, size_t dest_size, char const * src);
void publish_wifi_status_usb();
void refresh_esp32_identity();
void load_device_identity();
void save_device_identity(char const * device_id, char const * device_secret);
void update_mqtt_topics();
void ensure_device_registration();
bool register_device_with_cloud();
void load_saved_wifi_credentials();
void save_wifi_credentials(char const * ssid, char const * password);
void clear_saved_wifi_credentials();
void begin_wifi_saved_credentials();
void process_usb_provisioning();
void handle_usb_provisioning_line(char const * line);
void handle_wifi_scan_usb();
void publish_status_lines_to_uart();
void publish_time_to_uart();
void ensure_time_sync();
void add_clock_payload(JsonObject payload);
bool begin_wifi_connection_by_ssid(char const * ssid);
void handle_wifi_scan_uart();
void clear_i2c_inventory();
void parse_i2c_inventory(char const * text);
bool i2c_inventory_contains(uint8_t address);
void add_platform_capability(JsonArray capabilities, char const * id, char const * status, char const * bus, char const * address_text, char const * type, char const * confidence, bool safe_for_automation);
void add_platform_device(JsonArray devices, JsonArray root_capabilities, uint8_t address, char const * type, char const * status);
void add_platform_aht20_fallback(JsonArray devices, JsonArray root_capabilities);
void add_platform_bus(JsonObject payload, bool include_root_capabilities);
void add_port_capability(JsonArray capabilities, char const * id, char const * unit, char const * access, char const * status);
void add_status_ports_fallback(JsonObject payload);
void add_telemetry_samples_fallback(JsonObject payload);
void add_status_ports(JsonObject payload);
void add_telemetry_samples(JsonObject payload);
char const * guess_i2c_module_class(char const * module_type);
char const * guess_i2c_model_state(char const * module_type);
char const * guess_i2c_activation(char const * module_type);
void build_device_key(char * dest, size_t dest_size, char const * port_id, char const * address_text, char const * module_type);
void reset_board_port(BoardPortState & port);
void reset_board_sample(BoardSampleState & sample);
void reset_board_state_cache();
BoardPortState * find_or_alloc_board_port(char const * port_id);
BoardSampleState * find_or_alloc_board_sample(char const * port_id, char const * capability);
void parse_port_capabilities(char const * text, BoardPortState * port);
void handle_port_line(char const * line);
void handle_sample_line(char const * line);
char const * current_wifi_ssid();
int find_wifi_profile_index(char const * ssid);
int pick_best_wifi_profile();
void begin_wifi_profile(int profile_index);
bool forward_manual_action(JsonObjectConst manual_action, char * display_text, size_t display_text_size);
bool forward_rule_program(JsonObjectConst rule_program, char * display_text, size_t display_text_size);
bool extract_threshold_rule(char const * lua_code, char * op_text, size_t op_text_size, int32_t * threshold_tenths);
bool extract_servo_angle(char const * lua_code, int32_t * angle_degrees);
bool extract_display_text(char const * lua_code, char * dest, size_t dest_size);

bool apply_deploy_message(JsonVariantConst envelope)
{
  JsonObjectConst manual_action;
  JsonObjectConst rule_program;
  char cmd_line[96];
  char text[48];
  char op_text[3];
  int32_t threshold_tenths = 0;
  int32_t servo_angle_degrees = 180;
  const char * request_id;
  const char * script_id;
  const char * intent_type;
  const char * lua_code;

  if (envelope.isNull())
  {
    return false;
  }

  request_id = envelope["request_id"] | "";
  script_id = envelope["payload"]["script_id"] | "";
  intent_type = envelope["payload"]["intent_type"] | "demo";
  lua_code = envelope["payload"]["lua_code"] | "";
  manual_action = envelope["payload"]["manual_action"].as<JsonObjectConst>();
  rule_program = envelope["payload"]["rule_program"].as<JsonObjectConst>();

  copy_text(g_last_request_id, sizeof(g_last_request_id), request_id);
  copy_text(g_last_script_id, sizeof(g_last_script_id), script_id);
  copy_text(g_last_intent_type, sizeof(g_last_intent_type), intent_type);
  copy_text(g_script_state, sizeof(g_script_state), "PENDING");

  snprintf(cmd_line, sizeof(cmd_line), "req:%s", g_last_request_id);
  publish_uart_line(cmd_line);
  snprintf(cmd_line, sizeof(cmd_line), "script:%s", g_last_script_id);
  publish_uart_line(cmd_line);

  if (!manual_action.isNull() && forward_manual_action(manual_action, text, sizeof(text)))
  {
    copy_text(g_last_display_text, sizeof(g_last_display_text), text);
    snprintf(cmd_line, sizeof(cmd_line), "cmd:%s", g_last_display_text);
    publish_uart_line(cmd_line);
  }
  else if (!rule_program.isNull() && forward_rule_program(rule_program, text, sizeof(text)))
  {
    copy_text(g_last_display_text, sizeof(g_last_display_text), text);
    snprintf(cmd_line, sizeof(cmd_line), "cmd:%s", g_last_display_text);
    publish_uart_line(cmd_line);
  }
  else if ((strcmp(g_last_intent_type, "threshold_control") == 0) && extract_threshold_rule(lua_code, op_text, sizeof(op_text), &threshold_tenths))
  {
    snprintf(cmd_line, sizeof(cmd_line), "rule:sensor=temp;op=%s;value=%ld", op_text, static_cast<long>(threshold_tenths));
    publish_uart_line(cmd_line);
    publish_uart_line("seq:clear");
    if (extract_servo_angle(lua_code, &servo_angle_degrees))
    {
      snprintf(cmd_line, sizeof(cmd_line), "servo:angle=%ld", static_cast<long>(servo_angle_degrees));
      publish_uart_line(cmd_line);
    }
    snprintf(text, sizeof(text), "T %s %ld.%ldC",
            op_text,
            static_cast<long>(threshold_tenths / 10),
            static_cast<long>(abs(static_cast<long>(threshold_tenths % 10))));
    copy_text(g_last_display_text, sizeof(g_last_display_text), text);
    snprintf(cmd_line, sizeof(cmd_line), "cmd:%s", g_last_display_text);
    publish_uart_line(cmd_line);
  }
  else if (extract_display_text(lua_code, text, sizeof(text)))
  {
    publish_uart_line("rule:clear");
    publish_uart_line("seq:clear");
    copy_text(g_last_display_text, sizeof(g_last_display_text), text);
    snprintf(cmd_line, sizeof(cmd_line), "cmd:%s", g_last_display_text);
    publish_uart_line(cmd_line);
  }
  else
  {
    publish_uart_line("rule:clear");
    publish_uart_line("seq:clear");
    g_last_display_text[0] = '\0';
  }

  snprintf(cmd_line, sizeof(cmd_line), "intent:%s", g_last_intent_type);
  publish_uart_line(cmd_line);
  g_status_dirty = true;
  return true;
}

bool forward_manual_action(JsonObjectConst manual_action, char * text, size_t text_size)
{
  JsonObjectConst target;
  JsonArrayConst actions;
  const char * device;
  const char * capability;
  char cmd_line[96];
  size_t action_count = 0U;

  if ((text == nullptr) || (text_size == 0U))
  {
    return false;
  }

  target = manual_action["target"];
  actions = manual_action["actions"].as<JsonArrayConst>();
  device = target["device"] | "";
  capability = target["capability"] | "";
  if ((strcmp(device, "SG90") != 0) || (strcmp(capability, "servo.sweep") != 0) || actions.isNull() || (actions.size() == 0U))
  {
    return false;
  }

  publish_uart_line("rule:clear");
  publish_uart_line("seq:clear");

  for (JsonObjectConst action : actions)
  {
    const char * action_device = action["device"] | "";
    const char * method = action["method"] | "";
    int angle = action["params"]["angle"] | 90;
    int duration_ms = action["params"]["duration_ms"] | 350;

    if ((strcmp(action_device, "SG90") != 0) || (strcmp(method, "servo_set") != 0))
    {
      return false;
    }
    if (angle < 0)
    {
      angle = 0;
    }
    if (angle > 180)
    {
      angle = 180;
    }
    if (duration_ms < 50)
    {
      duration_ms = 50;
    }
    if (duration_ms > 5000)
    {
      duration_ms = 5000;
    }

    snprintf(cmd_line, sizeof(cmd_line), "seq:add;angle=%d;ms=%d", angle, duration_ms);
    publish_uart_line(cmd_line);
    action_count++;
  }

  if (action_count == 0U)
  {
    return false;
  }

  publish_uart_line("manual:start;device=SG90;method=servo_sweep");
  snprintf(text, text_size, "SG90 sweep %u steps", static_cast<unsigned int>(action_count));
  return true;
}

void publish_input_status(char const * text)
{
  char line[80];

  if ((nullptr == text) || ('\0' == text[0]))
  {
    return;
  }

  snprintf(line, sizeof(line), "input:%s", text);
  publish_uart_line(line);
}

bool submit_nl_to_cloud(char const * text)
{
  StaticJsonDocument<384> request_doc;
  DynamicJsonDocument response_doc(3072);
  HTTPClient http;
  String request_body;
  String response_text;
  String request_id;
  int status_code = 0;
  DeserializationError json_error;

  if ((nullptr == text) || ('\0' == text[0]))
  {
    publish_input_status("empty");
    return false;
  }

  if (WiFi.status() != WL_CONNECTED)
  {
    publish_input_status("wifi down");
    return false;
  }

  request_id = String("nl_") + String(static_cast<unsigned long>(millis()));
  request_doc["request_id"] = request_id;
  request_doc["text"] = text;
  request_doc["device_id"] = g_device_id;
  request_doc["session_id"] = nullptr;
  request_doc["need_confirm"] = true;
  request_doc["wait_for_ack"] = false;
  request_doc["preview_only"] = false;
  serializeJson(request_doc, request_body);

  publish_input_status("send cloud");

  http.setTimeout(15000);
  http.begin(kCloudHermesChatUrl);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Token", kCloudApiToken);
  status_code = http.POST(request_body);
  response_text = http.getString();
  http.end();

  if (status_code != HTTP_CODE_OK)
  {
    if (status_code == HTTP_CODE_UNAUTHORIZED)
    {
      publish_input_status("api 401");
    }
    else if (status_code == HTTP_CODE_UNPROCESSABLE_ENTITY)
    {
      publish_input_status("rule 422");
    }
    else
    {
      publish_input_status("http fail");
    }

    if (!response_text.isEmpty())
    {
      publish_usb_line(response_text.c_str());
    }

    g_fault_until_ms = millis() + kFaultHoldMs;
    return false;
  }

  json_error = deserializeJson(response_doc, response_text);
  if (json_error)
  {
    publish_input_status("json fail");
    publish_usb_line(response_text.c_str());
    return false;
  }

  if (!apply_deploy_message(response_doc["mqtt_message"]))
  {
    copy_text(g_last_request_id, sizeof(g_last_request_id), response_doc["request_id"] | request_id.c_str());
    copy_text(g_last_intent_type, sizeof(g_last_intent_type), response_doc["action_kind"] | "none");
    copy_text(g_script_state, sizeof(g_script_state), response_doc["delivery_stage"] | response_doc["status"] | "answered");
    g_status_dirty = true;
  }

  publish_input_status("cloud ok");
  return true;
}

void init_status_led()
{
#ifdef RGB_BUILTIN
  pinMode(RGB_BUILTIN, OUTPUT);
#elif defined(LED_BUILTIN)
  pinMode(LED_BUILTIN, OUTPUT);
#endif
}

void set_status_led(uint8_t red, uint8_t green, uint8_t blue)
{
#ifdef RGB_BUILTIN
  neopixelWrite(RGB_BUILTIN, red, green, blue);
#elif defined(LED_BUILTIN)
  digitalWrite(LED_BUILTIN, (red || green || blue) ? HIGH : LOW);
#else
  (void) red;
  (void) green;
  (void) blue;
#endif
}

void update_status_led()
{
  uint32_t now = millis();

  if (g_fault_until_ms > now)
  {
    set_status_led(((now / kFaultBlinkIntervalMs) % 2U) == 0U ? 32 : 0, 0, 0);
    return;
  }

  if (g_tx_flash_until_ms > now)
  {
    set_status_led(0, 32, 0);
    return;
  }

  if (g_rx_flash_until_ms > now)
  {
    set_status_led(32, 16, 0);
    return;
  }

  if (g_mqtt_connected)
  {
    set_status_led(0, 24, 0);
    return;
  }

  if (g_wifi_connected)
  {
    set_status_led(0, 24, 12);
    return;
  }

  if ((g_last_rx_ms > 0U) && ((now - g_last_rx_ms) <= kLinkActiveTimeoutMs))
  {
    set_status_led(0, 0, 24);
    return;
  }

  set_status_led(((now / kWaitBlinkIntervalMs) % 2U) == 0U ? 0 : 0, 0, ((now / kWaitBlinkIntervalMs) % 2U) == 0U ? 24 : 0);
}

void publish_uart_line(char const * text)
{
  if (nullptr == text)
  {
    return;
  }

  kLinkUart.print(text);
  kLinkUart.print("\r\n");
  g_tx_flash_until_ms = millis() + kEventFlashMs;
}

void publish_usb_line(char const * text)
{
  if (nullptr == text)
  {
    return;
  }

  Serial.print(text);
  Serial.print("\r\n");
}

void publish_wifi_status_usb()
{
  StaticJsonDocument<512> doc;
  doc["type"] = "wifi.status";
  doc["device_id"] = g_device_id;
  doc["ra8p1_uid"] = g_ra8p1_uid;
  doc["esp32_mac"] = g_esp32_mac;
  doc["registered"] = g_device_registered;
  doc["wifi"] = (WiFi.status() == WL_CONNECTED) ? "connected" : "disconnected";
  doc["mqtt"] = g_mqtt_connected ? "connected" : "disconnected";
  doc["ssid"] = current_wifi_ssid();
  doc["saved_ssid"] = g_saved_wifi_available ? g_saved_wifi_ssid : "";
  doc["ip"] = (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString() : "";
  serializeJson(doc, Serial);
  Serial.print("\r\n");
}

void update_mqtt_topics()
{
  snprintf(g_status_topic, sizeof(g_status_topic), "cloudbridge/%s/status", g_device_id);
  snprintf(g_telemetry_topic, sizeof(g_telemetry_topic), "cloudbridge/%s/telemetry", g_device_id);
  snprintf(g_event_topic, sizeof(g_event_topic), "cloudbridge/%s/event", g_device_id);
  snprintf(g_script_topic, sizeof(g_script_topic), "cloudbridge/%s/script", g_device_id);
}

void refresh_esp32_identity()
{
  String mac = WiFi.macAddress();
  uint64_t efuse_mac = ESP.getEfuseMac();

  mac.toCharArray(g_esp32_mac, sizeof(g_esp32_mac));
  snprintf(g_esp32_chip_id, sizeof(g_esp32_chip_id), "%04X%08X",
           static_cast<unsigned int>((efuse_mac >> 32) & 0xFFFFU),
           static_cast<unsigned int>(efuse_mac & 0xFFFFFFFFU));
}

void load_device_identity()
{
  String saved_device_id = g_wifi_preferences.getString("device_id", "");
  String saved_secret = g_wifi_preferences.getString("device_secret", "");

  refresh_esp32_identity();

  if (!saved_device_id.isEmpty() && !saved_device_id.equals(kDefaultDeviceId))
  {
    saved_device_id.toCharArray(g_device_id, sizeof(g_device_id));
    g_device_registered = true;
  }
  else
  {
    if (saved_device_id.equals(kDefaultDeviceId))
    {
      g_wifi_preferences.remove("device_id");
    }
    copy_text(g_device_id, sizeof(g_device_id), kDefaultDeviceId);
    g_device_registered = false;
  }

  saved_secret.toCharArray(g_device_secret, sizeof(g_device_secret));
  update_mqtt_topics();
}

void save_device_identity(char const * device_id, char const * device_secret)
{
  if ((device_id == nullptr) || (device_id[0] == '\0'))
  {
    return;
  }

  if (0 != strcmp(g_device_id, device_id))
  {
    if (g_mqtt.connected())
    {
      g_mqtt.disconnect();
    }
    g_mqtt_connected = false;
  }

  copy_text(g_device_id, sizeof(g_device_id), device_id);
  copy_text(g_device_secret, sizeof(g_device_secret), device_secret);
  g_wifi_preferences.putString("device_id", g_device_id);
  if (g_device_secret[0] != '\0')
  {
    g_wifi_preferences.putString("device_secret", g_device_secret);
  }
  g_device_registered = true;
  update_mqtt_topics();
  g_status_dirty = true;
}

bool register_device_with_cloud()
{
  StaticJsonDocument<384> request_doc;
  DynamicJsonDocument response_doc(2048);
  HTTPClient http;
  String request_body;
  String response_text;
  int status_code;
  DeserializationError json_error;
  const char * device_id;
  const char * device_secret;

  if (WiFi.status() != WL_CONNECTED)
  {
    return false;
  }

  refresh_esp32_identity();
  request_doc["ra8p1_uid"] = g_ra8p1_uid;
  request_doc["esp32_mac"] = g_esp32_mac;
  request_doc["esp32_chip_id"] = g_esp32_chip_id;
  request_doc["label"] = "RA8P1 field device";
  request_doc["bootstrap_secret"] = kCloudDeviceRegistrationSecret;
  serializeJson(request_doc, request_body);

  http.setTimeout(8000);
  http.begin(kCloudDeviceRegisterUrl);
  http.addHeader("Content-Type", "application/json");
  status_code = http.POST(request_body);
  response_text = http.getString();
  http.end();

  if ((status_code < 200) || (status_code >= 300))
  {
    publish_input_status("register fail");
    if (!response_text.isEmpty())
    {
      publish_usb_line(response_text.c_str());
    }
    return false;
  }

  json_error = deserializeJson(response_doc, response_text);
  if (json_error)
  {
    publish_input_status("register json");
    return false;
  }

  device_id = response_doc["device_id"] | "";
  device_secret = response_doc["device_secret"] | "";
  if (device_id[0] == '\0')
  {
    device_id = response_doc["device"]["device_id"] | "";
  }
  if (device_secret[0] == '\0')
  {
    device_secret = response_doc["device"]["device_secret"] | "";
  }
  if (device_id[0] == '\0')
  {
    publish_input_status("register no id");
    return false;
  }
  if (0 == strcmp(device_id, kDefaultDeviceId))
  {
    publish_input_status("register default id");
    return false;
  }

  save_device_identity(device_id, device_secret);
  char line[96];
  snprintf(line, sizeof(line), "register id=%s", g_device_id);
  publish_usb_line(line);
  publish_wifi_status_usb();
  publish_input_status("registered");
  return true;
}

void ensure_device_registration()
{
  static uint32_t last_attempt_ms = 0U;
  uint32_t now = millis();

  if (g_device_registered)
  {
    if (0 != strcmp(g_device_id, kDefaultDeviceId))
    {
      return;
    }
    g_device_registered = false;
  }
  if (g_ra8p1_uid[0] == '\0')
  {
    return;
  }
  if ((now - last_attempt_ms) < 15000U)
  {
    return;
  }

  last_attempt_ms = now;
  (void) register_device_with_cloud();
}

void load_saved_wifi_credentials()
{
  String ssid = g_wifi_preferences.getString("ssid", "");
  String password = g_wifi_preferences.getString("password", "");

  g_saved_wifi_available = !ssid.isEmpty();
  if (g_saved_wifi_available)
  {
    ssid.toCharArray(g_saved_wifi_ssid, sizeof(g_saved_wifi_ssid));
    password.toCharArray(g_saved_wifi_password, sizeof(g_saved_wifi_password));
  }
  else
  {
    g_saved_wifi_ssid[0] = '\0';
    g_saved_wifi_password[0] = '\0';
  }
}

void save_wifi_credentials(char const * ssid, char const * password)
{
  copy_text(g_saved_wifi_ssid, sizeof(g_saved_wifi_ssid), ssid);
  copy_text(g_saved_wifi_password, sizeof(g_saved_wifi_password), password);
  g_saved_wifi_available = (g_saved_wifi_ssid[0] != '\0');
  if (g_saved_wifi_available)
  {
    g_wifi_preferences.putString("ssid", g_saved_wifi_ssid);
    g_wifi_preferences.putString("password", g_saved_wifi_password);
  }
}

void clear_saved_wifi_credentials()
{
  g_wifi_preferences.remove("ssid");
  g_wifi_preferences.remove("password");
  g_saved_wifi_ssid[0] = '\0';
  g_saved_wifi_password[0] = '\0';
  g_saved_wifi_available = false;
}

void begin_wifi_saved_credentials()
{
  if (!g_saved_wifi_available)
  {
    return;
  }

  publish_usb_line("wifi profile:saved");
  WiFi.begin(g_saved_wifi_ssid, g_saved_wifi_password);
}

void copy_text(char * dest, size_t dest_size, char const * src)
{
  if ((nullptr == dest) || (0U == dest_size))
  {
    return;
  }

  if (nullptr == src)
  {
    dest[0] = '\0';
    return;
  }

  strncpy(dest, src, dest_size - 1U);
  dest[dest_size - 1U] = '\0';
}

void clear_i2c_inventory()
{
  g_i2c_device_count = 0U;
  for (size_t i = 0U; i < kI2cScanMaxDevices; i++)
  {
    g_i2c_addresses[i] = 0U;
    g_i2c_labels[i][0] = '\0';
  }
}

void parse_i2c_inventory(char const * text)
{
  char entry[40];
  char * label_start;
  char * end_ptr;
  char const * cursor = text;

  clear_i2c_inventory();
  if ((cursor == nullptr) || (cursor[0] == '\0') || (0 == strcmp(cursor, "-")) || (0 == strcmp(cursor, "none")))
  {
    return;
  }

  while ((cursor[0] != '\0') && (g_i2c_device_count < kI2cScanMaxDevices))
  {
    char const * comma = strchr(cursor, ',');
    size_t entry_len = (comma == nullptr) ? strlen(cursor) : static_cast<size_t>(comma - cursor);

    if (entry_len >= sizeof(entry))
    {
      entry_len = sizeof(entry) - 1U;
    }
    memcpy(entry, cursor, entry_len);
    entry[entry_len] = '\0';

    label_start = strchr(entry, '/');
    if (label_start != nullptr)
    {
      *label_start = '\0';
      label_start += 1;
    }
    else
    {
      label_start = entry;
    }

    g_i2c_addresses[g_i2c_device_count] = static_cast<uint8_t>(strtol(entry, &end_ptr, 0));
    if ((end_ptr == entry) || ((*end_ptr != '\0') && (*end_ptr != '/')))
    {
      g_i2c_addresses[g_i2c_device_count] = 0U;
    }
    copy_text(g_i2c_labels[g_i2c_device_count], sizeof(g_i2c_labels[g_i2c_device_count]), label_start);
    g_i2c_device_count++;

    if (comma == nullptr)
    {
      break;
    }
    cursor = comma + 1;
  }
}

bool i2c_inventory_contains(uint8_t address)
{
  for (size_t i = 0U; i < g_i2c_device_count; i++)
  {
    if (g_i2c_addresses[i] == address)
    {
      return true;
    }
  }

  return false;
}

void add_platform_capability(JsonArray capabilities, char const * id, char const * status, char const * bus, char const * address_text, char const * type, char const * confidence, bool safe_for_automation)
{
  JsonObject capability = capabilities.createNestedObject();
  JsonObject source = capability.createNestedObject("source");

  capability["id"] = id;
  capability["status"] = status;
  capability["confidence"] = confidence;
  capability["safe_for_automation"] = safe_for_automation;
  source["bus"] = bus;
  source["address"] = address_text;
  source["type"] = type;
}

void add_capability_list(JsonArray device_capabilities, JsonArray root_capabilities, char const * capability_id, char const * status, char const * address_text, char const * type, char const * confidence, bool safe_for_automation)
{
  device_capabilities.add(capability_id);
  if (!root_capabilities.isNull())
  {
    add_platform_capability(root_capabilities, capability_id, status, "i2c.s1", address_text, type, confidence, safe_for_automation);
  }
}

void add_platform_device(JsonArray devices, JsonArray root_capabilities, uint8_t address, char const * type, char const * status)
{
  char address_text[8];
  char const * category = "unknown";
  char const * driver = "";
  char const * confidence = "unknown";
  bool safe_for_automation = false;
  JsonObject device = devices.createNestedObject();
  JsonArray capabilities;

  snprintf(address_text, sizeof(address_text), "0x%02X", address);
  if (type == nullptr)
  {
    type = "unknown";
  }
  if (status == nullptr)
  {
    status = "present";
  }

  if ((0 == strcmp(type, "AHT20")) || (0 == strcmp(type, "BH1750")))
  {
    category = "env_sensor";
    driver = (0 == strcmp(type, "BH1750")) ? "bh1750" : "aht20";
    confidence = "exact";
    safe_for_automation = (0 == strcmp(status, "online")) || (0 == strcmp(status, "present"));
  }
  else if (0 == strcmp(type, "9548A-MUX"))
  {
    category = "i2c_mux";
    driver = "pca9548a";
    confidence = "class";
  }
  else if ((0 == strcmp(type, "OLED-class")) || (address == 0x3CU) || (address == 0x3DU))
  {
    category = "display";
    driver = "ssd1306";
    confidence = "class";
  }
  else if ((0 == strcmp(type, "ENV-class")) || (address == 0x76U) || (address == 0x77U))
  {
    category = "env_sensor";
    driver = "env-class";
    confidence = "class";
  }
  else if ((0 == strcmp(type, "IMU-RTC-class")) || (address == 0x68U) || (address == 0x69U))
  {
    category = "motion_or_time";
    driver = "imu-rtc-class";
    confidence = "class";
  }
  else if ((0 == strcmp(type, "EEPROM-class")) || (address == 0x57U))
  {
    category = "storage";
    driver = "eeprom-class";
    confidence = "class";
  }

  device["bus"] = "i2c.s1";
  device["address"] = address_text;
  device["type"] = type;
  device["category"] = category;
  device["driver"] = driver;
  device["confidence"] = confidence;
  device["status"] = status;
  device["safe_for_automation"] = safe_for_automation;
  capabilities = device.createNestedArray("capabilities");

  if (0 == strcmp(type, "AHT20"))
  {
    add_capability_list(capabilities, root_capabilities, "env.temperature", status, address_text, type, confidence, safe_for_automation);
    add_capability_list(capabilities, root_capabilities, "env.humidity", status, address_text, type, confidence, safe_for_automation);
  }
  else if (0 == strcmp(type, "BH1750"))
  {
    add_capability_list(capabilities, root_capabilities, "env.light.lux", status, address_text, type, confidence, safe_for_automation);
  }
  else if (0 == strcmp(category, "env_sensor"))
  {
    add_capability_list(capabilities, root_capabilities, "env.temperature", status, address_text, type, confidence, false);
    add_capability_list(capabilities, root_capabilities, "env.humidity", status, address_text, type, confidence, false);
    add_capability_list(capabilities, root_capabilities, "env.pressure", status, address_text, type, confidence, false);
  }
  else if (0 == strcmp(category, "display"))
  {
    add_capability_list(capabilities, root_capabilities, "display.text", status, address_text, type, confidence, false);
    add_capability_list(capabilities, root_capabilities, "display.bitmap", status, address_text, type, confidence, false);
  }
  else if (0 == strcmp(category, "motion_or_time"))
  {
    add_capability_list(capabilities, root_capabilities, "imu.accel", status, address_text, type, confidence, false);
    add_capability_list(capabilities, root_capabilities, "imu.gyro", status, address_text, type, confidence, false);
    add_capability_list(capabilities, root_capabilities, "rtc.time", status, address_text, type, confidence, false);
  }
}

void add_platform_aht20_fallback(JsonArray devices, JsonArray root_capabilities)
{
  add_platform_device(devices, root_capabilities, 0x38U, "AHT20", g_aht20_online ? "online" : "offline");
}

void add_platform_bus(JsonObject payload, bool include_root_capabilities)
{
  JsonArray buses = payload.createNestedArray("buses");
  JsonObject bus = buses.createNestedObject();
  JsonArray devices = bus.createNestedArray("devices");
  JsonArray root_capabilities;

  payload["platform_protocol"] = "cloudbridge.v2";
  if (include_root_capabilities)
  {
    root_capabilities = payload.createNestedArray("capabilities");
  }

  bus["id"] = "i2c.s1";
  bus["type"] = "i2c";
  bus["diag"] = g_i2c_diag;
  bus["count"] = g_i2c_device_count;

  for (size_t i = 0U; i < g_i2c_device_count; i++)
  {
    add_platform_device(devices, root_capabilities, g_i2c_addresses[i], g_i2c_labels[i], "present");
  }

  if (!i2c_inventory_contains(0x38U))
  {
    add_platform_aht20_fallback(devices, root_capabilities);
  }
}

void add_port_capability(JsonArray capabilities, char const * id, char const * unit, char const * access, char const * status)
{
  JsonObject capability = capabilities.createNestedObject();
  capability["id"] = id;
  capability["unit"] = unit;
  capability["access"] = access;
  capability["status"] = status;
}

char const * guess_i2c_module_class(char const * module_type)
{
  if (module_type == nullptr)
  {
    return "unknown";
  }

  if ((0 == strcmp(module_type, "AHT20")) || (0 == strcmp(module_type, "0x38-class")))
  {
    return "env.th";
  }
  if (0 == strcmp(module_type, "BH1750"))
  {
    return "env.light";
  }
  if (0 == strcmp(module_type, "9548A-MUX"))
  {
    return "i2c.mux";
  }
  if (0 == strcmp(module_type, "ENV-class"))
  {
    return "env.multi";
  }
  if (0 == strcmp(module_type, "OLED-class"))
  {
    return "display.i2c";
  }
  if (0 == strcmp(module_type, "EEPROM-class"))
  {
    return "storage.eeprom";
  }
  if (0 == strcmp(module_type, "IMU-RTC-class"))
  {
    return "motion_time";
  }

  return "unknown";
}

char const * guess_i2c_model_state(char const * module_type)
{
  if (module_type == nullptr)
  {
    return "unknown";
  }

  if (0 == strcmp(module_type, "AHT20"))
  {
    return "exact";
  }
  if ((0 == strcmp(module_type, "BH1750")) || (0 == strcmp(module_type, "9548A-MUX")))
  {
    return "candidate";
  }
  if (strstr(module_type, "-class") != nullptr)
  {
    return "candidate";
  }
  if (strstr(module_type, "I2C-0x") == module_type)
  {
    return "unknown";
  }

  return "candidate";
}

char const * guess_i2c_activation(char const * module_type)
{
  if (module_type == nullptr)
  {
    return "inactive";
  }

  if (0 == strcmp(module_type, "AHT20"))
  {
    return "confirmed";
  }
  if ((0 == strcmp(module_type, "BH1750")) || (0 == strcmp(module_type, "9548A-MUX")))
  {
    return "channel_active";
  }

  return "channel_active";
}

void build_device_key(char * dest, size_t dest_size, char const * port_id, char const * address_text, char const * module_type)
{
  if ((dest == nullptr) || (dest_size == 0U))
  {
    return;
  }

  snprintf(dest,
           dest_size,
           "%s:%s:%s",
           ((port_id != nullptr) && (port_id[0] != '\0')) ? port_id : "-",
           ((address_text != nullptr) && (address_text[0] != '\0')) ? address_text : "-",
           ((module_type != nullptr) && (module_type[0] != '\0')) ? module_type : "-");
}

void reset_board_port(BoardPortState & port)
{
  memset(&port, 0, sizeof(port));
}

void reset_board_sample(BoardSampleState & sample)
{
  memset(&sample, 0, sizeof(sample));
}

void reset_board_state_cache()
{
  for (size_t i = 0U; i < kBoardPortCount; i++)
  {
    reset_board_port(g_board_ports[i]);
  }
  for (size_t i = 0U; i < kBoardSampleCount; i++)
  {
    reset_board_sample(g_board_samples[i]);
  }
}

BoardPortState * find_or_alloc_board_port(char const * port_id)
{
  size_t free_index = kBoardPortCount;

  if ((port_id == nullptr) || (port_id[0] == '\0'))
  {
    return nullptr;
  }

  for (size_t i = 0U; i < kBoardPortCount; i++)
  {
    if (g_board_ports[i].valid && (0 == strcmp(g_board_ports[i].port_id, port_id)))
    {
      return &g_board_ports[i];
    }
    if ((!g_board_ports[i].valid) && (free_index == kBoardPortCount))
    {
      free_index = i;
    }
  }

  if (free_index >= kBoardPortCount)
  {
    return nullptr;
  }

  reset_board_port(g_board_ports[free_index]);
  g_board_ports[free_index].valid = true;
  copy_text(g_board_ports[free_index].port_id, sizeof(g_board_ports[free_index].port_id), port_id);
  return &g_board_ports[free_index];
}

BoardSampleState * find_or_alloc_board_sample(char const * port_id, char const * capability)
{
  size_t free_index = kBoardSampleCount;

  if ((port_id == nullptr) || (capability == nullptr) || (port_id[0] == '\0') || (capability[0] == '\0'))
  {
    return nullptr;
  }

  for (size_t i = 0U; i < kBoardSampleCount; i++)
  {
    if (g_board_samples[i].valid
        && (0 == strcmp(g_board_samples[i].port_id, port_id))
        && (0 == strcmp(g_board_samples[i].capability, capability)))
    {
      return &g_board_samples[i];
    }
    if ((!g_board_samples[i].valid) && (free_index == kBoardSampleCount))
    {
      free_index = i;
    }
  }

  if (free_index >= kBoardSampleCount)
  {
    return nullptr;
  }

  reset_board_sample(g_board_samples[free_index]);
  g_board_samples[free_index].valid = true;
  copy_text(g_board_samples[free_index].port_id, sizeof(g_board_samples[free_index].port_id), port_id);
  copy_text(g_board_samples[free_index].capability, sizeof(g_board_samples[free_index].capability), capability);
  return &g_board_samples[free_index];
}

void parse_port_capabilities(char const * text, BoardPortState * port)
{
  char local[192];
  char * context = nullptr;
  char * item;

  if ((text == nullptr) || (port == nullptr))
  {
    return;
  }

  port->capability_count = 0U;
  if (text[0] == '\0')
  {
    return;
  }

  copy_text(local, sizeof(local), text);
  item = strtok_r(local, ",", &context);
  while ((item != nullptr) && (port->capability_count < kPortCapabilityMax))
  {
    CapabilityState & capability = port->capabilities[port->capability_count];
    char * field_context = nullptr;
    char * id = strtok_r(item, "|", &field_context);
    char * unit = strtok_r(nullptr, "|", &field_context);
    char * access = strtok_r(nullptr, "|", &field_context);
    char * status = strtok_r(nullptr, "|", &field_context);

    memset(&capability, 0, sizeof(capability));
    capability.valid = (id != nullptr) && (id[0] != '\0');
    if (capability.valid)
    {
      copy_text(capability.id, sizeof(capability.id), id);
      copy_text(capability.unit, sizeof(capability.unit), (unit == nullptr) ? "" : unit);
      copy_text(capability.access, sizeof(capability.access), (access == nullptr) ? "" : access);
      copy_text(capability.status, sizeof(capability.status), (status == nullptr) ? "" : status);
      port->capability_count++;
    }
    item = strtok_r(nullptr, ",", &context);
  }
}

void add_status_ports_fallback(JsonObject payload)
{
  JsonArray ports = payload.createNestedArray("ports");
  JsonObject port;
  JsonObject module;
  JsonArray capabilities;
  char address_text[8];
  char const * i2c_status = "empty";
  char const * i2c_diag = g_i2c_diag;
  char const * i2c_activation = "inactive";
  char const * i2c_module_type = "none";
  char const * i2c_module_id = "none";
  char const * i2c_module_class = "none";
  char const * i2c_driver = "";
  char const * i2c_model_state = "none";
  char const * i2c_binding_source = "none";
  char const * i2c_confidence = "unknown";
  char device_key[48];
  uint8_t i2c_address = 0U;

  if (g_aht20_online)
  {
    i2c_activation = "confirmed";
    i2c_status = "online";
    i2c_module_type = "AHT20";
    i2c_module_id = "aht20";
    i2c_module_class = "env.th";
    i2c_driver = "aht20";
    i2c_model_state = "exact";
    i2c_binding_source = "auto_exact";
    i2c_confidence = "exact";
    i2c_address = 0x38U;
  }
  else if (g_i2c_device_count > 0U)
  {
    bool is_exact_aht20 = (0 == strcmp(g_i2c_labels[0], "AHT20"));
    bool is_class_candidate = (strstr(g_i2c_labels[0], "-class") != nullptr);

    i2c_activation = guess_i2c_activation(g_i2c_labels[0]);
    i2c_status = "online";
    i2c_module_type = g_i2c_labels[0];
    i2c_module_id = "i2c-s1-device";
    i2c_module_class = guess_i2c_module_class(g_i2c_labels[0]);
    i2c_driver = g_i2c_labels[0];
    i2c_model_state = guess_i2c_model_state(g_i2c_labels[0]);
    i2c_binding_source = is_exact_aht20 ? "auto_exact" : "auto_detected";
    i2c_confidence = is_exact_aht20 ? "exact" : (is_class_candidate ? "class" : "unknown");
    i2c_address = g_i2c_addresses[0];
  }
  else if ((0 != strcmp(g_i2c_diag, "ok")) && (0 != strcmp(g_i2c_diag, "unknown")))
  {
    i2c_status = "error";
  }

  port = ports.createNestedObject();
  port["port_id"] = "i2c.s1";
  port["physical_port"] = "I2C-1";
  port["channel"] = "Bus S1";
  port["type"] = "i2c";
  port["activation"] = i2c_activation;
  port["status"] = i2c_status;
  port["diag"] = i2c_diag;
  port["last_sample_ms"] = (g_aht20_last_sample_ms > 0U) ? g_aht20_last_sample_ms : g_i2c_last_scan_ms;
  module = port.createNestedObject("module");
  module["module_id"] = i2c_module_id;
  module["module_type"] = i2c_module_type;
  module["module_class"] = i2c_module_class;
  module["driver"] = i2c_driver;
  module["model_state"] = i2c_model_state;
  module["binding_source"] = i2c_binding_source;
  if (i2c_address > 0U)
  {
    snprintf(address_text, sizeof(address_text), "0x%02X", i2c_address);
    module["address"] = address_text;
  }
  module["confidence"] = i2c_confidence;
  build_device_key(device_key,
                   sizeof(device_key),
                   "i2c.s1",
                   (i2c_address > 0U) ? address_text : "",
                   i2c_module_type);
  module["device_key"] = device_key;
  capabilities = port.createNestedArray("capabilities");
  if (0 == strcmp(i2c_module_type, "AHT20"))
  {
    add_port_capability(capabilities, "env.temperature", "C", "read", g_aht20_online ? "online" : "offline");
    add_port_capability(capabilities, "env.humidity", "%RH", "read", g_aht20_online ? "online" : "offline");
  }

  port = ports.createNestedObject();
  port["port_id"] = "i2c.s2";
  port["physical_port"] = "I2C-2";
  port["channel"] = "Bus S2";
  port["type"] = "i2c";
  port["activation"] = "reserved";
  port["status"] = "empty";
  port["diag"] = "not_supported";
  port["last_sample_ms"] = 0U;
  module = port.createNestedObject("module");
  module["module_id"] = "reserved";
  module["module_type"] = "reserved";
  module["module_class"] = "reserved";
  module["driver"] = "";
  module["model_state"] = "reserved";
  module["binding_source"] = "reserved";
  module["confidence"] = "reserved";
  module["device_key"] = "i2c.s2:-:reserved";
  capabilities = port.createNestedArray("capabilities");

  port = ports.createNestedObject();
  port["port_id"] = "pwm.0";
  port["physical_port"] = "PWM-0";
  port["channel"] = "P105";
  port["type"] = "pwm";
  port["activation"] = "confirmed";
  port["status"] = g_last_execution_valid ? "online" : "configured";
  port["diag"] = "no_feedback_open_loop";
  port["last_sample_ms"] = g_last_execution_ms;
  module = port.createNestedObject("module");
  module["module_id"] = "sg90";
  module["module_type"] = "SG90";
  module["module_class"] = "act.servo";
  module["driver"] = "sg90_servo";
  module["model_state"] = "exact";
  module["binding_source"] = "user_confirmed";
  module["confidence"] = "user_confirmed";
  module["device_key"] = "pwm.0:-:SG90";
  capabilities = port.createNestedArray("capabilities");
  add_port_capability(capabilities, "motor.servo.angle", "degree", "write", g_last_execution_valid ? "execution_feedback" : "configured");
  add_port_capability(capabilities, "buzzer.active", "-", "write", g_last_execution_valid ? "execution_feedback" : "configured");

  port = ports.createNestedObject();
  port["port_id"] = "uart.bridge";
  port["physical_port"] = "UART-BRIDGE";
  port["channel"] = "UART0";
  port["type"] = "uart";
  port["activation"] = "confirmed";
  port["status"] = g_uart_online ? "online" : "offline";
  port["diag"] = g_uart_online ? "ok" : "waiting";
  port["last_sample_ms"] = g_last_rx_ms;
  module = port.createNestedObject("module");
  module["module_id"] = "esp32_bridge";
  module["module_type"] = "ESP32-S3";
  module["module_class"] = "bridge.uart";
  module["driver"] = "esp32_uart_link";
  module["model_state"] = "exact";
  module["binding_source"] = "system_fixed";
  module["confidence"] = "exact";
  module["device_key"] = "uart.bridge:-:ESP32-S3";
  capabilities = port.createNestedArray("capabilities");
  add_port_capability(capabilities, "bridge.uart.mqtt", "-", "readwrite", g_mqtt_connected ? "online" : "degraded");
}

void add_status_ports(JsonObject payload)
{
  bool has_board_ports = false;

  for (size_t i = 0U; i < kBoardPortCount; i++)
  {
    if (g_board_ports[i].valid)
    {
      has_board_ports = true;
      break;
    }
  }

  if (!has_board_ports)
  {
    add_status_ports_fallback(payload);
    return;
  }

  JsonArray ports = payload.createNestedArray("ports");
  for (size_t i = 0U; i < kBoardPortCount; i++)
  {
    JsonObject port_object;
    JsonObject module;
    JsonArray capabilities;
    BoardPortState const & port = g_board_ports[i];

    if (!port.valid)
    {
      continue;
    }

    port_object = ports.createNestedObject();
    port_object["port_id"] = port.port_id;
    port_object["physical_port"] = port.physical_port;
    port_object["channel"] = port.channel;
    port_object["type"] = port.type;
    port_object["activation"] = port.activation;
    port_object["status"] = port.status;
    port_object["diag"] = port.diag;
    port_object["last_sample_ms"] = port.last_sample_ms;

    module = port_object.createNestedObject("module");
    module["module_id"] = port.module_id;
    module["module_type"] = port.module_type;
    module["module_class"] = port.module_class;
    module["driver"] = port.driver;
    module["model_state"] = port.model_state;
    module["binding_source"] = port.binding_source;
    module["confidence"] = port.confidence;
    if (port.address[0] != '\0')
    {
      module["address"] = port.address;
    }
    if (port.device_key[0] != '\0')
    {
      module["device_key"] = port.device_key;
    }

    capabilities = port_object.createNestedArray("capabilities");
    for (size_t capability_index = 0U; capability_index < port.capability_count; capability_index++)
    {
      CapabilityState const & capability = port.capabilities[capability_index];
      if (!capability.valid)
      {
        continue;
      }
      add_port_capability(capabilities, capability.id, capability.unit, capability.access, capability.status);
    }
  }
}

void add_telemetry_samples_fallback(JsonObject payload)
{
  JsonArray samples = payload.createNestedArray("samples");
  JsonObject sample;

  if (g_aht20_has_sample)
  {
    sample = samples.createNestedObject();
    sample["port_id"] = "i2c.s1";
    sample["module_type"] = "AHT20";
    sample["capability"] = "env.temperature";
    sample["value"] = g_aht20_temp_c;
    sample["unit"] = "C";
    sample["ts_ms"] = g_aht20_last_sample_ms;

    sample = samples.createNestedObject();
    sample["port_id"] = "i2c.s1";
    sample["module_type"] = "AHT20";
    sample["capability"] = "env.humidity";
    sample["value"] = g_aht20_humidity;
    sample["unit"] = "%RH";
    sample["ts_ms"] = g_aht20_last_sample_ms;
  }

  if (g_last_execution_valid)
  {
    sample = samples.createNestedObject();
    sample["port_id"] = "pwm.0";
    sample["module_type"] = "SG90";
    sample["capability"] = "motor.servo.angle";
    sample["value"] = g_last_execution_angle_degrees;
    sample["unit"] = "degree";
    sample["ts_ms"] = g_last_execution_ms;
    sample["source"] = "execution_feedback";
  }
}

void add_telemetry_samples(JsonObject payload)
{
  bool has_board_samples = false;

  for (size_t i = 0U; i < kBoardSampleCount; i++)
  {
    if (g_board_samples[i].valid)
    {
      has_board_samples = true;
      break;
    }
  }

  if (!has_board_samples)
  {
    add_telemetry_samples_fallback(payload);
    return;
  }

  JsonArray samples = payload.createNestedArray("samples");
  for (size_t i = 0U; i < kBoardSampleCount; i++)
  {
    JsonObject sample_object;
    BoardSampleState const & sample = g_board_samples[i];

    if (!sample.valid)
    {
      continue;
    }

    sample_object = samples.createNestedObject();
    sample_object["port_id"] = sample.port_id;
    sample_object["module_type"] = sample.module_type;
    sample_object["capability"] = sample.capability;
    sample_object["value"] = sample.value;
    sample_object["unit"] = sample.unit;
    sample_object["ts_ms"] = sample.ts_ms;
    if (sample.source[0] != '\0')
    {
      sample_object["source"] = sample.source;
    }
  }
}

char const * current_wifi_ssid()
{
  static char ssid_text[40];
  String connected_ssid;

  if (WiFi.status() != WL_CONNECTED)
  {
    return "-";
  }

  connected_ssid = WiFi.SSID();
  if (connected_ssid.isEmpty())
  {
    return "-";
  }

  connected_ssid.toCharArray(ssid_text, sizeof(ssid_text));
  return ssid_text;
}

int find_wifi_profile_index(char const * ssid)
{
  if ((nullptr == ssid) || ('\0' == ssid[0]))
  {
    return -1;
  }

  for (size_t i = 0U; i < kWifiProfileCount; ++i)
  {
    if (strcmp(kWifiProfiles[i].ssid, ssid) == 0)
    {
      return static_cast<int>(i);
    }
  }

  return -1;
}

int pick_best_wifi_profile()
{
  int best_profile = -1;
  int16_t best_rssi = -32768;
  int network_count = 0;

  network_count = WiFi.scanNetworks(false, true, false, 300, 0);
  if (network_count <= 0)
  {
    return -1;
  }

  for (int network_index = 0; network_index < network_count; ++network_index)
  {
    String visible_ssid = WiFi.SSID(network_index);
    int profile_index = find_wifi_profile_index(visible_ssid.c_str());
    int16_t rssi = WiFi.RSSI(network_index);

    if ((profile_index >= 0) && (rssi > best_rssi))
    {
      best_profile = profile_index;
      best_rssi = rssi;
    }
  }

  return best_profile;
}

void begin_wifi_profile(int profile_index)
{
  char line[96];

  if ((profile_index < 0) || (static_cast<size_t>(profile_index) >= kWifiProfileCount))
  {
    return;
  }

  snprintf(line, sizeof(line), "wifi profile:%s", kWifiProfiles[profile_index].ssid);
  publish_usb_line(line);
  WiFi.begin(kWifiProfiles[profile_index].ssid, kWifiProfiles[profile_index].password);
}

char const * topic_status()
{
  return g_status_topic;
}

char const * topic_telemetry()
{
  return g_telemetry_topic;
}

char const * topic_event()
{
  return g_event_topic;
}

char const * topic_script()
{
  return g_script_topic;
}

bool parse_key_value(char const * text, char const * key, char * dest, size_t dest_size)
{
  char pattern[24];
  char const * start;
  char const * match;
  char const * end;
  size_t length;

  if ((nullptr == text) || (nullptr == key) || (nullptr == dest) || (0U == dest_size))
  {
    return false;
  }

  snprintf(pattern, sizeof(pattern), "%s=", key);
  match = text;
  start = nullptr;
  while (nullptr != (match = strstr(match, pattern)))
  {
    if ((match == text) || (match[-1] == ';') || (match[-1] == ':'))
    {
      start = match;
      break;
    }
    match += 1;
  }

  if (nullptr == start)
  {
    return false;
  }

  start += strlen(pattern);
  end = strchr(start, ';');
  length = (nullptr == end) ? strlen(start) : static_cast<size_t>(end - start);
  if (length >= dest_size)
  {
    length = dest_size - 1U;
  }

  memcpy(dest, start, length);
  dest[length] = '\0';
  return true;
}

bool extract_display_text(char const * lua_code, char * dest, size_t dest_size)
{
  char const * start;
  char const * end;
  size_t length;

  if ((nullptr == lua_code) || (nullptr == dest) || (0U == dest_size))
  {
    return false;
  }

  start = strstr(lua_code, "screen_text(\"");
  if (nullptr == start)
  {
    start = strstr(lua_code, "print(\"");
    if (nullptr == start)
    {
      return false;
    }
    start += strlen("print(\"");
  }
  else
  {
    start += strlen("screen_text(\"");
  }

  end = strchr(start, '"');
  if (nullptr == end)
  {
    return false;
  }

  length = static_cast<size_t>(end - start);
  if (length >= dest_size)
  {
    length = dest_size - 1U;
  }

  memcpy(dest, start, length);
  dest[length] = '\0';
  return true;
}

bool extract_threshold_rule(char const * lua_code, char * op_text, size_t op_text_size, int32_t * threshold_tenths)
{
  char const * start;
  int sign = 1;
  int32_t integer_part = 0;
  int32_t decimal_tenths = 0;

  if ((lua_code == nullptr) || (op_text == nullptr) || (op_text_size < 2U) || (threshold_tenths == nullptr))
  {
    return false;
  }

  start = strstr(lua_code, "if data.temp ");
  if (start == nullptr)
  {
    return false;
  }

  start += strlen("if data.temp ");
  if ((*start != '>') && (*start != '<'))
  {
    return false;
  }

  op_text[0] = *start;
  op_text[1] = '\0';
  start++;
  if ((*start == '=') && (op_text_size >= 3U))
  {
    op_text[1] = '=';
    op_text[2] = '\0';
    start++;
  }

  while (*start == ' ')
  {
    start++;
  }

  if (*start == '-')
  {
    sign = -1;
    start++;
  }

  if ((*start < '0') || (*start > '9'))
  {
    return false;
  }

  while ((*start >= '0') && (*start <= '9'))
  {
    integer_part = (integer_part * 10) + static_cast<int32_t>(*start - '0');
    start++;
  }

  if (*start == '.')
  {
    start++;
    if ((*start >= '0') && (*start <= '9'))
    {
      decimal_tenths = static_cast<int32_t>(*start - '0');
      start++;
    }
  }

  while (*start == ' ')
  {
    start++;
  }

  if (strncmp(start, "then", 4) != 0)
  {
    return false;
  }

  *threshold_tenths = ((integer_part * 10) + decimal_tenths) * sign;
  return true;
}

bool extract_servo_angle(char const * lua_code, int32_t * angle_degrees)
{
  char const * start;
  int32_t parsed_angle = 0;

  if ((lua_code == nullptr) || (angle_degrees == nullptr))
  {
    return false;
  }

  start = strstr(lua_code, "servo_set(");
  if (start == nullptr)
  {
    return false;
  }

  start += strlen("servo_set(");
  if ((*start < '0') || (*start > '9'))
  {
    return false;
  }

  while ((*start >= '0') && (*start <= '9'))
  {
    parsed_angle = (parsed_angle * 10) + static_cast<int32_t>(*start - '0');
    start++;
  }

  if (*start != ')')
  {
    return false;
  }

  if (parsed_angle < 0)
  {
    parsed_angle = 0;
  }
  if (parsed_angle > 180)
  {
    parsed_angle = 180;
  }

  *angle_degrees = parsed_angle;
  return true;
}

bool forward_rule_program(JsonObjectConst program, char * text, size_t text_size)
{
  JsonObjectConst trigger;
  JsonArrayConst actions;
  const char * sensor;
  const char * op_text;
  float threshold_value;
  int32_t threshold_tenths;
  long cooldown_ms;
  char cmd_line[96];
  size_t action_count = 0U;

  if ((text == nullptr) || (text_size == 0U))
  {
    return false;
  }

  trigger = program["trigger"];
  actions = program["actions"].as<JsonArrayConst>();
  sensor = trigger["sensor"] | "";
  op_text = trigger["operator"] | "";
  threshold_value = trigger["value"] | 0.0f;
  threshold_tenths = static_cast<int32_t>(threshold_value >= 0.0f ? ((threshold_value * 10.0f) + 0.5f) : ((threshold_value * 10.0f) - 0.5f));
  cooldown_ms = program["cooldown_ms"] | 30000L;

  if ((strcmp(sensor, "AHT20.temp") != 0) || (actions.isNull()) || (actions.size() == 0U))
  {
    return false;
  }

  snprintf(cmd_line, sizeof(cmd_line), "rule:sensor=temp;op=%s;value=%ld", op_text, static_cast<long>(threshold_tenths));
  publish_uart_line(cmd_line);
  publish_uart_line("seq:clear");

  for (JsonObjectConst action : actions)
  {
    const char * device = action["device"] | "";
    const char * method = action["method"] | "";
    int angle = action["params"]["angle"] | 90;
    int duration_ms = action["params"]["duration_ms"] | 350;

    if ((strcmp(device, "SG90") != 0) || (strcmp(method, "servo_set") != 0))
    {
      return false;
    }

    if (angle < 0)
    {
      angle = 0;
    }
    if (angle > 180)
    {
      angle = 180;
    }
    if (duration_ms < 50)
    {
      duration_ms = 50;
    }
    if (duration_ms > 5000)
    {
      duration_ms = 5000;
    }

    snprintf(cmd_line, sizeof(cmd_line), "seq:add;angle=%d;ms=%d", angle, duration_ms);
    publish_uart_line(cmd_line);
    action_count++;
  }

  if (action_count == 0U)
  {
    return false;
  }

  if (cooldown_ms < 0L)
  {
    cooldown_ms = 0L;
  }
  if (cooldown_ms > 600000L)
  {
    cooldown_ms = 600000L;
  }
  snprintf(cmd_line, sizeof(cmd_line), "cooldown:ms=%ld", cooldown_ms);
  publish_uart_line(cmd_line);

  snprintf(text, text_size, "T %s %ld.%ldC SG90",
          op_text,
          static_cast<long>(threshold_tenths / 10),
          static_cast<long>(abs(static_cast<long>(threshold_tenths % 10))));
  return true;
}

void publish_runtime_snapshot()
{
  publish_uart_line(g_wifi_connected ? "wifi:connected" : "wifi:disconnected");
  publish_uart_line(g_mqtt_connected ? "mqtt:connected" : "mqtt:disconnected");
  publish_time_to_uart();
  if (g_last_request_id[0] != '\0')
  {
    char buffer[96];
    snprintf(buffer, sizeof(buffer), "req:%s", g_last_request_id);
    publish_uart_line(buffer);
  }
  if (g_last_script_id[0] != '\0')
  {
    char buffer[96];
    snprintf(buffer, sizeof(buffer), "script:%s", g_last_script_id);
    publish_uart_line(buffer);
  }
  if (g_last_display_text[0] != '\0')
  {
    char buffer[96];
    snprintf(buffer, sizeof(buffer), "cmd:%s", g_last_display_text);
    publish_uart_line(buffer);
  }
}

void publish_time_to_uart()
{
  struct tm time_info;
  char line[48];

  if (!g_time_synced)
  {
    return;
  }

  if (!getLocalTime(&time_info, 50))
  {
    g_time_synced = false;
    return;
  }

  snprintf(line,
           sizeof(line),
           "time:%04d-%02d-%02dT%02d:%02d:%02d+08:00",
           time_info.tm_year + 1900,
           time_info.tm_mon + 1,
           time_info.tm_mday,
           time_info.tm_hour,
           time_info.tm_min,
           time_info.tm_sec);
  publish_uart_line(line);
}

void add_clock_payload(JsonObject payload)
{
  struct tm time_info;
  JsonObject clock = payload.createNestedObject("clock");
  clock["timezone"] = "Asia/Shanghai";
  clock["synced"] = g_time_synced;
  if (!g_time_synced || !getLocalTime(&time_info, 50))
  {
    return;
  }

  char local_iso[32];
  snprintf(local_iso,
           sizeof(local_iso),
           "%04d-%02d-%02dT%02d:%02d:%02d+08:00",
           time_info.tm_year + 1900,
           time_info.tm_mon + 1,
           time_info.tm_mday,
           time_info.tm_hour,
           time_info.tm_min,
           time_info.tm_sec);
  clock["local_iso"] = local_iso;
  clock["year"] = time_info.tm_year + 1900;
  clock["month"] = time_info.tm_mon + 1;
  clock["day"] = time_info.tm_mday;
  clock["hour"] = time_info.tm_hour;
  clock["minute"] = time_info.tm_min;
  clock["second"] = time_info.tm_sec;
}

void ensure_time_sync()
{
  struct tm time_info;
  uint32_t now = millis();

  if (WiFi.status() != WL_CONNECTED)
  {
    return;
  }

  if (!g_time_service_started)
  {
    configTime(kTimeZoneOffsetSeconds,
               kTimeDaylightOffsetSeconds,
               "ntp1.aliyun.com",
               "ntp.tencent.com",
               "pool.ntp.org");
    g_time_service_started = true;
    g_last_time_sync_ms = 0U;
  }

  if (g_time_synced)
  {
    if ((now - g_last_time_sync_ms) < kTimeResyncMs)
    {
      return;
    }
  }
  else if ((now - g_last_time_sync_ms) < kTimeRetryMs)
  {
    return;
  }

  g_last_time_sync_ms = now;
  if (!getLocalTime(&time_info, 1200))
  {
    return;
  }

  g_time_synced = true;
  publish_time_to_uart();
}

bool begin_wifi_connection_by_ssid(char const * ssid)
{
  int profile_index;

  if ((ssid == nullptr) || (ssid[0] == '\0'))
  {
    return false;
  }

  if ((WiFi.status() == WL_CONNECTED) && (0 == strcmp(current_wifi_ssid(), ssid)))
  {
    publish_runtime_snapshot();
    return true;
  }

  if (g_saved_wifi_available && (0 == strcmp(g_saved_wifi_ssid, ssid)))
  {
    g_wifi_connected = false;
    g_last_wifi_attempt_ms = 0U;
    begin_wifi_saved_credentials();
    return true;
  }

  profile_index = find_wifi_profile_index(ssid);
  if (profile_index >= 0)
  {
    g_wifi_connected = false;
    g_last_wifi_attempt_ms = 0U;
    begin_wifi_profile(profile_index);
    return true;
  }

  return false;
}

void handle_wifi_scan_uart()
{
  int network_count;
  uint32_t emitted_count = 0U;
  bool emitted_current = false;

  publish_uart_line("wifi-scan:clear");
  network_count = WiFi.scanNetworks(false, true, false, 500, 0);
  for (int i = 0; i < network_count; i++)
  {
    String visible_ssid = WiFi.SSID(i);
    bool is_connected;
    bool is_saved;
    int profile_index;
    char const * state = "visible";

    if (visible_ssid.isEmpty())
    {
      continue;
    }

    is_connected = (WiFi.status() == WL_CONNECTED) && visible_ssid.equals(current_wifi_ssid());
    profile_index = find_wifi_profile_index(visible_ssid.c_str());
    is_saved = (profile_index >= 0) ||
               (g_saved_wifi_available && visible_ssid.equals(g_saved_wifi_ssid));
    if (is_connected)
    {
      state = "connected";
    }
    else if (is_saved)
    {
      state = "saved";
    }

    char line[192];
    visible_ssid.replace("\r", " ");
    visible_ssid.replace("\n", " ");
    snprintf(line,
             sizeof(line),
             "wifi-scan:item=%s;rssi=%d;state=%s",
             visible_ssid.c_str(),
             WiFi.RSSI(i),
             state);
    publish_uart_line(line);
    emitted_count++;
    if (is_connected)
    {
      emitted_current = true;
    }
  }

  if (!emitted_current && (WiFi.status() == WL_CONNECTED))
  {
    char line[192];
    snprintf(line,
             sizeof(line),
             "wifi-scan:item=%s;rssi=%d;state=connected",
             current_wifi_ssid(),
             WiFi.RSSI());
    publish_uart_line(line);
    emitted_count++;
  }

  char done_line[48];
  snprintf(done_line, sizeof(done_line), "wifi-scan:done;count=%lu", static_cast<unsigned long>(emitted_count));
  publish_uart_line(done_line);
}

void publish_status()
{
  StaticJsonDocument<4096> doc;
  JsonObject payload = doc.createNestedObject("payload");
  JsonArray hardware_list = payload.createNestedArray("hardware_list");
  JsonObject i2c = payload.createNestedObject("i2c");
  JsonArray i2c_devices = i2c.createNestedArray("devices");
  char buffer[4096];

  doc["type"] = "status";
  doc["request_id"] = "status_tick";
  payload["device_id"] = g_device_id;
  add_clock_payload(payload);
  JsonObject identity = payload.createNestedObject("identity");
  identity["ra8p1_uid"] = g_ra8p1_uid;
  identity["esp32_mac"] = g_esp32_mac;
  identity["esp32_chip_id"] = g_esp32_chip_id;
  identity["registered"] = g_device_registered;
  payload["state"] = g_mqtt_connected ? "ONLINE" : "ERROR";
  payload["wifi"] = g_wifi_connected ? "connected" : "disconnected";
  payload["mqtt"] = g_mqtt_connected ? "connected" : "disconnected";
  payload["uart"] = g_uart_online ? "online" : "waiting";
  payload["script_state"] = g_script_state;
  i2c["bus"] = "s1";
  i2c["diag"] = g_i2c_diag;
  i2c["count"] = g_i2c_device_count;
  add_platform_bus(payload, true);
  add_status_ports(payload);

  if (g_last_request_id[0] != '\0')
  {
    payload["last_request_id"] = g_last_request_id;
  }
  if (g_last_script_id[0] != '\0')
  {
    payload["last_script_id"] = g_last_script_id;
  }
  if (g_last_intent_type[0] != '\0')
  {
    payload["last_intent_type"] = g_last_intent_type;
  }
  if (g_last_execution_valid)
  {
    JsonObject last_execution = payload.createNestedObject("last_execution");
    last_execution["state"] = g_last_execution_state;
    if (g_last_execution_reason[0] != '\0')
    {
      last_execution["reason"] = g_last_execution_reason;
    }
    if (g_last_execution_operator[0] != '\0')
    {
      last_execution["operator"] = g_last_execution_operator;
    }
    if (g_last_execution_action[0] != '\0')
    {
      last_execution["action"] = g_last_execution_action;
    }
    last_execution["sample"] = g_last_execution_has_sample;
    last_execution["threshold"] = static_cast<float>(g_last_execution_threshold_tenths) / 10.0f;
    last_execution["angle"] = g_last_execution_angle_degrees;
    if (g_last_execution_has_sample)
    {
      last_execution["temp"] = static_cast<float>(g_last_execution_temp_tenths) / 10.0f;
    }
  }

  for (size_t i = 0U; i < g_i2c_device_count; i++)
  {
    char address_text[8];
    JsonObject device = i2c_devices.createNestedObject();
    JsonObject hw = hardware_list.createNestedObject();

    snprintf(address_text, sizeof(address_text), "0x%02X", g_i2c_addresses[i]);
    device["address"] = address_text;
    device["type"] = g_i2c_labels[i];
    hw["address"] = address_text;
    hw["type"] = g_i2c_labels[i];
    hw["status"] = "present";
    hw["bus"] = "s1";
  }

  if (!i2c_inventory_contains(0x38U))
  {
    JsonObject hw = hardware_list.createNestedObject();
    hw["address"] = "0x38";
    hw["type"] = "AHT20";
    hw["status"] = g_aht20_online ? "online" : "offline";
    hw["bus"] = "s1";
  }

  JsonObject aht20 = payload.createNestedObject("aht20");
  aht20["status"] = g_aht20_online ? "online" : "offline";
  aht20["crc_ok"] = g_aht20_crc_ok;
  if (g_aht20_diag[0] != '\0')
  {
    aht20["diag"] = g_aht20_diag;
  }
  if (g_aht20_has_sample)
  {
    aht20["temp"] = g_aht20_temp_c;
    aht20["humidity"] = g_aht20_humidity;
  }

  size_t len = serializeJson(doc, buffer, sizeof(buffer));
  g_mqtt.publish(topic_status(), buffer, len);
  g_last_status_ms = millis();
  g_status_dirty = false;
}

void publish_telemetry()
{
  StaticJsonDocument<3072> doc;
  JsonObject payload = doc.createNestedObject("payload");
  JsonObject aht20 = payload.createNestedObject("aht20");
  JsonObject i2c = payload.createNestedObject("i2c");
  JsonArray i2c_devices = i2c.createNestedArray("devices");
  char buffer[3072];

  doc["type"] = "telemetry";
  doc["request_id"] = "telemetry_tick";
  payload["device_id"] = g_device_id;
  add_clock_payload(payload);
  JsonObject identity = payload.createNestedObject("identity");
  identity["ra8p1_uid"] = g_ra8p1_uid;
  identity["esp32_mac"] = g_esp32_mac;
  identity["esp32_chip_id"] = g_esp32_chip_id;
  identity["registered"] = g_device_registered;
  i2c["bus"] = "s1";
  i2c["diag"] = g_i2c_diag;
  i2c["count"] = g_i2c_device_count;
  add_platform_bus(payload, false);
  add_status_ports(payload);
  add_telemetry_samples(payload);
  aht20["status"] = g_aht20_online ? "online" : "offline";
  aht20["crc_ok"] = g_aht20_crc_ok;
  if (g_aht20_diag[0] != '\0')
  {
    aht20["diag"] = g_aht20_diag;
  }
  if (g_aht20_has_sample)
  {
    aht20["temp"] = g_aht20_temp_c;
    aht20["humidity"] = g_aht20_humidity;
  }

  for (size_t i = 0U; i < g_i2c_device_count; i++)
  {
    char address_text[8];
    JsonObject device = i2c_devices.createNestedObject();
    snprintf(address_text, sizeof(address_text), "0x%02X", g_i2c_addresses[i]);
    device["address"] = address_text;
    device["type"] = g_i2c_labels[i];
  }

  size_t len = serializeJson(doc, buffer, sizeof(buffer));
  g_mqtt.publish(topic_telemetry(), buffer, len);
  g_last_telemetry_ms = millis();
  g_telemetry_dirty = false;
}

void publish_deploy_ack_event(char const * request_id, char const * script_id, int code, char const * message)
{
  StaticJsonDocument<512> doc;
  JsonObject payload = doc.createNestedObject("payload");
  char buffer[512];

  doc["type"] = "deploy_ack";
  doc["request_id"] = request_id;
  payload["device_id"] = g_device_id;
  payload["ra8p1_uid"] = g_ra8p1_uid;
  payload["esp32_mac"] = g_esp32_mac;
  payload["script_id"] = script_id;
  payload["code"] = code;
  payload["message"] = message;
  payload["state"] = (code == 0) ? "SCRIPT_ACCEPTED" : "SCRIPT_REJECTED";

  size_t len = serializeJson(doc, buffer, sizeof(buffer));
  g_mqtt.publish(topic_event(), buffer, len);
}

void publish_execution_state_event(char const * request_id, char const * script_id, char const * state_text, int32_t temperature_tenths)
{
  StaticJsonDocument<512> doc;
  JsonObject payload = doc.createNestedObject("payload");
  char buffer[512];

  doc["type"] = "execution_state";
  doc["request_id"] = request_id;
  payload["device_id"] = g_device_id;
  payload["ra8p1_uid"] = g_ra8p1_uid;
  payload["esp32_mac"] = g_esp32_mac;
  payload["script_id"] = script_id;
  payload["state"] = state_text;
  payload["temp"] = static_cast<float>(temperature_tenths) / 10.0f;

  size_t len = serializeJson(doc, buffer, sizeof(buffer));
  g_mqtt.publish(topic_event(), buffer, len);
}

void publish_execution_state_event_ex(
    char const * request_id,
    char const * script_id,
    char const * state_text,
    char const * reason_text,
    bool has_sample,
    int32_t temperature_tenths,
    char const * operator_text,
    int32_t threshold_tenths,
    char const * action_text,
    int32_t angle_degrees)
{
  StaticJsonDocument<640> doc;
  JsonObject payload = doc.createNestedObject("payload");
  char buffer[640];

  doc["type"] = "execution_state";
  doc["request_id"] = request_id;
  payload["device_id"] = g_device_id;
  payload["ra8p1_uid"] = g_ra8p1_uid;
  payload["esp32_mac"] = g_esp32_mac;
  payload["script_id"] = script_id;
  payload["state"] = state_text;
  payload["sample"] = has_sample;
  if ((reason_text != nullptr) && (reason_text[0] != '\0'))
  {
    payload["reason"] = reason_text;
  }
  if ((operator_text != nullptr) && (operator_text[0] != '\0'))
  {
    payload["operator"] = operator_text;
  }
  if ((action_text != nullptr) && (action_text[0] != '\0'))
  {
    payload["action"] = action_text;
  }
  payload["threshold"] = static_cast<float>(threshold_tenths) / 10.0f;
  payload["angle"] = angle_degrees;
  if (has_sample)
  {
    payload["temp"] = static_cast<float>(temperature_tenths) / 10.0f;
  }

  size_t len = serializeJson(doc, buffer, sizeof(buffer));
  g_mqtt.publish(topic_event(), buffer, len);
}

void handle_ack_line(char const * line)
{
  char request_id[64];
  char script_id[64];
  char code_text[8];
  char message[32];
  int code = 0;

  if ((!parse_key_value(line, "req", request_id, sizeof(request_id)))
      || (!parse_key_value(line, "script", script_id, sizeof(script_id))))
  {
    return;
  }

  if (parse_key_value(line, "code", code_text, sizeof(code_text)))
  {
    code = atoi(code_text);
  }
  else
  {
    code = -1;
  }

  if (!parse_key_value(line, "msg", message, sizeof(message)))
  {
    copy_text(message, sizeof(message), "accepted");
  }

  copy_text(g_last_request_id, sizeof(g_last_request_id), request_id);
  copy_text(g_last_script_id, sizeof(g_last_script_id), script_id);
  copy_text(g_script_state, sizeof(g_script_state), (code == 0) ? "ACKED" : "ERROR");
  publish_deploy_ack_event(request_id, script_id, code, message);
  g_status_dirty = true;
}

void handle_exec_line(char const * line)
{
  char request_id[64];
  char script_id[64];
  char state_text[24];
  char reason_text[24];
  char value_text[16];
  char operator_text[4];
  char action_text[16];
  int32_t temperature_tenths = 0;
  int32_t threshold_tenths = 0;
  int32_t angle_degrees = 0;
  bool has_sample = false;

  if ((!parse_key_value(line, "req", request_id, sizeof(request_id)))
      || (!parse_key_value(line, "script", script_id, sizeof(script_id)))
      || (!parse_key_value(line, "state", state_text, sizeof(state_text))))
  {
    return;
  }

  reason_text[0] = '\0';
  operator_text[0] = '\0';
  action_text[0] = '\0';

  if (parse_key_value(line, "reason", reason_text, sizeof(reason_text)))
  {
  }
  if (parse_key_value(line, "sample", value_text, sizeof(value_text)))
  {
    has_sample = atoi(value_text) != 0;
  }
  if (parse_key_value(line, "t", value_text, sizeof(value_text)))
  {
    temperature_tenths = static_cast<int32_t>(atoi(value_text));
  }
  if (parse_key_value(line, "op", operator_text, sizeof(operator_text)))
  {
  }
  if (parse_key_value(line, "value", value_text, sizeof(value_text)))
  {
    threshold_tenths = static_cast<int32_t>(atoi(value_text));
  }
  if (parse_key_value(line, "action", action_text, sizeof(action_text)))
  {
  }
  if (parse_key_value(line, "angle", value_text, sizeof(value_text)))
  {
    angle_degrees = atoi(value_text);
  }

  copy_text(g_last_request_id, sizeof(g_last_request_id), request_id);
  copy_text(g_last_script_id, sizeof(g_last_script_id), script_id);
  copy_text(g_script_state, sizeof(g_script_state), state_text);
  copy_text(g_last_execution_state, sizeof(g_last_execution_state), state_text);
  copy_text(g_last_execution_reason, sizeof(g_last_execution_reason), reason_text);
  copy_text(g_last_execution_operator, sizeof(g_last_execution_operator), operator_text);
  copy_text(g_last_execution_action, sizeof(g_last_execution_action), action_text);
  g_last_execution_has_sample = has_sample;
  g_last_execution_temp_tenths = temperature_tenths;
  g_last_execution_threshold_tenths = threshold_tenths;
  g_last_execution_angle_degrees = angle_degrees;
  g_last_execution_valid = true;
  g_last_execution_ms = millis();
  publish_execution_state_event_ex(
      request_id,
      script_id,
      state_text,
      reason_text,
      has_sample,
      temperature_tenths,
      operator_text,
      threshold_tenths,
      action_text,
      angle_degrees);
  g_status_dirty = true;
}

void handle_aht20_line(char const * line)
{
  char value[24];
  char diag[32];

  if (strstr(line, "status=offline") != nullptr)
  {
    g_aht20_online = false;
    g_aht20_has_sample = false;
    g_aht20_crc_ok = false;
    if (parse_key_value(line, "diag", diag, sizeof(diag)))
    {
      copy_text(g_aht20_diag, sizeof(g_aht20_diag), diag);
    }
    else
    {
      g_aht20_diag[0] = '\0';
    }
    g_status_dirty = true;
    g_telemetry_dirty = true;
    return;
  }

  g_aht20_online = true;
  g_aht20_diag[0] = '\0';
  if (parse_key_value(line, "t", value, sizeof(value)))
  {
    g_aht20_temp_c = static_cast<float>(atof(value));
    g_aht20_has_sample = true;
    g_aht20_last_sample_ms = millis();
  }
  if (parse_key_value(line, "h", value, sizeof(value)))
  {
    g_aht20_humidity = static_cast<float>(atof(value));
    g_aht20_has_sample = true;
    g_aht20_last_sample_ms = millis();
  }
  if (parse_key_value(line, "crc", value, sizeof(value)))
  {
    g_aht20_crc_ok = atoi(value) != 0;
  }

  g_status_dirty = true;
  g_telemetry_dirty = true;
}

void handle_i2c_line(char const * line)
{
  char diag[32];
  char count_text[8];
  char devices[160];

  if (parse_key_value(line, "diag", diag, sizeof(diag)))
  {
    copy_text(g_i2c_diag, sizeof(g_i2c_diag), diag);
  }
  else
  {
    copy_text(g_i2c_diag, sizeof(g_i2c_diag), "unknown");
  }

  if (parse_key_value(line, "count", count_text, sizeof(count_text)))
  {
    g_i2c_device_count = static_cast<uint8_t>(atoi(count_text));
    if (g_i2c_device_count > kI2cScanMaxDevices)
    {
      g_i2c_device_count = static_cast<uint8_t>(kI2cScanMaxDevices);
    }
  }

  if (parse_key_value(line, "devices", devices, sizeof(devices)))
  {
    parse_i2c_inventory(devices);
  }
  else
  {
    clear_i2c_inventory();
  }

  g_i2c_last_scan_ms = millis();

  g_status_dirty = true;
  g_telemetry_dirty = true;
}

void handle_port_line(char const * line)
{
  char value[192];
  BoardPortState * port;

  if (!parse_key_value(line, "id", value, sizeof(value)))
  {
    return;
  }

  port = find_or_alloc_board_port(value);
  if (port == nullptr)
  {
    return;
  }

  if (parse_key_value(line, "physical", value, sizeof(value)))
  {
    copy_text(port->physical_port, sizeof(port->physical_port), value);
  }
  if (parse_key_value(line, "channel", value, sizeof(value)))
  {
    copy_text(port->channel, sizeof(port->channel), value);
  }
  if (parse_key_value(line, "type", value, sizeof(value)))
  {
    copy_text(port->type, sizeof(port->type), value);
  }
  if (parse_key_value(line, "act", value, sizeof(value)))
  {
    copy_text(port->activation, sizeof(port->activation), value);
  }
  if (parse_key_value(line, "status", value, sizeof(value)))
  {
    copy_text(port->status, sizeof(port->status), value);
  }
  if (parse_key_value(line, "diag", value, sizeof(value)))
  {
    copy_text(port->diag, sizeof(port->diag), value);
  }
  if (parse_key_value(line, "mid", value, sizeof(value)))
  {
    copy_text(port->module_id, sizeof(port->module_id), value);
  }
  if (parse_key_value(line, "mtype", value, sizeof(value)))
  {
    copy_text(port->module_type, sizeof(port->module_type), value);
  }
  if (parse_key_value(line, "mclass", value, sizeof(value)))
  {
    copy_text(port->module_class, sizeof(port->module_class), value);
  }
  if (parse_key_value(line, "drv", value, sizeof(value)))
  {
    copy_text(port->driver, sizeof(port->driver), value);
  }
  if (parse_key_value(line, "mstate", value, sizeof(value)))
  {
    copy_text(port->model_state, sizeof(port->model_state), value);
  }
  if (parse_key_value(line, "bind", value, sizeof(value)))
  {
    copy_text(port->binding_source, sizeof(port->binding_source), value);
  }
  if (parse_key_value(line, "dkey", value, sizeof(value)))
  {
    copy_text(port->device_key, sizeof(port->device_key), value);
  }
  if (parse_key_value(line, "conf", value, sizeof(value)))
  {
    copy_text(port->confidence, sizeof(port->confidence), value);
  }
  if (parse_key_value(line, "addr", value, sizeof(value)))
  {
    copy_text(port->address, sizeof(port->address), value);
  }
  if (parse_key_value(line, "caps", value, sizeof(value)))
  {
    parse_port_capabilities(value, port);
  }
  if (parse_key_value(line, "ts", value, sizeof(value)))
  {
    port->last_sample_ms = static_cast<uint32_t>(strtoul(value, nullptr, 10));
  }

  g_status_dirty = true;
  g_telemetry_dirty = true;
}

void handle_sample_line(char const * line)
{
  char port_id[32];
  char capability[48];
  char value_text[32];
  BoardSampleState * sample;

  if ((!parse_key_value(line, "port", port_id, sizeof(port_id)))
      || (!parse_key_value(line, "cap", capability, sizeof(capability))))
  {
    return;
  }

  sample = find_or_alloc_board_sample(port_id, capability);
  if (sample == nullptr)
  {
    return;
  }

  if (parse_key_value(line, "module", value_text, sizeof(value_text)))
  {
    copy_text(sample->module_type, sizeof(sample->module_type), value_text);
  }
  if (parse_key_value(line, "value", value_text, sizeof(value_text)))
  {
    sample->value = static_cast<float>(atof(value_text));
  }
  if (parse_key_value(line, "unit", value_text, sizeof(value_text)))
  {
    copy_text(sample->unit, sizeof(sample->unit), value_text);
  }
  if (parse_key_value(line, "ts", value_text, sizeof(value_text)))
  {
    sample->ts_ms = static_cast<uint32_t>(strtoul(value_text, nullptr, 10));
  }
  if (parse_key_value(line, "source", value_text, sizeof(value_text)))
  {
    copy_text(sample->source, sizeof(sample->source), value_text);
  }

  g_status_dirty = true;
  g_telemetry_dirty = true;
}

void handle_line(char const * line)
{
  uint32_t now = millis();

  if (nullptr == line)
  {
    return;
  }

  g_last_rx_ms = now;
  g_rx_flash_until_ms = now + kEventFlashMs;
  g_uart_online = true;

  if (0 == strcmp(line, "ping"))
  {
    publish_uart_line("pong");
    return;
  }

  if ((0 == strcmp(line, "ra8p1-ready")) || (0 == strcmp(line, "ra8p1-uart-link-boot")))
  {
    publish_runtime_snapshot();
    return;
  }

  if (0 == strcmp(line, "wifi:scan"))
  {
    handle_wifi_scan_uart();
    return;
  }

  if (0 == strncmp(line, "wifi:connect:", 13))
  {
    if (begin_wifi_connection_by_ssid(line + 13))
    {
      publish_uart_line("wifi:connecting");
    }
    else
    {
      publish_uart_line("wifi:connect-failed");
    }
    return;
  }

  if (0 == strncmp(line, "ra8p1_uid:", 10))
  {
    copy_text(g_ra8p1_uid, sizeof(g_ra8p1_uid), line + 10);
    g_device_registered = (0 != strcmp(g_device_id, kDefaultDeviceId));
    g_status_dirty = true;
    ensure_device_registration();
    return;
  }

  if (0 == strncmp(line, "nl:", 3))
  {
    (void) submit_nl_to_cloud(line + 3);
    return;
  }

  if (0 == strncmp(line, "ack:req=", 8))
  {
    handle_ack_line(line);
    return;
  }

  if (0 == strncmp(line, "exec:req=", 9))
  {
    handle_exec_line(line);
    return;
  }

  if (0 == strncmp(line, "aht20:", 6))
  {
    handle_aht20_line(line);
    return;
  }

  if (0 == strncmp(line, "i2c:", 4))
  {
    handle_i2c_line(line);
    return;
  }

  if (0 == strncmp(line, "port:", 5))
  {
    handle_port_line(line);
    return;
  }

  if (0 == strncmp(line, "sample:", 7))
  {
    handle_sample_line(line);
    return;
  }
}

void handle_wifi_scan_usb()
{
  StaticJsonDocument<2048> doc;
  JsonArray networks = doc.createNestedArray("networks");
  int network_count = WiFi.scanNetworks(false, true, false, 500, 0);

  doc["type"] = "wifi.scan.result";
  doc["count"] = network_count > 0 ? network_count : 0;
  if (network_count > 0)
  {
    int limit = network_count > 12 ? 12 : network_count;
    for (int i = 0; i < limit; ++i)
    {
      JsonObject item = networks.createNestedObject();
      item["ssid"] = WiFi.SSID(i);
      item["rssi"] = WiFi.RSSI(i);
      item["secure"] = WiFi.encryptionType(i) != WIFI_AUTH_OPEN;
    }
  }

  serializeJson(doc, Serial);
  Serial.print("\r\n");
}

void handle_usb_provisioning_line(char const * line)
{
  StaticJsonDocument<768> doc;
  StaticJsonDocument<256> response;
  DeserializationError err;
  const char * type;
  const char * ssid;
  const char * password;

  if ((nullptr == line) || ('\0' == line[0]))
  {
    return;
  }

  if (0 == strcmp(line, "wifi:status"))
  {
    publish_wifi_status_usb();
    return;
  }

  if (0 == strcmp(line, "wifi:scan"))
  {
    handle_wifi_scan_usb();
    return;
  }

  err = deserializeJson(doc, line);
  if (err)
  {
    response["type"] = "wifi.error";
    response["message"] = "invalid_json";
    serializeJson(response, Serial);
    Serial.print("\r\n");
    return;
  }

  type = doc["type"] | "";
  if (0 == strcmp(type, "wifi.status"))
  {
    publish_wifi_status_usb();
    return;
  }

  if (0 == strcmp(type, "wifi.scan"))
  {
    handle_wifi_scan_usb();
    return;
  }

  if (0 == strcmp(type, "wifi.clear"))
  {
    clear_saved_wifi_credentials();
    WiFi.disconnect(true, true);
    g_wifi_connected = false;
    g_mqtt_connected = false;
    response["type"] = "wifi.clear.result";
    response["ok"] = true;
    serializeJson(response, Serial);
    Serial.print("\r\n");
    publish_status_lines_to_uart();
    g_status_dirty = true;
    return;
  }

  if (0 == strcmp(type, "wifi.set"))
  {
    ssid = doc["ssid"] | "";
    password = doc["password"] | "";
    if ('\0' == ssid[0])
    {
      response["type"] = "wifi.error";
      response["message"] = "ssid_required";
      serializeJson(response, Serial);
      Serial.print("\r\n");
      return;
    }

    save_wifi_credentials(ssid, password);
    WiFi.disconnect(false, false);
    g_wifi_connected = false;
    g_mqtt_connected = false;
    g_last_wifi_attempt_ms = 0U;
    begin_wifi_saved_credentials();
    response["type"] = "wifi.set.result";
    response["ok"] = true;
    response["ssid"] = g_saved_wifi_ssid;
    response["message"] = "saved_connecting";
    serializeJson(response, Serial);
    Serial.print("\r\n");
    publish_status_lines_to_uart();
    g_status_dirty = true;
    return;
  }

  response["type"] = "wifi.error";
  response["message"] = "unknown_command";
  serializeJson(response, Serial);
  Serial.print("\r\n");
}

void process_rx()
{
  while (kLinkUart.available() > 0)
  {
    int value = kLinkUart.read();
    if (value < 0)
    {
      return;
    }

    char ch = static_cast<char>(value);
    if ('\r' == ch)
    {
      continue;
    }

    if ('\n' == ch)
    {
      g_line_buffer[g_line_length] = '\0';
      handle_line(g_line_buffer);
      g_line_length = 0;
      continue;
    }

    if (g_line_length < (kLineBufferSize - 1))
    {
      g_line_buffer[g_line_length++] = ch;
    }
    else
    {
      g_fault_until_ms = millis() + kFaultHoldMs;
      g_line_length = 0;
    }
  }
}

void process_usb_provisioning()
{
  while (Serial.available() > 0)
  {
    int value = Serial.read();
    if (value < 0)
    {
      return;
    }

    char ch = static_cast<char>(value);
    if ('\r' == ch)
    {
      continue;
    }

    if ('\n' == ch)
    {
      g_usb_line_buffer[g_usb_line_length] = '\0';
      handle_usb_provisioning_line(g_usb_line_buffer);
      g_usb_line_length = 0U;
      continue;
    }

    if (g_usb_line_length < (kUsbLineBufferSize - 1U))
    {
      g_usb_line_buffer[g_usb_line_length++] = ch;
    }
    else
    {
      g_usb_line_length = 0U;
      publish_usb_line("{\"type\":\"wifi.error\",\"message\":\"line_too_long\"}");
    }
  }
}

void publish_status_lines_to_uart()
{
  char line[96];

  g_last_uart_status_ms = millis();
  publish_uart_line(g_wifi_connected ? "wifi:connected" : "wifi:disconnected");
  snprintf(line, sizeof(line), "wifi-ssid:%s", current_wifi_ssid());
  publish_uart_line(line);
  publish_uart_line(g_mqtt_connected ? "mqtt:connected" : "mqtt:disconnected");
  snprintf(line, sizeof(line), "device-id:%s", g_device_id);
  publish_uart_line(line);
}

void mqtt_callback(char * topic, byte * payload, unsigned int length)
{
  DynamicJsonDocument doc(4096);
  DeserializationError err;
  char buffer[kMqttScriptMessageBufferSize];

  if ((nullptr == topic) || (nullptr == payload) || (length >= sizeof(buffer)))
  {
    publish_input_status("mqtt oversize");
    return;
  }

  memcpy(buffer, payload, length);
  buffer[length] = '\0';
  err = deserializeJson(doc, buffer);
  if (err)
  {
    publish_input_status("mqtt parse");
    publish_usb_line(buffer);
    return;
  }

  (void) apply_deploy_message(doc.as<JsonVariantConst>());
}

void ensure_wifi()
{
  int profile_index = -1;
  uint32_t now = millis();

  if (WiFi.status() == WL_CONNECTED)
  {
    if (!g_wifi_connected)
    {
      g_wifi_connected = true;
      publish_status_lines_to_uart();
      g_status_dirty = true;
    }
    return;
  }

  if (g_wifi_connected)
  {
    g_wifi_connected = false;
    g_mqtt_connected = false;
    publish_status_lines_to_uart();
    g_status_dirty = true;
  }

  if ((now - g_last_wifi_attempt_ms) < kWifiRetryMs)
  {
    return;
  }

  g_last_wifi_attempt_ms = now;
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true, true);
  delay(100);

  if (g_saved_wifi_available)
  {
    begin_wifi_saved_credentials();
    return;
  }

  profile_index = pick_best_wifi_profile();
  if (profile_index >= 0)
  {
    begin_wifi_profile(profile_index);
    return;
  }

  begin_wifi_profile(0);
}

void ensure_mqtt()
{
  uint32_t now = millis();

  if (!g_wifi_connected)
  {
    return;
  }

  if (g_mqtt.connected())
  {
    if (!g_mqtt_connected)
    {
      g_mqtt_connected = true;
      publish_status_lines_to_uart();
      g_status_dirty = true;
      g_mqtt.subscribe(topic_script());
    }
    return;
  }

  if (g_mqtt_connected)
  {
    g_mqtt_connected = false;
    publish_status_lines_to_uart();
    g_status_dirty = true;
  }

  if ((now - g_last_mqtt_attempt_ms) < kMqttRetryMs)
  {
    return;
  }

  g_last_mqtt_attempt_ms = now;
  if (g_mqtt.connect(g_device_id, kMqttUser, kMqttPassword))
  {
    g_mqtt_connected = true;
    g_mqtt.subscribe(topic_script());
    publish_status_lines_to_uart();
    g_status_dirty = true;
  }
}

void publish_periodic()
{
  uint32_t now = millis();

  if (!g_mqtt_connected)
  {
    return;
  }

  if (g_status_dirty || ((now - g_last_status_ms) >= kStatusIntervalMs))
  {
    publish_status();
  }

  if (g_telemetry_dirty || ((now - g_last_telemetry_ms) >= kTelemetryIntervalMs))
  {
    publish_telemetry();
  }
}
}  // namespace

void setup()
{
  Serial.begin(kBaudRate);
  delay(200);
  reset_board_state_cache();
  g_wifi_preferences.begin("vela_wifi", false);
  WiFi.mode(WIFI_STA);
  load_device_identity();
  load_saved_wifi_credentials();

  init_status_led();
  kLinkUart.begin(kBaudRate, SERIAL_8N1, kRxPin, kTxPin);
  g_mqtt.setBufferSize(kMqttPacketBufferSize);
  g_mqtt.setServer(kMqttHost, kMqttPort);
  g_mqtt.setCallback(mqtt_callback);

  delay(100);
  publish_uart_line("esp32-ready");
  publish_status_lines_to_uart();
  update_status_led();
}

void loop()
{
  uint32_t now = millis();

  process_usb_provisioning();
  process_rx();
  ensure_wifi();
  ensure_time_sync();
  ensure_device_registration();
  ensure_mqtt();
  g_mqtt.loop();

  if ((now - g_last_heartbeat_ms) >= kHeartbeatIntervalMs)
  {
    g_last_heartbeat_ms = now;
    publish_uart_line("esp32-heartbeat");
  }

  if (g_uart_online && ((now - g_last_rx_ms) > kLinkActiveTimeoutMs))
  {
    g_uart_online = false;
    g_status_dirty = true;
  }

  if (g_uart_online && ((now - g_last_uart_status_ms) >= kUartStatusIntervalMs))
  {
    publish_status_lines_to_uart();
  }

  publish_periodic();
  update_status_led();
  delay(10);
}
