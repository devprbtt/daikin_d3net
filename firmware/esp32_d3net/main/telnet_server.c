#include "telnet_server.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"

static const char *TAG = "telnet_server";

typedef struct {
    app_context_t *app;
    int clients[4];
} telnet_ctx_t;

static telnet_ctx_t s_telnet = {
    .app = NULL,
    .clients = {-1, -1, -1, -1},
};

static void telnet_broadcast(const char *line, size_t len) {
    for (size_t i = 0; i < sizeof(s_telnet.clients) / sizeof(s_telnet.clients[0]); i++) {
        int fd = s_telnet.clients[i];
        if (fd < 0) {
            continue;
        }
        int r = send(fd, line, len, 0);
        if (r < 0) {
            close(fd);
            s_telnet.clients[i] = -1;
        }
    }
}

void telnet_server_logf(const char *fmt, ...) {
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n <= 0) {
        return;
    }

    size_t len = (size_t)n;
    if (len >= sizeof(buf) - 2U) {
        len = sizeof(buf) - 3U;
    }
    buf[len++] = '\r';
    buf[len++] = '\n';
    telnet_broadcast(buf, len);
}

static void telnet_status_task(void *arg) {
    (void)arg;
    while (true) {
        if (s_telnet.app != NULL && s_telnet.app->gateway_lock != NULL) {
            if (xSemaphoreTake(s_telnet.app->gateway_lock, pdMS_TO_TICKS(200)) == pdTRUE) {
                telnet_server_logf("units=%u", s_telnet.app->gateway.discovered_count);
                for (uint8_t i = 0; i < D3NET_MAX_UNITS; i++) {
                    d3net_unit_t *u = &s_telnet.app->gateway.units[i];
                    if (!u->present) {
                        continue;
                    }
                    telnet_server_logf(
                        "%s pwr=%d mode=%d set=%.1f cur=%.1f",
                        u->unit_id,
                        d3net_status_power_get(&u->status),
                        d3net_status_oper_mode_get(&u->status),
                        d3net_status_temp_setpoint_get(&u->status),
                        d3net_status_temp_current_get(&u->status));
                }
                xSemaphoreGive(s_telnet.app->gateway_lock);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

static void telnet_accept_task(void *arg) {
    (void)arg;
    struct sockaddr_in dest_addr = {
        .sin_family = AF_INET,
        .sin_port = htons(23),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };

    int listen_fd = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    if (listen_fd < 0) {
        ESP_LOGE(TAG, "socket failed");
        vTaskDelete(NULL);
        return;
    }
    int yes = 1;
    setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

    if (bind(listen_fd, (struct sockaddr *)&dest_addr, sizeof(dest_addr)) != 0) {
        ESP_LOGE(TAG, "bind failed");
        close(listen_fd);
        vTaskDelete(NULL);
        return;
    }
    if (listen(listen_fd, 4) != 0) {
        ESP_LOGE(TAG, "listen failed");
        close(listen_fd);
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "telnet server listening on port 23");

    while (true) {
        struct sockaddr_storage source_addr;
        socklen_t addr_len = sizeof(source_addr);
        int sock = accept(listen_fd, (struct sockaddr *)&source_addr, &addr_len);
        if (sock < 0) {
            continue;
        }

        size_t slot = sizeof(s_telnet.clients) / sizeof(s_telnet.clients[0]);
        for (size_t i = 0; i < sizeof(s_telnet.clients) / sizeof(s_telnet.clients[0]); i++) {
            if (s_telnet.clients[i] < 0) {
                slot = i;
                break;
            }
        }

        if (slot >= sizeof(s_telnet.clients) / sizeof(s_telnet.clients[0])) {
            close(sock);
            continue;
        }

        s_telnet.clients[slot] = sock;
        const char *hello = "D3Net telnet connected\r\n";
        send(sock, hello, strlen(hello), 0);
    }
}

esp_err_t telnet_server_start(app_context_t *app) {
    if (app == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    s_telnet.app = app;
    xTaskCreate(telnet_accept_task, "telnet_accept", 4096, NULL, 5, NULL);
    xTaskCreate(telnet_status_task, "telnet_status", 4096, NULL, 4, NULL);
    return ESP_OK;
}
