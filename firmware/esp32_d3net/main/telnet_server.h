#pragma once

#include "esp_err.h"

#include "app_context.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t telnet_server_start(app_context_t *app);
void telnet_server_logf(const char *fmt, ...);

#ifdef __cplusplus
}
#endif
