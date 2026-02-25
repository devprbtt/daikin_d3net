#include "web_server.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "config_store.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "telnet_server.h"
#include "wifi_manager.h"

static const char *TAG = "web_server";

static const char *INDEX_HTML =
    "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>D3Net ESP32</title><style>body{font-family:Verdana,sans-serif;background:#f4f7fb;color:#112;padding:16px}"
    "h2{margin:0 0 8px}.card{background:#fff;border-radius:12px;padding:12px;margin:10px 0;box-shadow:0 2px 8px rgba(0,0,0,.08)}"
    "button{padding:8px 12px;margin:4px}input,select{padding:8px;margin:4px;width:100%}.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}"
    ".meter{width:100%;height:16px;background:#ddd;border-radius:8px;overflow:hidden}.bar{height:16px;background:#25a16b;width:0%}</style></head><body>"
    "<h2>Daikin D3Net Controller</h2>"
    "<div class='card'><b>Wi-Fi</b><div id='wifi_status'>loading...</div><button onclick='scanWifi()'>Scan</button>"
    "<select id='ssid_select' onchange='ssid.value=this.value'><option value=''>Select scanned AP</option></select>"
    "<input id='ssid' placeholder='SSID'><input id='pass' placeholder='Password' type='password'><button onclick='connectWifi()'>Connect</button></div>"
    "<div class='card'><b>OTA Update</b><input id='fw' type='file'><button onclick='uploadFw()'>Upload</button>"
    "<div class='meter'><div id='ota_bar' class='bar'></div></div><div id='ota_status'>idle</div></div>"
    "<div class='card'><b>HVAC Units</b><button onclick='discover()'>Discover</button><div id='hvacs'></div></div>"
    "<script>"
    "async function j(u,o){let r=await fetch(u,o);return r.json()}"
    "async function refresh(){let s=await j('/api/status');document.getElementById('wifi_status').innerText=`STA:${s.wifi.connected?'connected':'disconnected'} ${s.wifi.ip||''}`;"
    "document.getElementById('ota_status').innerText=s.ota.message;let p=s.ota.total_bytes?Math.floor((100*s.ota.bytes_received)/s.ota.total_bytes):0;"
    "document.getElementById('ota_bar').style.width=p+'%';let h=await j('/api/hvac');renderHvacs(h.units)}"
    "function renderHvacs(units){let h='';for(let u of units){h+=`<div class='card'><b>${u.unit_id}</b> mode=${u.mode} power=${u.power} cur=${u.temp_current} set=${u.temp_setpoint}"
    "<div class='row'><button onclick=\"cmd(${u.index},'power',1)\">ON</button><button onclick=\"cmd(${u.index},'power',0)\">OFF</button></div>"
    "<div class='row'><input id='sp_${u.index}' placeholder='Setpoint C'><button onclick=\"setpoint(${u.index})\">Set</button></div></div>`;} document.getElementById('hvacs').innerHTML=h||'No units';}"
    "async function scanWifi(){let r=await j('/api/wifi/scan');let s=document.getElementById('ssid_select');s.innerHTML='';if(!r.items||!r.items.length){let o=document.createElement('option');o.value='';o.text='No APs found';s.appendChild(o);return;}let p=document.createElement('option');p.value='';p.text='Select scanned AP';s.appendChild(p);for(let ap of r.items){let o=document.createElement('option');o.value=ap.ssid;o.text=`${ap.ssid} (RSSI ${ap.rssi})`;s.appendChild(o);}}"
    "async function connectWifi(){let selected=document.getElementById('ssid_select').value;let chosen=ssid.value||selected;await fetch('/api/wifi/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:chosen,password:pass.value})});setTimeout(refresh,1000)}"
    "async function discover(){await fetch('/api/discover',{method:'POST'});setTimeout(refresh,500)}"
    "async function cmd(i,c,v){await fetch('/api/hvac/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:i,cmd:c,value:v})});setTimeout(refresh,300)}"
    "async function setpoint(i){let v=parseFloat(document.getElementById('sp_'+i).value);await fetch('/api/hvac/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:i,cmd:'setpoint',value:v})});setTimeout(refresh,300)}"
    "async function uploadFw(){let f=document.getElementById('fw').files[0];if(!f)return;await fetch('/api/ota',{method:'POST',body:f});setTimeout(refresh,500)}"
    "setInterval(refresh,2000);refresh();"
    "</script></body></html>";

static esp_err_t http_reply_json(httpd_req_t *req, cJSON *root) {
    char *body = cJSON_PrintUnformatted(root);
    if (body == NULL) {
        cJSON_Delete(root);
        return ESP_ERR_NO_MEM;
    }
    httpd_resp_set_type(req, "application/json");
    esp_err_t err = httpd_resp_sendstr(req, body);
    free(body);
    cJSON_Delete(root);
    return err;
}

static int recv_body(httpd_req_t *req, char **out, size_t *out_len) {
    if (req->content_len <= 0) {
        *out = NULL;
        *out_len = 0;
        return ESP_OK;
    }
    char *buf = calloc(1, (size_t)req->content_len + 1U);
    if (buf == NULL) {
        return ESP_ERR_NO_MEM;
    }
    int total = 0;
    while (total < req->content_len) {
        int r = httpd_req_recv(req, buf + total, req->content_len - total);
        if (r <= 0) {
            free(buf);
            return ESP_FAIL;
        }
        total += r;
    }
    *out = buf;
    *out_len = (size_t)total;
    return ESP_OK;
}

static esp_err_t handle_index_get(httpd_req_t *req) {
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t handle_status_get(httpd_req_t *req) {
    app_context_t *app = (app_context_t *)req->user_ctx;
    char ip[32] = {0};
    wifi_manager_sta_ip(ip, sizeof(ip));

    cJSON *root = cJSON_CreateObject();
    cJSON *wifi = cJSON_CreateObject();
    cJSON_AddBoolToObject(wifi, "connected", wifi_manager_sta_connected());
    cJSON_AddStringToObject(wifi, "ip", ip);
    cJSON_AddItemToObject(root, "wifi", wifi);

    cJSON *ota = cJSON_CreateObject();
    cJSON_AddBoolToObject(ota, "active", app->ota.active);
    cJSON_AddBoolToObject(ota, "success", app->ota.success);
    cJSON_AddNumberToObject(ota, "bytes_received", (double)app->ota.bytes_received);
    cJSON_AddNumberToObject(ota, "total_bytes", (double)app->ota.total_bytes);
    cJSON_AddStringToObject(ota, "message", app->ota.message);
    cJSON_AddItemToObject(root, "ota", ota);

    return http_reply_json(req, root);
}

static esp_err_t handle_wifi_scan_get(httpd_req_t *req) {
    wifi_scan_item_t items[20];
    size_t count = 0;
    esp_err_t err = wifi_manager_scan(items, 20, &count);
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "scan failed");
        return err;
    }

    cJSON *root = cJSON_CreateObject();
    cJSON *arr = cJSON_CreateArray();
    for (size_t i = 0; i < count; i++) {
        cJSON *item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "ssid", items[i].ssid);
        cJSON_AddNumberToObject(item, "rssi", items[i].rssi);
        cJSON_AddNumberToObject(item, "auth", items[i].authmode);
        cJSON_AddItemToArray(arr, item);
    }
    cJSON_AddItemToObject(root, "items", arr);
    return http_reply_json(req, root);
}

static esp_err_t handle_wifi_connect_post(httpd_req_t *req) {
    app_context_t *app = (app_context_t *)req->user_ctx;
    char *body = NULL;
    size_t body_len = 0;
    if (recv_body(req, &body, &body_len) != ESP_OK || body == NULL) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "body");
        return ESP_FAIL;
    }
    cJSON *json = cJSON_ParseWithLength(body, body_len);
    free(body);
    if (json == NULL) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "json");
        return ESP_FAIL;
    }

    cJSON *ssid = cJSON_GetObjectItem(json, "ssid");
    cJSON *pass = cJSON_GetObjectItem(json, "password");
    if (!cJSON_IsString(ssid) || ssid->valuestring == NULL) {
        cJSON_Delete(json);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "ssid");
        return ESP_FAIL;
    }

    esp_err_t err = wifi_manager_connect_sta(ssid->valuestring, cJSON_IsString(pass) ? pass->valuestring : "");
    if (err == ESP_OK) {
        strncpy(app->config.sta_ssid, ssid->valuestring, sizeof(app->config.sta_ssid) - 1U);
        if (cJSON_IsString(pass) && pass->valuestring != NULL) {
            strncpy(app->config.sta_password, pass->valuestring, sizeof(app->config.sta_password) - 1U);
        } else {
            app->config.sta_password[0] = '\0';
        }
        app->config.sta_configured = true;
        config_store_save(&app->config);
    }
    cJSON_Delete(json);

    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "connect failed");
        return err;
    }
    return httpd_resp_sendstr(req, "{\"ok\":true}");
}

static esp_err_t handle_hvac_get(httpd_req_t *req) {
    app_context_t *app = (app_context_t *)req->user_ctx;
    cJSON *root = cJSON_CreateObject();
    cJSON *arr = cJSON_CreateArray();

    if (xSemaphoreTake(app->gateway_lock, pdMS_TO_TICKS(2000)) == pdTRUE) {
        for (uint8_t i = 0; i < D3NET_MAX_UNITS; i++) {
            d3net_unit_t *u = &app->gateway.units[i];
            if (!u->present) {
                continue;
            }
            cJSON *item = cJSON_CreateObject();
            cJSON_AddNumberToObject(item, "index", u->index);
            cJSON_AddStringToObject(item, "unit_id", u->unit_id);
            cJSON_AddBoolToObject(item, "power", d3net_status_power_get(&u->status));
            cJSON_AddNumberToObject(item, "mode", d3net_status_oper_mode_get(&u->status));
            cJSON_AddNumberToObject(item, "temp_current", d3net_status_temp_current_get(&u->status));
            cJSON_AddNumberToObject(item, "temp_setpoint", d3net_status_temp_setpoint_get(&u->status));
            cJSON_AddItemToArray(arr, item);
        }
        xSemaphoreGive(app->gateway_lock);
    }

    cJSON_AddItemToObject(root, "units", arr);
    return http_reply_json(req, root);
}

static esp_err_t handle_discover_post(httpd_req_t *req) {
    app_context_t *app = (app_context_t *)req->user_ctx;
    esp_err_t err = ESP_FAIL;
    if (xSemaphoreTake(app->gateway_lock, pdMS_TO_TICKS(5000)) == pdTRUE) {
        err = d3net_gateway_discover_units(&app->gateway);
        xSemaphoreGive(app->gateway_lock);
    }
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "discover failed");
        return err;
    }
    telnet_server_logf("discovery complete: units=%u", app->gateway.discovered_count);
    return httpd_resp_sendstr(req, "{\"ok\":true}");
}

static esp_err_t handle_hvac_cmd_post(httpd_req_t *req) {
    app_context_t *app = (app_context_t *)req->user_ctx;
    char *body = NULL;
    size_t body_len = 0;
    if (recv_body(req, &body, &body_len) != ESP_OK || body == NULL) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "body");
        return ESP_FAIL;
    }
    cJSON *json = cJSON_ParseWithLength(body, body_len);
    free(body);
    if (json == NULL) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "json");
        return ESP_FAIL;
    }

    cJSON *idx = cJSON_GetObjectItem(json, "index");
    cJSON *cmd = cJSON_GetObjectItem(json, "cmd");
    cJSON *val = cJSON_GetObjectItem(json, "value");
    if (!cJSON_IsNumber(idx) || !cJSON_IsString(cmd)) {
        cJSON_Delete(json);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "fields");
        return ESP_FAIL;
    }
    int index = idx->valueint;
    if (index < 0 || index >= D3NET_MAX_UNITS) {
        cJSON_Delete(json);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "index");
        return ESP_FAIL;
    }

    esp_err_t err = ESP_FAIL;
    if (xSemaphoreTake(app->gateway_lock, pdMS_TO_TICKS(5000)) == pdTRUE) {
        d3net_unit_t *u = &app->gateway.units[index];
        if (!u->present) {
            err = ESP_ERR_NOT_FOUND;
        } else {
            uint64_t now_ms = (uint64_t)(esp_timer_get_time() / 1000ULL);
            if (strcmp(cmd->valuestring, "power") == 0 && cJSON_IsNumber(val)) {
                err = d3net_unit_set_power(&app->gateway, u, val->valuedouble > 0.5, now_ms);
            } else if (strcmp(cmd->valuestring, "mode") == 0 && cJSON_IsNumber(val)) {
                err = d3net_unit_set_mode(&app->gateway, u, (d3net_mode_t)val->valueint, now_ms);
            } else if (strcmp(cmd->valuestring, "setpoint") == 0 && cJSON_IsNumber(val)) {
                err = d3net_unit_set_setpoint(&app->gateway, u, (float)val->valuedouble, now_ms);
            } else if (strcmp(cmd->valuestring, "fan_speed") == 0 && cJSON_IsNumber(val)) {
                err = d3net_unit_set_fan_speed(&app->gateway, u, (d3net_fan_speed_t)val->valueint, now_ms);
            } else if (strcmp(cmd->valuestring, "fan_dir") == 0 && cJSON_IsNumber(val)) {
                err = d3net_unit_set_fan_dir(&app->gateway, u, (d3net_fan_dir_t)val->valueint, now_ms);
            } else if (strcmp(cmd->valuestring, "filter_reset") == 0) {
                err = d3net_unit_filter_reset(&app->gateway, u, now_ms);
            } else {
                err = ESP_ERR_INVALID_ARG;
            }
        }
        xSemaphoreGive(app->gateway_lock);
    }
    cJSON_Delete(json);

    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "command failed");
        return err;
    }
    telnet_server_logf("hvac command ok");
    return httpd_resp_sendstr(req, "{\"ok\":true}");
}

static esp_err_t handle_ota_post(httpd_req_t *req) {
    app_context_t *app = (app_context_t *)req->user_ctx;
    app->ota.active = true;
    app->ota.success = false;
    app->ota.bytes_received = 0;
    app->ota.total_bytes = (size_t)req->content_len;
    strncpy(app->ota.message, "OTA receiving", sizeof(app->ota.message) - 1U);

    const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
    if (update_partition == NULL) {
        strncpy(app->ota.message, "No OTA partition", sizeof(app->ota.message) - 1U);
        app->ota.active = false;
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "partition");
        return ESP_FAIL;
    }

    esp_ota_handle_t ota_handle = 0;
    esp_err_t err = esp_ota_begin(update_partition, OTA_SIZE_UNKNOWN, &ota_handle);
    if (err != ESP_OK) {
        strncpy(app->ota.message, "OTA begin failed", sizeof(app->ota.message) - 1U);
        app->ota.active = false;
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "ota begin");
        return err;
    }

    char buf[1024];
    int remaining = req->content_len;
    while (remaining > 0) {
        int to_read = remaining > (int)sizeof(buf) ? (int)sizeof(buf) : remaining;
        int r = httpd_req_recv(req, buf, to_read);
        if (r <= 0) {
            esp_ota_abort(ota_handle);
            app->ota.active = false;
            strncpy(app->ota.message, "OTA read failed", sizeof(app->ota.message) - 1U);
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "ota read");
            return ESP_FAIL;
        }
        err = esp_ota_write(ota_handle, buf, (size_t)r);
        if (err != ESP_OK) {
            esp_ota_abort(ota_handle);
            app->ota.active = false;
            strncpy(app->ota.message, "OTA write failed", sizeof(app->ota.message) - 1U);
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "ota write");
            return err;
        }
        remaining -= r;
        app->ota.bytes_received += (size_t)r;
    }

    err = esp_ota_end(ota_handle);
    if (err == ESP_OK) {
        err = esp_ota_set_boot_partition(update_partition);
    }
    app->ota.active = false;
    app->ota.success = (err == ESP_OK);
    strncpy(app->ota.message, err == ESP_OK ? "OTA complete, rebooting" : "OTA finalize failed", sizeof(app->ota.message) - 1U);

    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "ota end");
        return err;
    }

    httpd_resp_sendstr(req, "{\"ok\":true,\"reboot\":true}");
    vTaskDelay(pdMS_TO_TICKS(1200));
    esp_restart();
    return ESP_OK;
}

esp_err_t web_server_start(app_context_t *app, httpd_handle_t *out_handle) {
    if (app == NULL || out_handle == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 16;
    config.stack_size = 8192;

    httpd_handle_t server = NULL;
    esp_err_t err = httpd_start(&server, &config);
    if (err != ESP_OK) {
        return err;
    }

    const httpd_uri_t routes[] = {
        {.uri = "/", .method = HTTP_GET, .handler = handle_index_get, .user_ctx = app},
        {.uri = "/api/status", .method = HTTP_GET, .handler = handle_status_get, .user_ctx = app},
        {.uri = "/api/wifi/scan", .method = HTTP_GET, .handler = handle_wifi_scan_get, .user_ctx = app},
        {.uri = "/api/wifi/connect", .method = HTTP_POST, .handler = handle_wifi_connect_post, .user_ctx = app},
        {.uri = "/api/hvac", .method = HTTP_GET, .handler = handle_hvac_get, .user_ctx = app},
        {.uri = "/api/discover", .method = HTTP_POST, .handler = handle_discover_post, .user_ctx = app},
        {.uri = "/api/hvac/cmd", .method = HTTP_POST, .handler = handle_hvac_cmd_post, .user_ctx = app},
        {.uri = "/api/ota", .method = HTTP_POST, .handler = handle_ota_post, .user_ctx = app},
    };

    for (size_t i = 0; i < sizeof(routes) / sizeof(routes[0]); i++) {
        err = httpd_register_uri_handler(server, &routes[i]);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "handler register failed for %s", routes[i].uri);
        }
    }

    *out_handle = server;
    ESP_LOGI(TAG, "web server started");
    return ESP_OK;
}
