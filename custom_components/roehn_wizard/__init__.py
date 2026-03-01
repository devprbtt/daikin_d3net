"""The Roehn Wizard integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_SCAN_INTERVAL, DOMAIN, MANUFACTURER, MODEL, PLATFORMS
from .coordinator import RoehnCoordinator
from .protocol import RoehnClient
from .resources import ResourcesIndex, load_resources_index


@dataclass(slots=True)
class RoehnRuntimeData:
    """Runtime state for one config entry."""

    coordinator: RoehnCoordinator
    resources: ResourcesIndex
    images_url_base: str


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Roehn Wizard from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    scan_interval = entry.data[CONF_SCAN_INTERVAL]

    client = RoehnClient(host=host, port=port, timeout=1.0)
    coordinator = RoehnCoordinator(
        hass=hass,
        entry=entry,
        client=client,
        update_interval_seconds=scan_interval,
    )
    resources = load_resources_index()
    images_url_base = ""

    try:
        await coordinator.async_config_entry_first_refresh()
        await coordinator.async_start_event_listener()
    except Exception as err:
        raise ConfigEntryNotReady(f"Unable to connect to Roehn processor at {host}:{port}") from err

    entry.runtime_data = RoehnRuntimeData(
        coordinator=coordinator,
        resources=resources,
        images_url_base=images_url_base,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Roehn Wizard entry."""
    runtime: RoehnRuntimeData = entry.runtime_data
    await runtime.coordinator.async_stop_event_listener()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def processor_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for the processor itself."""
    host = entry.data[CONF_HOST]
    name = entry.data[CONF_NAME]
    return DeviceInfo(
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=name,
        identifiers={(DOMAIN, f"{host}:{entry.data[CONF_PORT]}")},
    )


def module_device_info(
    entry: ConfigEntry,
    serial_hex: str,
    model: str,
    ext_model: str,
    hsnet_id: int,
) -> DeviceInfo:
    """Return device info for a module connected to the processor."""
    base_name = ext_model or model or f"Module {serial_hex}"
    module_name = f"{base_name} HSNET {hsnet_id}"
    return DeviceInfo(
        manufacturer=MANUFACTURER,
        model=module_name,
        name=module_name,
        identifiers={(DOMAIN, f"module:{serial_hex}")},
        via_device=(DOMAIN, f"{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}"),
    )
