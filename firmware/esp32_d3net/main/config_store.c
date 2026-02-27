#include "config_store.h"

#include <string.h>

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "config_store";

esp_err_t config_store_load(app_config_t *cfg) {
    if (cfg == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(cfg, 0, sizeof(*cfg));

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
        err = nvs_commit(nvs);
    }
    nvs_close(nvs);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "saved Wi-Fi config for SSID '%s'", cfg->sta_ssid);
    }
    return err;
}
