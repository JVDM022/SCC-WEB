#include <ctype.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "driver/uart.h"
#include "esp_crt_bundle.h"
#include "esp_eap_client.h"
#include "esp_event.h"
#include "esp_https_ota.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "wifi_credentials_local.h"

#ifndef WIFI_SSID
#error "Define WIFI_SSID in wifi_credentials_local.h"
#endif
#ifndef EAP_USERNAME
#error "Define EAP_USERNAME in wifi_credentials_local.h"
#endif
#ifndef EAP_PASSWORD
#error "Define EAP_PASSWORD in wifi_credentials_local.h"
#endif
#ifndef EAP_IDENTITY
#define EAP_IDENTITY ""
#endif

#ifndef WIFI_CONNECT_TIMEOUT_MS
#define WIFI_CONNECT_TIMEOUT_MS 20000U
#endif
#ifndef WIFI_RETRY_DELAY_MS
#define WIFI_RETRY_DELAY_MS 10000U
#endif

#ifndef TELEMETRY_URL
#define TELEMETRY_URL ""
#endif
#ifndef COMMAND_URL
#define COMMAND_URL ""
#endif
#ifndef OTA_FIRMWARE_URL
#define OTA_FIRMWARE_URL ""
#endif
#ifndef OTA_CHECK_ON_BOOT
#define OTA_CHECK_ON_BOOT 0
#endif

#define ESP32_RX2 16
#define ESP32_TX2 17
#define ARDUINO_BAUD 115200
#define UART_PORT UART_NUM_2
#define UART_RX_BUFFER_SIZE 1024

#define TELEMETRY_PERIOD_MS 2000U
#define COMMAND_PERIOD_MS 1000U

#define MAX_ARDUINO_LINE_LEN 128
#define MAX_HTTP_RESPONSE_LEN 768
#define MAX_CMD_TYPE_LEN 24
#define MAX_OTA_URL_LEN 320

#define WIFI_CONNECTED_BIT BIT0
#define RELAY_TASK_STACK_SIZE 8192
#define RELAY_TASK_PRIORITY 5

typedef struct {
  char *buffer;
  size_t max_len;
  size_t len;
} http_response_buffer_t;

static const char *TAG = "esp32-relay";
static EventGroupHandle_t s_wifi_event_group;
static bool s_wifi_connected = false;
static bool s_wifi_connecting = false;
static char s_last_arduino_line[MAX_ARDUINO_LINE_LEN] = "";
static long s_last_cmd_id_seen = -1;
static char s_http_get_response[MAX_HTTP_RESPONSE_LEN];
static char s_http_post_response[256];
static char s_telemetry_payload[320];
static char s_cmd_type[MAX_CMD_TYPE_LEN];
static char s_ota_url[MAX_OTA_URL_LEN];
static char s_cmd_line[48];
static bool s_have_temp = false;
static bool s_have_on = false;
static bool s_have_motor = false;
static bool s_have_heat = false;
static bool s_have_kill = false;
static bool s_have_uptime = false;
static uint32_t s_uart_rx_bytes = 0;
static uint32_t s_uart_rx_lines = 0;
static uint32_t s_last_uart_rx_log_ms = 0;
static float s_last_temp_c = 0.0f;
static int s_last_on = 0;
static int s_last_motor = 0;
static int s_last_heat = 0;
static int s_last_kill = 0;
static uint32_t s_last_uptime_s = 0;

static uint32_t now_ms(void) {
  return (uint32_t)(esp_timer_get_time() / 1000ULL);
}

static void copy_cstr(char *dest, size_t dest_len, const char *src) {
  if (dest_len == 0) {
    return;
  }
  if (src == NULL) {
    dest[0] = '\0';
    return;
  }
  strncpy(dest, src, dest_len - 1);
  dest[dest_len - 1] = '\0';
}

static void trim_inplace(char *s) {
  size_t len;
  size_t i;
  size_t start = 0;

  if (s == NULL) {
    return;
  }

  len = strlen(s);
  while (start < len && isspace((unsigned char)s[start])) {
    start++;
  }
  if (start > 0) {
    memmove(s, s + start, len - start + 1);
  }

  len = strlen(s);
  for (i = len; i > 0; i--) {
    if (!isspace((unsigned char)s[i - 1])) {
      break;
    }
    s[i - 1] = '\0';
  }
}

static bool parse_status_flag(const char *value, int *out) {
  char token[16];
  size_t i = 0;

  if (value == NULL || out == NULL) {
    return false;
  }

  while (value[i] != '\0' && value[i] != ',' && !isspace((unsigned char)value[i]) && i < sizeof(token) - 1) {
    token[i] = (char)toupper((unsigned char)value[i]);
    i++;
  }
  token[i] = '\0';

  if (token[0] == '\0') {
    return false;
  }
  if (strcmp(token, "1") == 0 || strcmp(token, "ON") == 0 || strcmp(token, "TRUE") == 0 ||
      strcmp(token, "YES") == 0 || strcmp(token, "ACTIVE") == 0 || strcmp(token, "KILLED") == 0) {
    *out = 1;
    return true;
  }
  if (strcmp(token, "0") == 0 || strcmp(token, "OFF") == 0 || strcmp(token, "FALSE") == 0 ||
      strcmp(token, "NO") == 0 || strcmp(token, "INACTIVE") == 0 || strcmp(token, "CLEARED") == 0) {
    *out = 0;
    return true;
  }

  return false;
}

static bool extract_float_field(const char *line, const char *key, float *out) {
  const char *value;
  char *end_ptr;

  if (line == NULL || key == NULL || out == NULL) {
    return false;
  }

  value = strstr(line, key);
  if (value == NULL) {
    return false;
  }
  value += strlen(key);

  *out = strtof(value, &end_ptr);
  return end_ptr != value;
}

static bool extract_status_field(const char *line, const char *key, int *out) {
  const char *value;

  if (line == NULL || key == NULL || out == NULL) {
    return false;
  }

  value = strstr(line, key);
  if (value == NULL) {
    return false;
  }
  value += strlen(key);

  return parse_status_flag(value, out);
}

static bool parse_uptime_seconds(const char *value, uint32_t *out) {
  uint64_t total = 0;
  bool have_component = false;
  const char *cursor;

  if (value == NULL || out == NULL) {
    return false;
  }

  cursor = value;
  while (*cursor != '\0') {
    unsigned long component = 0;
    char *end_ptr;
    char unit;

    while (*cursor != '\0' && (isspace((unsigned char)*cursor) || *cursor == ',')) {
      cursor++;
    }
    if (*cursor == '\0') {
      break;
    }
    if (!isdigit((unsigned char)*cursor)) {
      return false;
    }

    component = strtoul(cursor, &end_ptr, 10);
    if (end_ptr == cursor) {
      return false;
    }

    unit = (char)tolower((unsigned char)*end_ptr);
    if (unit == 'd') {
      total += (uint64_t)component * 86400ULL;
      cursor = end_ptr + 1;
    } else if (unit == 'h') {
      total += (uint64_t)component * 3600ULL;
      cursor = end_ptr + 1;
    } else if (unit == 'm') {
      total += (uint64_t)component * 60ULL;
      cursor = end_ptr + 1;
    } else if (unit == 's') {
      total += (uint64_t)component;
      cursor = end_ptr + 1;
    } else if (unit == '\0' || unit == ',' || isspace((unsigned char)unit)) {
      total += (uint64_t)component;
      cursor = end_ptr;
    } else {
      return false;
    }

    have_component = true;
  }

  if (!have_component) {
    return false;
  }

  *out = (uint32_t)total;
  return true;
}

static bool extract_uptime_field(const char *line, const char *key, uint32_t *out) {
  const char *value;

  if (line == NULL || key == NULL || out == NULL) {
    return false;
  }

  value = strstr(line, key);
  if (value == NULL) {
    return false;
  }
  value += strlen(key);

  return parse_uptime_seconds(value, out);
}

static void update_arduino_snapshot_from_line(const char *line) {
  float temp_c = 0.0f;
  int status_value = 0;
  uint32_t uptime_s = 0;

  if (line == NULL || line[0] == '\0') {
    return;
  }

  if (extract_float_field(line, "T=", &temp_c) || extract_float_field(line, "TEMP=", &temp_c)) {
    s_last_temp_c = temp_c;
    s_have_temp = true;
  }

  if (extract_status_field(line, "ON=", &status_value) || extract_status_field(line, "HEAT=", &status_value)) {
    s_last_on = status_value;
    s_have_on = true;
  }

  if (extract_status_field(line, "MOTOR=", &status_value)) {
    s_last_motor = status_value;
    s_have_motor = true;
  }

  if (extract_status_field(line, "HEAT=", &status_value)) {
    s_last_heat = status_value;
    s_have_heat = true;
  }

  if (extract_status_field(line, "KILL=", &status_value)) {
    s_last_kill = status_value;
    s_have_kill = true;
  }

  if (extract_uptime_field(line, "UPTIME=", &uptime_s)) {
    s_last_uptime_s = uptime_s;
    s_have_uptime = true;
  }
}

static long extract_long_json(const char *json, const char *key) {
  char pattern[48];
  const char *key_pos;
  const char *colon;
  char *end_ptr;

  if (json == NULL || key == NULL) {
    return 0;
  }

  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  key_pos = strstr(json, pattern);
  if (key_pos == NULL) {
    return 0;
  }

  colon = strchr(key_pos, ':');
  if (colon == NULL) {
    return 0;
  }

  return strtol(colon + 1, &end_ptr, 10);
}

static bool extract_string_json(const char *json, const char *key, char *out, size_t out_len) {
  char pattern[48];
  const char *key_pos;
  const char *colon;
  const char *q1;
  const char *q2;
  size_t copy_len;

  if (json == NULL || key == NULL || out == NULL || out_len == 0) {
    return false;
  }

  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  key_pos = strstr(json, pattern);
  if (key_pos == NULL) {
    out[0] = '\0';
    return false;
  }

  colon = strchr(key_pos, ':');
  if (colon == NULL) {
    out[0] = '\0';
    return false;
  }

  q1 = strchr(colon, '"');
  if (q1 == NULL) {
    out[0] = '\0';
    return false;
  }
  q2 = strchr(q1 + 1, '"');
  if (q2 == NULL) {
    out[0] = '\0';
    return false;
  }

  copy_len = (size_t)(q2 - (q1 + 1));
  if (copy_len >= out_len) {
    copy_len = out_len - 1;
  }
  memcpy(out, q1 + 1, copy_len);
  out[copy_len] = '\0';
  return true;
}

static esp_err_t http_event_handler(esp_http_client_event_t *evt) {
  http_response_buffer_t *response = (http_response_buffer_t *)evt->user_data;

  if (evt->event_id == HTTP_EVENT_ON_DATA && response != NULL && evt->data_len > 0) {
    size_t free_space = 0;
    size_t copy_len = 0;

    if (response->max_len > response->len) {
      free_space = response->max_len - response->len - 1;
    }
    copy_len = (size_t)evt->data_len < free_space ? (size_t)evt->data_len : free_space;

    if (copy_len > 0) {
      memcpy(response->buffer + response->len, evt->data, copy_len);
      response->len += copy_len;
      response->buffer[response->len] = '\0';
    }
  }

  return ESP_OK;
}

static bool https_post_json(const char *url, const char *json_body) {
  s_http_post_response[0] = '\0';
  http_response_buffer_t response_buf = {
      .buffer = s_http_post_response,
      .max_len = sizeof(s_http_post_response),
      .len = 0,
  };
  esp_http_client_config_t config;
  esp_http_client_handle_t client;
  esp_err_t err;
  int status_code;

  if (!s_wifi_connected || url == NULL || url[0] == '\0' || json_body == NULL) {
    return false;
  }

  memset(&config, 0, sizeof(config));
  config.url = url;
  config.method = HTTP_METHOD_POST;
  config.timeout_ms = 10000;
  config.event_handler = http_event_handler;
  config.user_data = &response_buf;
  config.crt_bundle_attach = esp_crt_bundle_attach;

  client = esp_http_client_init(&config);
  if (client == NULL) {
    ESP_LOGE(TAG, "POST init failed");
    return false;
  }

  esp_http_client_set_header(client, "Content-Type", "application/json");
  esp_http_client_set_post_field(client, json_body, (int)strlen(json_body));

  err = esp_http_client_perform(client);
  status_code = esp_http_client_get_status_code(client);
  esp_http_client_cleanup(client);

  if (err != ESP_OK) {
    ESP_LOGE(TAG, "POST %s failed: %s", url, esp_err_to_name(err));
    return false;
  }

  ESP_LOGI(TAG, "POST %s -> %d | %s", url, status_code, s_http_post_response);
  return (status_code >= 200 && status_code < 300);
}

static bool https_get(const char *url, char *out_response, size_t out_len) {
  http_response_buffer_t response_buf;
  esp_http_client_config_t config;
  esp_http_client_handle_t client;
  esp_err_t err;
  int status_code;

  if (out_response == NULL || out_len == 0) {
    return false;
  }
  out_response[0] = '\0';

  if (!s_wifi_connected || url == NULL || url[0] == '\0') {
    return false;
  }

  response_buf.buffer = out_response;
  response_buf.max_len = out_len;
  response_buf.len = 0;

  memset(&config, 0, sizeof(config));
  config.url = url;
  config.method = HTTP_METHOD_GET;
  config.timeout_ms = 10000;
  config.event_handler = http_event_handler;
  config.user_data = &response_buf;
  config.crt_bundle_attach = esp_crt_bundle_attach;

  client = esp_http_client_init(&config);
  if (client == NULL) {
    ESP_LOGE(TAG, "GET init failed");
    return false;
  }

  err = esp_http_client_perform(client);
  status_code = esp_http_client_get_status_code(client);
  esp_http_client_cleanup(client);

  if (err != ESP_OK) {
    ESP_LOGE(TAG, "GET %s failed: %s", url, esp_err_to_name(err));
    return false;
  }

  ESP_LOGI(TAG, "GET %s -> %d | %s", url, status_code, out_response);
  return (status_code >= 200 && status_code < 300);
}

static void send_to_arduino(const char *cmd_line) {
  if (cmd_line == NULL || cmd_line[0] == '\0') {
    return;
  }

  uart_write_bytes(UART_PORT, cmd_line, strlen(cmd_line));
  uart_write_bytes(UART_PORT, "\n", 1);
  ESP_LOGI(TAG, "-> Arduino: %s", cmd_line);
}

static void read_arduino_lines(void) {
  uint8_t data[64];
  int bytes_read = uart_read_bytes(UART_PORT, data, sizeof(data), pdMS_TO_TICKS(10));
  static char line_buf[MAX_ARDUINO_LINE_LEN];
  static size_t line_len = 0;
  size_t i;
  char preview[33];
  size_t preview_len;

  if (bytes_read <= 0) {
    return;
  }

  s_uart_rx_bytes += (uint32_t)bytes_read;
  if ((now_ms() - s_last_uart_rx_log_ms) >= 2000U) {
    preview_len = (size_t)bytes_read < (sizeof(preview) - 1U) ? (size_t)bytes_read : (sizeof(preview) - 1U);
    for (i = 0; i < preview_len; i++) {
      preview[i] = isprint((unsigned char)data[i]) ? (char)data[i] : '.';
    }
    preview[preview_len] = '\0';
    ESP_LOGI(TAG, "UART2 rx: %d bytes (total=%lu, lines=%lu), preview=\"%s\"", bytes_read,
             (unsigned long)s_uart_rx_bytes, (unsigned long)s_uart_rx_lines, preview);
    s_last_uart_rx_log_ms = now_ms();
  }

  for (i = 0; i < (size_t)bytes_read; i++) {
    char c = (char)data[i];

    if (c == '\r' || c == '\n') {
      line_buf[line_len] = '\0';
      trim_inplace(line_buf);
      if (line_buf[0] != '\0') {
        copy_cstr(s_last_arduino_line, sizeof(s_last_arduino_line), line_buf);
        update_arduino_snapshot_from_line(s_last_arduino_line);
        s_uart_rx_lines++;
        ESP_LOGI(TAG, "<- Arduino: %s", s_last_arduino_line);
      }
      line_len = 0;
      continue;
    }

    if (line_len < sizeof(line_buf) - 1) {
      line_buf[line_len++] = c;
    } else {
      line_len = 0;
    }
  }
}

static void post_telemetry(void) {
  uint32_t ts = now_ms();
  char temp_field[32];
  char on_field[8];
  char motor_field[8];
  char heat_field[8];
  char kill_field[8];
  char uptime_field[24];

  if (s_have_temp) {
    snprintf(temp_field, sizeof(temp_field), "%.2f", s_last_temp_c);
  } else {
    copy_cstr(temp_field, sizeof(temp_field), "null");
  }

  if (s_have_on) {
    snprintf(on_field, sizeof(on_field), "%d", s_last_on);
  } else {
    copy_cstr(on_field, sizeof(on_field), "null");
  }

  if (s_have_motor) {
    snprintf(motor_field, sizeof(motor_field), "%d", s_last_motor);
  } else {
    copy_cstr(motor_field, sizeof(motor_field), "null");
  }

  if (s_have_heat) {
    snprintf(heat_field, sizeof(heat_field), "%d", s_last_heat);
  } else {
    copy_cstr(heat_field, sizeof(heat_field), "null");
  }

  if (s_have_kill) {
    snprintf(kill_field, sizeof(kill_field), "%d", s_last_kill);
  } else {
    copy_cstr(kill_field, sizeof(kill_field), "null");
  }

  if (s_have_uptime) {
    snprintf(uptime_field, sizeof(uptime_field), "%lu", (unsigned long)s_last_uptime_s);
  } else {
    copy_cstr(uptime_field, sizeof(uptime_field), "null");
  }

  snprintf(
      s_telemetry_payload,
      sizeof(s_telemetry_payload),
      "{\"temp\":%s,\"on\":%s,\"motor\":%s,\"heat\":%s,\"kill\":%s,\"uptime_s\":%s,\"ts\":%lu}",
      temp_field,
      on_field,
      motor_field,
      heat_field,
      kill_field,
      uptime_field,
      (unsigned long)ts);

  ESP_LOGI(TAG, "Telemetry payload: %s", s_telemetry_payload);
  https_post_json(TELEMETRY_URL, s_telemetry_payload);
}

static void perform_ota_update(const char *url) {
  esp_http_client_config_t http_config;
  esp_https_ota_config_t ota_config;
  esp_err_t err;

  if (url == NULL || url[0] == '\0') {
    ESP_LOGW(TAG, "OTA skipped: no URL configured");
    return;
  }
  if (!s_wifi_connected) {
    ESP_LOGW(TAG, "OTA skipped: WiFi is not connected");
    return;
  }

  memset(&http_config, 0, sizeof(http_config));
  http_config.url = url;
  http_config.timeout_ms = 20000;
  http_config.crt_bundle_attach = esp_crt_bundle_attach;

  memset(&ota_config, 0, sizeof(ota_config));
  ota_config.http_config = &http_config;

  ESP_LOGI(TAG, "Starting OTA update: %s", url);
  err = esp_https_ota(&ota_config);
  if (err == ESP_OK) {
    ESP_LOGI(TAG, "OTA update successful. Rebooting...");
    esp_restart();
    return;
  }

  ESP_LOGE(TAG, "OTA update failed: %s", esp_err_to_name(err));
}

static void poll_command_and_forward(void) {
  long cmd_id;
  long value;
  const char *selected_ota_url;

  s_http_get_response[0] = '\0';
  s_cmd_type[0] = '\0';
  s_ota_url[0] = '\0';

  if (!https_get(COMMAND_URL, s_http_get_response, sizeof(s_http_get_response))) {
    return;
  }

  trim_inplace(s_http_get_response);
  if (s_http_get_response[0] == '\0') {
    return;
  }

  cmd_id = extract_long_json(s_http_get_response, "cmdId");
  value = extract_long_json(s_http_get_response, "value");
  if (cmd_id <= 0 || !extract_string_json(s_http_get_response, "type", s_cmd_type, sizeof(s_cmd_type)) || s_cmd_type[0] == '\0') {
    return;
  }

  if (cmd_id == s_last_cmd_id_seen) {
    return;
  }
  s_last_cmd_id_seen = cmd_id;

  if (strcmp(s_cmd_type, "KILL") == 0) {
    snprintf(s_cmd_line, sizeof(s_cmd_line), "KILL %ld", value);
    s_last_kill = value != 0 ? 1 : 0;
    s_have_kill = true;
    send_to_arduino(s_cmd_line);
  } else if (strcmp(s_cmd_type, "SET_ON") == 0) {
    snprintf(s_cmd_line, sizeof(s_cmd_line), "SET_ON %ld", value);
    send_to_arduino(s_cmd_line);
  } else if (strcmp(s_cmd_type, "OTA") == 0) {
    selected_ota_url = OTA_FIRMWARE_URL;
    s_ota_url[0] = '\0';
    if (extract_string_json(s_http_get_response, "url", s_ota_url, sizeof(s_ota_url)) && s_ota_url[0] != '\0') {
      selected_ota_url = s_ota_url;
    }

    if (selected_ota_url == NULL || selected_ota_url[0] == '\0') {
      ESP_LOGW(TAG, "OTA command ignored: missing firmware URL");
      return;
    }

    perform_ota_update(selected_ota_url);
  } else {
    ESP_LOGW(TAG, "Unknown command type: %s", s_cmd_type);
  }
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data) {
  (void)arg;

  if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
    s_wifi_connecting = true;
    esp_wifi_connect();
    return;
  }

  if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
    s_wifi_connected = false;
    s_wifi_connecting = false;
    xEventGroupClearBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    ESP_LOGW(TAG, "WiFi disconnected");
    return;
  }

  if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
    ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
    wifi_ap_record_t ap_info;

    s_wifi_connected = true;
    s_wifi_connecting = false;
    xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);

    ESP_LOGI(TAG, "WiFi connected. IP: " IPSTR, IP2STR(&event->ip_info.ip));
    if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
      ESP_LOGI(TAG, "RSSI: %d dBm", ap_info.rssi);
    }
  }
}

static void init_uart(void) {
  uart_config_t uart_config = {
      .baud_rate = ARDUINO_BAUD,
      .data_bits = UART_DATA_8_BITS,
      .parity = UART_PARITY_DISABLE,
      .stop_bits = UART_STOP_BITS_1,
      .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
      .source_clk = UART_SCLK_DEFAULT,
  };

  ESP_ERROR_CHECK(uart_driver_install(UART_PORT, UART_RX_BUFFER_SIZE, 0, 0, NULL, 0));
  ESP_ERROR_CHECK(uart_param_config(UART_PORT, &uart_config));
  ESP_ERROR_CHECK(uart_set_pin(UART_PORT, ESP32_TX2, ESP32_RX2, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
  ESP_LOGI(TAG, "UART2 configured: TX=%d RX=%d baud=%d", ESP32_TX2, ESP32_RX2, ARDUINO_BAUD);
}

static void init_wifi_enterprise(void) {
  esp_event_handler_instance_t instance_any_id;
  esp_event_handler_instance_t instance_got_ip;
  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  wifi_config_t wifi_config = {0};
  const char *identity = EAP_IDENTITY;
  EventBits_t bits;

  if (identity[0] == '\0') {
    identity = EAP_USERNAME;
  }

  s_wifi_event_group = xEventGroupCreate();

  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();

  ESP_ERROR_CHECK(esp_wifi_init(&cfg));
  ESP_ERROR_CHECK(
      esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, &instance_any_id));
  ESP_ERROR_CHECK(
      esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, &instance_got_ip));

  copy_cstr((char *)wifi_config.sta.ssid, sizeof(wifi_config.sta.ssid), WIFI_SSID);
  wifi_config.sta.pmf_cfg.capable = true;
  wifi_config.sta.pmf_cfg.required = false;

  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));

  esp_eap_client_clear_ca_cert();
  ESP_ERROR_CHECK(esp_eap_client_set_identity((const uint8_t *)identity, strlen(identity)));
  ESP_ERROR_CHECK(esp_eap_client_set_username((const uint8_t *)EAP_USERNAME, strlen(EAP_USERNAME)));
  ESP_ERROR_CHECK(esp_eap_client_set_password((const uint8_t *)EAP_PASSWORD, strlen(EAP_PASSWORD)));
  ESP_ERROR_CHECK(esp_wifi_sta_enterprise_enable());
  s_wifi_connecting = true;

  ESP_ERROR_CHECK(esp_wifi_start());
  ESP_LOGI(TAG, "Connecting to WPA2-Enterprise WiFi: %s", WIFI_SSID);

  bits = xEventGroupWaitBits(s_wifi_event_group, WIFI_CONNECTED_BIT, pdFALSE, pdFALSE,
                             pdMS_TO_TICKS(WIFI_CONNECT_TIMEOUT_MS));
  if ((bits & WIFI_CONNECTED_BIT) == 0U) {
    ESP_LOGW(TAG, "WiFi connect timeout after %lu ms", (unsigned long)WIFI_CONNECT_TIMEOUT_MS);
  }
}


static void relay_task(void *arg) {
  uint32_t last_telemetry_ms = 0;
  uint32_t last_command_poll_ms = 0;
  uint32_t last_wifi_retry_ms = 0;
  uint32_t last_uart_idle_log_ms = 0;

  (void)arg;

  for (;;) {
    uint32_t now = now_ms();

    if (!s_wifi_connected && !s_wifi_connecting && (now - last_wifi_retry_ms) >= WIFI_RETRY_DELAY_MS) {
      last_wifi_retry_ms = now;
      s_wifi_connecting = true;
      ESP_LOGW(TAG, "WiFi disconnected. Reconnecting...");
      esp_wifi_connect();
    }

    read_arduino_lines();

    if ((now - last_uart_idle_log_ms) >= 5000U) {
      last_uart_idle_log_ms = now;
      if (s_uart_rx_bytes == 0U) {
        ESP_LOGW(TAG, "UART2 idle: no bytes received yet on RX=%d", ESP32_RX2);
      }
    }

    if ((now - last_telemetry_ms) >= TELEMETRY_PERIOD_MS) {
      last_telemetry_ms = now;
      post_telemetry();
    }

    if ((now - last_command_poll_ms) >= COMMAND_PERIOD_MS) {
      last_command_poll_ms = now;
      poll_command_and_forward();
    }

    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

void app_main(void) {
  esp_err_t ret;

  ret = nvs_flash_init();
  if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_ERROR_CHECK(nvs_flash_erase());
    ret = nvs_flash_init();
  }
  ESP_ERROR_CHECK(ret);

  init_uart();
  init_wifi_enterprise();

  if (OTA_CHECK_ON_BOOT != 0) {
    perform_ota_update(OTA_FIRMWARE_URL);
  }

  ESP_LOGI(TAG, "Ready: UART telemetry bridge + Azure HTTP polling + OTA");

  xTaskCreatePinnedToCore(relay_task, "relay_task", RELAY_TASK_STACK_SIZE, NULL, RELAY_TASK_PRIORITY, NULL, 1);
}
