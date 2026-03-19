## IoT Hub Upgrade Assessment

Date: 2026-03-19

### Source Hub

- Name: `scc-project-iothub-42645`
- Resource group: `SCC-Project`
- Location: `canadacentral`
- SKU: `F1`
- Hostname: `scc-project-iothub-42645.azure-devices.net`

### Target Hub

- Planned SKU: `S1`
- Planned units: `1`
- Planned location: `canadacentral`
- Planned resource group: `SCC-Project`

### Website Configuration

- Workspace `.env` currently points to the source hub via `IOTHUB_CONNECTION_STRING`
- Default device ID is `esp32-relay-01`

### Device Identity To Migrate

- Device ID: `esp32-relay-01`
- Auth type: symmetric key (SAS)
- Status: enabled

### Notes

- Azure does not support in-place upgrade from `F1` to a paid hub.
- A new paid hub must be created and the device identity/config must be migrated.
- Control already works through one IoT Hub; no second hub is required for shutdown commands.

## Migration Progress

- Created target hub: `scc-project-iothub-s1-42645`
- Target hostname: `scc-project-iothub-s1-42645.azure-devices.net`
- Target event hub path: `scc-project-iothub-s1-426`
- Created target consumer group: `telemetry-sink`
- Migrated device identity: `esp32-relay-01`
- Updated Azure Function App settings:
  - `esp32-control-app`
  - `esp32-telemetry-sink-42645`
- Updated local workspace `.env` to the target hub
