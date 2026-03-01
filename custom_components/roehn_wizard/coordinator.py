"""Coordinator for Roehn Wizard integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .protocol import BiosInfo, DeviceInfo, ProcessorInfo, RoehnClient

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RoehnSnapshot:
    processor: ProcessorInfo | None
    bios: BiosInfo | None
    devices: list[DeviceInfo]


class RoehnCoordinator(DataUpdateCoordinator[RoehnSnapshot]):
    """Fetches and caches Roehn processor data."""

    def __init__(
        self,
        hass,
        entry: ConfigEntry,
        client: RoehnClient,
        update_interval_seconds: int,
    ) -> None:
        self.client = client
        self.entry = entry
        self._button_states: dict[tuple[int, int], str] = {}
        self._button_last_changed: dict[tuple[int, int], datetime] = {}
        self._button_listeners: list[Callable[[int, int, str], None]] = []
        self._event_listener_task: asyncio.Task | None = None
        self._event_listener_running = False
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            update_interval=timedelta(seconds=update_interval_seconds),
            always_update=True,
        )

    async def _async_update_data(self) -> RoehnSnapshot:
        try:
            processor, bios, devices = await asyncio.gather(
                asyncio.to_thread(self.client.query_processor_discovery_info),
                asyncio.to_thread(self.client.query_processor_bios_info),
                asyncio.to_thread(self.client.query_devices),
            )
        except Exception as err:  # pragma: no cover - safety net for network errors
            raise UpdateFailed(str(err)) from err

        if processor is None and bios is None and not devices:
            raise UpdateFailed("No response from Roehn processor")

        return RoehnSnapshot(processor=processor, bios=bios, devices=devices)

    async def async_set_load(self, device_address: int, channel: int, level: int) -> int | None:
        """Set load level through command interface."""
        return await self.hass.async_add_executor_job(
            self.client.set_load,
            device_address,
            channel,
            level,
        )

    async def async_query_load(self, device_address: int, channel: int) -> int | None:
        """Read load level through command interface."""
        return await self.hass.async_add_executor_job(
            self.client.query_load,
            device_address,
            channel,
        )

    async def async_shade_up(self, device_address: int, channel: int) -> int | None:
        """Move shade up."""
        return await self.hass.async_add_executor_job(
            self.client.shade_up,
            device_address,
            channel,
        )

    async def async_shade_down(self, device_address: int, channel: int) -> int | None:
        """Move shade down."""
        return await self.hass.async_add_executor_job(
            self.client.shade_down,
            device_address,
            channel,
        )

    async def async_shade_stop(self, device_address: int, channel: int) -> int | None:
        """Stop shade movement."""
        return await self.hass.async_add_executor_job(
            self.client.shade_stop,
            device_address,
            channel,
        )

    async def async_shade_set(self, device_address: int, channel: int, level: int) -> int | None:
        """Set shade level 0..100."""
        return await self.hass.async_add_executor_job(
            self.client.shade_set,
            device_address,
            channel,
            level,
        )

    async def async_start_event_listener(self) -> None:
        """Start async listener for live telnet events."""
        if self._event_listener_task is not None:
            return
        self._event_listener_running = True
        self._event_listener_task = self.hass.loop.create_task(self._async_event_listener_loop())

    async def async_stop_event_listener(self) -> None:
        """Stop async listener for live telnet events."""
        self._event_listener_running = False
        if self._event_listener_task is None:
            return
        self._event_listener_task.cancel()
        try:
            await self._event_listener_task
        except asyncio.CancelledError:
            pass
        finally:
            self._event_listener_task = None

    def async_add_button_listener(self, listener: Callable[[int, int, str], None]) -> CALLBACK_TYPE:
        """Register callback for keypad button events."""
        self._button_listeners.append(listener)

        def _remove_listener() -> None:
            if listener in self._button_listeners:
                self._button_listeners.remove(listener)

        return _remove_listener

    def get_button_state(self, device_address: int, button_id: int) -> str | None:
        """Return last known action for keypad button."""
        return self._button_states.get((device_address, button_id))

    def get_button_last_changed(self, device_address: int, button_id: int) -> datetime | None:
        """Return UTC timestamp for last keypad button event."""
        return self._button_last_changed.get((device_address, button_id))

    async def _async_event_listener_loop(self) -> None:
        while self._event_listener_running:
            writer = None
            try:
                reader, writer = await asyncio.open_connection(
                    self.client.host,
                    self.client.command_port,
                )
                _LOGGER.debug("Connected Roehn event listener to %s:%s", self.client.host, self.client.command_port)

                while self._event_listener_running:
                    raw_line = await reader.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("ascii", errors="ignore").strip()
                    if not line:
                        continue
                    self._handle_event_line(line)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # pragma: no cover - network safety net
                _LOGGER.debug("Roehn event listener disconnected: %s", err)
            finally:
                if writer is not None:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:  # pragma: no cover
                        pass
            if self._event_listener_running:
                await asyncio.sleep(2)

    def _handle_event_line(self, line: str) -> None:
        parsed = _parse_button_event_line(line)
        if parsed is None:
            return
        device_address, button_id, action = parsed
        key = (device_address, button_id)
        self._button_states[key] = action
        self._button_last_changed[key] = datetime.now(timezone.utc)
        for listener in list(self._button_listeners):
            try:
                listener(device_address, button_id, action)
            except Exception:  # pragma: no cover - listener safety net
                _LOGGER.exception("Keypad button listener failure")


def _parse_button_event_line(line: str) -> tuple[int, int, str] | None:
    """Parse event like R:BTN PRESS <device_id> <button_id>."""
    if not line.startswith("R:BTN "):
        return None
    parts = line.split()
    if len(parts) < 4:
        return None
    action = parts[1].upper()
    if action not in {"PRESS", "RELEASE", "HOLD", "DOUBLE"}:
        return None
    try:
        device_address = int(parts[2])
        button_id = int(parts[3])
    except ValueError:
        return None
    if device_address <= 0 or button_id <= 0:
        return None
    return device_address, button_id, action
