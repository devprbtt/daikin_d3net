#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "d3net_gateway.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    bool active;
    bool success;
    char message[96];
    size_t bytes_received;
    size_t total_bytes;
} ota_state_t;

typedef struct {
    char sta_ssid[33];
    char sta_password[65];
    bool sta_configured;
} app_config_t;

typedef struct {
    d3net_gateway_t gateway;
    SemaphoreHandle_t gateway_lock;
    ota_state_t ota;
    app_config_t config;
} app_context_t;

#ifdef __cplusplus
}
#endif
