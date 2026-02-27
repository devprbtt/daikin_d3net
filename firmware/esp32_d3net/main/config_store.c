#include "config_store.h"

#include <string.h>

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "modbus_rtu.h"

static const char *TAG = "config_store";

static void set_rtu_defaults(app_config_t *cfg) {
    cfg->rtu_cfg.uart_num = UART_NUM_1;
    cfg->rtu_cfg.tx_pin = 17;
    cfg->rtu_cfg.rx_pin = 16;
    cfg->rtu_cfg.de_pin = 4;
    cfg->rtu_cfg.re_pin = 5;
    cfg->rtu_cfg.baud_rate = 19200;
    cfg->rtu_cfg.data_bits = 8;
    cfg->rtu_cfg.stop_bits = 2;
    cfg->rtu_cfg.parity = 'N';
    cfg->rtu_cfg.slave_id = 1;
    cfg->rtu_cfg.timeout_ms = 3000;
}

esp_err_t config_store_load(app_config_t *cfg) {
    if (cfg == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(cfg, 0, sizeof(*cfg));
    set_rtu_defaults(cfg);

    nvs_handle_t nvs = 0;
    esp_err_t err = nvs_open("d3net", NVS_READONLY, &nvs);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    if (err != ESP_OK) {
        return err;
    }

    size_t ssid_len = sizeof(cfg->sta_ssid);
    err = nvs_get_str(nvs, "sta_ssid", cfg->sta_ssid, &ssid_len);
    if (err != ESP_OK) {
        nvs_close(nvs);
        return ESP_OK;
    }

    size_t pass_len = sizeof(cfg->sta_password);
    err = nvs_get_str(nvs, "sta_pass", cfg->sta_password, &pass_len);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        cfg->sta_password[0] = '\0';
        err = ESP_OK;
    }
    if (err == ESP_OK) {
        cfg->sta_configured = cfg->sta_ssid[0] != '\0';
    }

    uint64_t mask = 0;
    size_t ids_len = sizeof(cfg->registered_ids);
    if (nvs_get_u64(nvs, "reg_mask", &mask) == ESP_OK) {
        cfg->registered_mask = mask;
    }
    if (nvs_get_blob(nvs, "reg_ids", cfg->registered_ids, &ids_len) != ESP_OK || ids_len != sizeof(cfg->registered_ids)) {
        memset(cfg->registered_ids, 0, sizeof(cfg->registered_ids));
    }

    size_t rtu_len = sizeof(cfg->rtu_cfg);
    if (nvs_get_blob(nvs, "rtu_cfg", &cfg->rtu_cfg, &rtu_len) != ESP_OK || rtu_len != sizeof(cfg->rtu_cfg)) {
        set_rtu_defaults(cfg);
    }
    nvs_close(nvs);
    return err;
}

esp_err_t config_store_save(const app_config_t *cfg) {
    if (cfg == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t nvs = 0;
    esp_err_t err = nvs_open("d3net", NVS_READWRITE, &nvs);
    if (err != ESP_OK) {
        return err;
    }

    err = nvs_set_str(nvs, "sta_ssid", cfg->sta_ssid);
    if (err == ESP_OK) {
        err = nvs_set_str(nvs, "sta_pass", cfg->sta_password);
    }
    if (err == ESP_OK) {
        err = nvs_set_u64(nvs, "reg_mask", cfg->registered_mask);
    }
    if (err == ESP_OK) {
        err = nvs_set_blob(nvs, "reg_ids", cfg->registered_ids, sizeof(cfg->registered_ids));
    }
    if (err == ESP_OK) {
        err = nvs_set_blob(nvs, "rtu_cfg", &cfg->rtu_cfg, sizeof(cfg->rtu_cfg));
    }
    if (err == ESP_OK) {
        err = nvs_commit(nvs);
    }
    nvs_close(nvs);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "saved Wi-Fi config for SSID '%s'", cfg->sta_ssid);
    }
    return err;
}
