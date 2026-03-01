# Roehn Wizard Protocol Map (from Decompiled Sources)

This document summarizes protocol details extracted from:

- `G:\decompilation\hscommunicationlibrary\HsCommunicationLibrary`
- `G:\decompilation\hstransferprotocollibrary\HsTransferProtocolLibrary`

It is focused on building standalone integrations (network-side and hardware-side).

## 1) Transport and Frame Basics

### Common wire signature

- ASCII header at bytes `0..8`: `HSN_S-UDP`
- Seen in both libraries (`CallObject.DEFAULT_HEADER`, `CallbackObject.DEFAULT_HEADER`, `Upload.WriteBuffHeader`).

### Discovery/control channel (`HsCommunicationLibrary`)

- UDP
- Default port: `2006` (`CommunicationManager.DEFAULT_PORT`)
- Broadcast address used for discovery: `255.255.255.255`
- Per-session timeout handling:
  - timeout threshold: `5000 ms`
  - default retry count: `3`
  - managed by `CommunicationSessionControlThread`

### Upload/transfer channel (`HsTransferProtocolLibrary`)

- UDP
- Port is provided externally (`HsTransfer.SetConnection(ip, port)`)
- Uses the same `HSN_S-UDP` header, but different group/opcode handling in bytes `9+`.

## 2) Communication API Command IDs (Calls/Callbacks)

Mapping from `CallbackManager.GenerateCallBackObject(...)`:

| Header_0 | Header_1 | Meaning / callback |
|---|---:|---|
| `3` | `0` | `GetProcessorsOnNetworkCallbackObject` |
| `100` | `1` | `GetConnectedDevicesOnProcessorCallbackObject` |
| `10` | `3` | `PrepareDownloadProjectFromProcessorCallbackObject` |
| `10` | `2` | `GetDownloadPackgeSliceCallbackObject` |
| `205` | `1` | `GetLearnableLightsCallbackObject` |
| `206` | `0` | `GetFastLoadStatusCallbackObject` |
| `4` | `9` | `GetBIOSVersionCallbackObject` |
| `3` | `123` | `ChangeProcessorIPCallbackObject` |
| `207` | `0` | `CancelRandomSearchCallbackObject` |
| `207` | `1` | `StartRandomSearchCallbackObject` |
| `207` | `3` | `EnablePressToShowCallbackObject` |
| `207` | `4` | `DisablePressToShowCallbackObject` |
| `207` | `5` | `ChangeDeviceAddressCallbackObject` |
| `1` | `7` | `RestartNetworkCallbackObject` |
| `0` | `0` | `IdentifyModuleBySerialNumberCallbackObject` |

## 3) Core Packet Layouts

## 3.1 Discover processors

Source:

- `Calls/GetProcessorsOnNetworkCallObject.cs`
- `Callbacks/GetProcessorsOnNetworkCallbackObject.cs`

Request (`13 bytes`):

- `[0..8]` = `HSN_S-UDP`
- `[9]` = `0x03`
- `[10]` = `0x00`
- `[11]` = `0x00`
- `[12]` = `0x00`

Response parse highlights:

- Checks `[9]=0x03`, `[10]=0x00`
- Name C-string starts at offset `12`
- If length `>=82`, parser reads:
  - version at `32..35`
  - serial at `42..57` (C-string, max 16)
  - IP at `62..65`
  - mask at `66..69`
  - gateway at `70..73`
  - MAC at `74..79`

## 3.2 Enumerate devices connected to a processor

Source:

- `Calls/GetConnectDevicesOnProcessorCallObject.cs`
- `Callbacks/GetConnectedDevicesOnProcessorCallbackObject.cs`

Request (`14 bytes`):

- `[9]=100`, `[10]=1`
- `[11..12]` = `ReadIndex` little-endian
- `[13]=0`

Response:

- `headerLength = data[12]`
- `registerLength = data[13]`
- `registersQty = data[14]`
- register records begin at:
  - `registerInitialPos = 9 + 3 + headerLength + k * registerLength`
- key record fields:
  - status, port, hsnet id, device id, model ids/fw
  - model string (7 bytes), extended model string (10 bytes)
  - 6-byte serial
  - CRC, EEPROM address, bitmap
- pagination:
  - if `registersQty >= 24`, callback creates next call with `ReadIndex + registersQty`

## 3.3 Change processor IP/mask/gateway

Source:

- `Calls/ChangeProcessorIPCallObject.cs`
- `Callbacks/ChangeProcessorIPCallbackObject.cs`

Request (`44 bytes`):

- `[9]=3`, `[10]=123`, `[11]=0`
- serial ASCII starts at `[12]`
- network fields begin at `[28]`:
  - old IP `[28..31]`
  - new IP `[32..35]`
  - new mask `[36..39]`
  - new gateway `[40..43]`

Callback parses the same offsets and reports old/new addressing info.

## 3.4 Identify module by serial number (beep/blink)

Source:

- `Calls/IdentifyModuleBySerialNumberCallObject.cs`
- `Callbacks/IdentifyModuleBySerialNumberCallbackObject.cs`

Request (`28 bytes`):

- `[9]=1`, `[10]=1`, `[11]=0`
- then fixed command payload:
  - `[12]=16`, `[13]=125`, `[14]=1`, `[15]=255`, `[16]=0`
  - serial bytes `[17..22]` (6 bytes)
  - `[23]=4`, `[24]=238`, `[25]=0`, `[26]=0`
  - `[27]=1|0` (`beep/blink`)

Behavior:

- retriggerable call every `300 ms` until stopped.
- callback manager also maps ack `0,0` to identify callback.

## 3.5 Download project image slices

Source:

- `Calls/PrepareDownloadProjectFromProcessorCallObject.cs`
- `Calls/GetDownloadPackageSliceCallObject.cs`
- `Callbacks/GetDownloadPackgeSliceCallbackObject.cs`

Prepare request (`15 bytes`):

- `[9]=10`, `[10]=3`, `[11]=0`, `[12]=2`, `[13..14]=blockId LE`

Slice request (`16 bytes`):

- `[9]=10`, `[10]=2`, `[11]=0`
- `[12..13]=addr LE` where `addr = stateRx * 512`
- `[14..15]=size LE` where `size = 512`

Slice callback:

- decodes `addr` from `[12..13]`, size from `[14..15]`
- payload starts at `[16]`
- reconstructs project header and full project buffer across chained calls.

## 4) Upload/Transfer Protocol (HsTransferProtocolLibrary)

Key constants (`Defines.cs`):

- `S_ID = "HSN_S-UDP"`
- `GP_PACKAGE = 10`
- `GP_UPLOAD = 1`
- `GP_DOWNLOAD = 2`
- `GP_COMMAND = 3`
- `GP_NOTIFY = 4`
- `GP_TIMEOUT = 50`
- `FASTLOAD_BLOCK = 351`

Base sender (`Protocols/Upload.cs`):

- `SendCommand(cmd, blockId)` writes:
  - `[9]=10`, `[10]=3`, `[11]=0`, `[12]=cmd`, `[13]=blockId`, `[14]=blockId>>8`
- `SendSmartData(addr, size)` writes:
  - `[9]=10`, `[10]=1`, `[11]=0`
  - `[12..13]=addr LE`, `[14..15]=size LE`
  - payload starts at `[16]`

Receiver (`Protocols/UploadReceiverThread.cs`) state handling:

- For group `10`:
  - opcode `1`: continue upload stream
  - opcode `3`: command ack/notify flow (`receivedBytes[12]` switches behavior)
- For short responses (`len == 10`):
  - status in `receivedBytes[9]` (`0` ok, `1` retry, `2` invalid addr, etc.)

## 5) High-Level Data Model That Drives Protocol

The `.rwdb` files in Wizard resources are JSON templates, not a binary DB.

Useful categories:

- `Modules/*.rwdb`: module GUIDs, defaults, IP placeholders
- `UserInterfaces/*.rwdb`: keypad/pulsador models and `DriverGuid`
- `ControlModels/*.rwdb`: large command maps (notably HVAC IR command payloads)
- `ControlTypes/*.rwdb`: control/protocol type metadata

This gives you high-level semantics (model IDs, capabilities) while the two protocol libraries provide low-level wire format.

## 6) Practical Build Plan for Your Integration

1. Implement a minimal UDP client for `HsCommunicationLibrary` command set first:
   - discovery (`3,0`)
   - device list (`100,1`)
   - optional identify/change-address tooling.
2. Implement robust parser structs with fixed offsets from section 3.
3. Add project download path (`10,3` + `10,2`) for backup/introspection.
4. Implement transfer sender (`10,1` and `10,3`) once read path is stable.
5. Use `.rwdb` JSON to map model GUIDs and user-facing entities.

## 7) Notes and Caveats

- `Roehn Wizard.dll` itself is obfuscated; treat it as orchestration/UI only.
- Decompiled code has at least one suspicious indexing bug in MAC int array assignment (`GetProcessorsOnNetworkCallbackObject` writes index `3` multiple times). Trust parsed strings/bytes over that helper array.
- Keep packet capture traces while implementing; unknown fields can be validated quickly against Wizard behavior.

## 8) Native SmartHub Tool (`Resources/Tools/smarthub.exe`) Findings

Source:

- `I:\Roehn Wizard\Resources\Tools\smarthub.exe` (native executable; not .NET metadata)
- extracted evidence in:
  - `logs/smarthub_strings_focus.txt`
  - `logs/smarthub_models_candidates.txt`

### 8.1 Binary/profile characteristics

- PE32 x86 native app (not managed C# / no CLR metadata).
- Uses `WSOCK32.DLL` imports directly (`socket`, `bind`, `sendto`, `recvfrom`, `connect`, `select`, `setsockopt`, `WSAStartup`).
- Exports include Delphi/Borland-style symbols for UDP unit/class:
  - `@Nmudp@TNMUDP@SendBuffer...`
  - `@Nmudp@TNMUDP@ProcessIncomingdata...`
  - `@Nmudp@TNMUDP@SetLocalPort...`

Implication:

- This tool likely contains an older/parallel implementation of the HSN UDP runtime path, including diagnostics and command monitor features not exposed in `HsCommunicationLibrary`.

### 8.2 Additional protocol signatures

New markers found beyond existing docs:

- `HSN_S-UDP` (already known)
- `HSN_M-UDP` (new; likely monitor/management stream or alternate frame family)

UI/diagnostic strings strongly tied to transport state:

- `ACK PKT`
- `SYNC`
- `POWERUP`
- `TIMEOUT ALIVE`
- `Buffer de Comandos UDP:`
- `PACKET COUNT:`
- `SOCKET NUMBER:`
- `LOCAL PORT`
- `REMOTE PORT`

### 8.3 Likely runtime field model (high confidence from format strings)

The executable contains explicit formatting templates that look like decoded frame logs:

- `ADDR:%d  PORT:%d  CMD:%d VALUE:%d`
- `ADDR:%d  PORT:%d  VALUE:%d`
- `DEVICE/ADDR:%d/%d   CHANNEL:%d  PORT:%d  VALUE:%d`
- `ID:%d - ADDR:%d - PORT:%d`
- `ID:%d - IP:%d - PORT:%d`
- `ID:%d - LOCAL IP - PORT:%d`
- `UNIT:%d  VALUE:%d  CMD:%d`
- `VARIABLE:%d  VALUE:%d`
- `SOURCE ADDR:%d   DESTINATION ADDR:%d  UNIT:%d`

There is also an explicit column-like trace header:

- `SEQUENCY`
- `ADDR`
- `LEN`
- `CMD`
- `DATA`

Integration value:

- This strongly suggests a generic command frame path where `cmd` + `value` drive actuation.
- It gives concrete candidate semantics for entity writes:
  - switch/relay: `ADDR/PORT/CMD/VALUE`
  - dimmer/channel: `UNIT/VALUE/CMD`
  - variable/script/scene paths via `VARIABLE` / `UNIT` constructs.

### 8.4 Network/port hints

- Constant `2006` appears in the binary (matches processor UDP default).
- Additional strings indicate configurable local/remote ports and simulator endpoints:
  - `Simulator Address/Port -> 16bits`
  - `Conectado no IP %s / Porta %d`

### 8.5 Product/model coverage cues

The native tool includes model labels that match and extend discovered devices:

- `ADP-DIM8`, `ADP-LX4`, `ADP-RL12`, `ADP-HUB16`
- `GUAVA-4080`, `GUAVA-DALI`, `GUAVA-RS2`, `GUAVA-I16E`, `GUAVA-I4`, `GUAVA-PWM`, `GUAVA-DX2`
- `RIO-PP`, `RIO-PR`, `RIO-PRR`
- `IRZAPPER`, `RELAY-12/16/24`

Integration value:

- Prioritize HA entity support by model family, starting with known installed ones (`DIM8`, `RL12`, `LX4T`) and then extending with these model groups.

### 8.6 Protocol hypotheses to validate with capture

Given these strings, test the following in Wireshark while toggling one output at a time:

1. Check whether control frames contain obvious tuple `ADDR, PORT, CMD, VALUE`.
2. Verify if `HSN_M-UDP` appears on-wire as an alternate header for monitor/ack flows.
3. Map `ACK`, `SYNC`, `POWERUP`, `ALIVE` transitions to specific command IDs.
4. Confirm whether `UNIT`/`VARIABLE` commands are script/runtime APIs rather than project upload APIs.

### 8.7 Immediate HA engineering actions unlocked

1. Add protocol parser scaffolding for a generic runtime command tuple:
   - fields: `addr`, `port`, `cmd`, `value`, `unit`, `variable` (nullable).
2. Add debug mode in integration to log raw tx/rx frames in hex + interpreted tuple.
3. Implement first write entities using discovered model families:
   - `switch` for RL12 channels
   - `light` (brightness) for DIM8/LX4
4. Use capture-guided mapping table `model + cmd -> action` and keep it in code as explicit constants.
