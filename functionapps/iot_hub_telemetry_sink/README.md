# IoT Hub Telemetry Sink Function

This Azure Function consumes the IoT Hub Event Hub-compatible endpoint and stores the latest heater telemetry sample in PostgreSQL table `heater_telemetry_latest`.

Required app settings:

- `AzureWebJobsStorage`
- `FUNCTIONS_WORKER_RUNTIME=python`
- `DATABASE_URL`
- `DATABASE_CONNECT_TIMEOUT` (optional, defaults to `15`)
- `IOTHUB_EVENTHUB_CONNECTION_STRING`
- `IOTHUB_EVENTHUB_NAME`
- `IOTHUB_EVENTHUB_CONSUMER_GROUP`
- `TELEMETRY_DEVICE_ID` (optional but recommended)

Recommended consumer group:

- Create a dedicated IoT Hub consumer group such as `telemetry-sink`.

Deployment target:

- Azure Function App `esp32-control-app`
