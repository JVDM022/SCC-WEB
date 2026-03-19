import React, { useEffect, useMemo, useRef, useState } from "react";
import { Chart } from "chart.js/auto";

const HISTORY_WINDOW_MS = 3 * 60 * 1000;
const POLL_INTERVAL_MS = 1000;
const PACIFIC_TIME_ZONE = "America/Los_Angeles";

const PACIFIC_TIME_LABEL = new Intl.DateTimeFormat("en-US", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
  timeZone: PACIFIC_TIME_ZONE,
});

const PACIFIC_TOOLTIP_LABEL = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
  timeZone: PACIFIC_TIME_ZONE,
  timeZoneName: "short",
});

function normalizeBoolean(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return value !== 0;
  }
  const normalized = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on", "online", "enabled", "active"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off", "offline", "disabled", "inactive"].includes(normalized)) {
    return false;
  }
  return null;
}

function normalizeNumber(value) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") {
    return null;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }

  let text = String(value).trim().replace(/\u2212/g, "-");
  if (!text) {
    return null;
  }

  if (text.includes(",") && text.includes(".")) {
    if (text.lastIndexOf(",") > text.lastIndexOf(".")) {
      text = text.replaceAll(".", "").replace(",", ".");
    } else {
      text = text.replaceAll(",", "");
    }
  } else if ((text.match(/,/g) || []).length === 1 && !text.includes(".")) {
    text = text.replace(",", ".");
  }

  const direct = Number(text);
  if (Number.isFinite(direct)) {
    return direct;
  }

  const match = text.match(/[-+]?(?:\d+(?:[.,]\d+)?|\.\d+)/);
  if (!match) {
    return null;
  }

  let token = match[0];
  if (token.includes(",") && token.includes(".")) {
    if (token.lastIndexOf(",") > token.lastIndexOf(".")) {
      token = token.replaceAll(".", "").replace(",", ".");
    } else {
      token = token.replaceAll(",", "");
    }
  } else if (token.includes(",") && !token.includes(".")) {
    token = token.replace(",", ".");
  }

  const parsed = Number(token);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeUptimeSeconds(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) && value >= 0 ? Math.floor(value) : null;
  }

  const raw = String(value).trim().toLowerCase();
  if (!raw) {
    return null;
  }
  if (/^\d+$/.test(raw)) {
    return Number(raw);
  }

  let total = 0;
  let found = false;
  for (const match of raw.matchAll(/(\d+)\s*([dhms])/g)) {
    found = true;
    const amount = Number(match[1]);
    const unit = match[2];
    if (unit === "d") total += amount * 86400;
    if (unit === "h") total += amount * 3600;
    if (unit === "m") total += amount * 60;
    if (unit === "s") total += amount;
  }
  return found ? total : null;
}

function formatUptime(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds) || seconds < 0) {
    return "";
  }

  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const parts = [];

  if (days) parts.push(`${days}d`);
  if (hours) parts.push(`${hours}h`);
  if (minutes) parts.push(`${minutes}m`);
  if (secs || parts.length === 0) parts.push(`${secs}s`);

  return parts.join(" ");
}

function normalizeTelemetry(payload) {
  const rawTemperature = payload?.temperature ?? payload?.temp ?? payload?.temperature_c;
  const temperature = normalizeNumber(rawTemperature);
  const heaterOn = normalizeBoolean(
    payload?.heater_on ?? payload?.heaterOn ?? payload?.heater ?? payload?.on
  );
  const kill = normalizeBoolean(payload?.kill ?? payload?.kill_state ?? payload?.killed);
  let systemOn = normalizeBoolean(
    payload?.system_on ?? payload?.systemOn ?? payload?.system ?? payload?.relay_on
  );
  const uptimeSeconds = normalizeUptimeSeconds(
    payload?.uptime_seconds ?? payload?.uptime_s ?? payload?.uptime
  );

  if (systemOn === null) {
    if (kill !== null) {
      systemOn = !kill;
    } else if (temperature !== null || heaterOn !== null) {
      systemOn = true;
    }
  }

  return {
    temperature,
    heaterOn,
    kill,
    systemOn,
    uptimeSeconds,
  };
}

function withBase(base, path) {
  const cleanBase = base.replace(/\/+$/, "");
  return `${cleanBase}${path}`;
}

export default function TelemetryDashboard({ apiBaseUrl = "" }) {
  const [telemetry, setTelemetry] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [commandStatus, setCommandStatus] = useState("");

  const chartCanvasRef = useRef(null);
  const chartRef = useRef(null);

  const telemetryUrl = useMemo(() => withBase(apiBaseUrl, "/api/telemetry"), [apiBaseUrl]);
  const commandUrl = useMemo(() => withBase(apiBaseUrl, "/api/command"), [apiBaseUrl]);

  useEffect(() => {
    let cancelled = false;

    const pollTelemetry = async () => {
      try {
        const response = await fetch(telemetryUrl, {
          headers: { Accept: "application/json" },
        });
        const body = await response.json().catch(() => ({}));

        if (!response.ok) {
          throw new Error(body.error || `Telemetry request failed (${response.status})`);
        }

        const next = normalizeTelemetry(body);
        if (cancelled) {
          return;
        }

        setTelemetry(next);
        setError("");

        setHistory((prev) => {
          const now = Date.now();
          return [...prev, { timestamp: now, temperature: next.temperature }].filter(
            (point) => now - point.timestamp <= HISTORY_WINDOW_MS
          ).filter((point) => point.temperature !== null && !Number.isNaN(point.temperature));
        });
      } catch (err) {
        if (!cancelled) {
          setError(err?.message || "Unable to load telemetry");
        }
      }
    };

    pollTelemetry();
    const intervalId = setInterval(pollTelemetry, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [telemetryUrl]);

  useEffect(() => {
    if (!chartCanvasRef.current) {
      return;
    }

    const labels = history.map((point) => PACIFIC_TIME_LABEL.format(new Date(point.timestamp)));
    const values = history.map((point) => point.temperature);

    if (!chartRef.current) {
      chartRef.current = new Chart(chartCanvasRef.current, {
        type: "line",
        data: {
          labels,
          datasets: [
            {
              label: "Temperature (°C)",
              data: values,
              borderColor: "#0b6ef6",
              backgroundColor: "rgba(11, 110, 246, 0.15)",
              tension: 0.25,
              fill: true,
              pointRadius: 0,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: {
            tooltip: {
              callbacks: {
                title(items) {
                  const point = history[items[0]?.dataIndex ?? -1];
                  if (!point) {
                    return "";
                  }
                  return PACIFIC_TOOLTIP_LABEL.format(new Date(point.timestamp));
                },
              },
            },
          },
          scales: {
            x: {
              ticks: { maxTicksLimit: 10 },
            },
            y: {
              title: { display: true, text: "°C" },
            },
          },
        },
      });
      return;
    }

    chartRef.current.data.labels = labels;
    chartRef.current.data.datasets[0].data = values;
    chartRef.current.options.plugins.tooltip.callbacks.title = (items) => {
      const point = history[items[0]?.dataIndex ?? -1];
      if (!point) {
        return "";
      }
      return PACIFIC_TOOLTIP_LABEL.format(new Date(point.timestamp));
    };
    chartRef.current.update();
  }, [history]);

  useEffect(() => {
    return () => {
      if (chartRef.current) {
        chartRef.current.destroy();
        chartRef.current = null;
      }
    };
  }, []);

  const sendShutdownCommand = async (value) => {
    setIsSending(true);
    setCommandStatus("");

    try {
      const response = await fetch(commandUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ type: value === 1 ? "SHUTDOWN" : "RESUME", value }),
      });

      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.error || `Command request failed (${response.status})`);
      }

      setCommandStatus(value === 1 ? "Shutdown command sent" : "Resume command sent");
      setError("");
    } catch (err) {
      setError(err?.message || "Unable to send command");
    } finally {
      setIsSending(false);
    }
  };

  return (
    <section style={{ padding: 16, fontFamily: "system-ui, sans-serif" }}>
      <h2 style={{ marginTop: 0 }}>Heater Telemetry</h2>

      {error ? <p style={{ color: "#b91c1c" }}>{error}</p> : null}
      {commandStatus ? <p style={{ color: "#166534" }}>{commandStatus}</p> : null}

      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
        <div style={{ border: "1px solid #d4d4d8", borderRadius: 8, padding: 12 }}>
          <strong>Temperature</strong>
          <div>{telemetry && telemetry.temperature !== null && !Number.isNaN(telemetry.temperature) ? `${telemetry.temperature.toFixed(1)} °C` : "--"}</div>
        </div>

        <div style={{ border: "1px solid #d4d4d8", borderRadius: 8, padding: 12 }}>
          <strong>Heater</strong>
          <div>{telemetry ? (telemetry.heaterOn ? "ON" : "OFF") : "--"}</div>
        </div>

        <div style={{ border: "1px solid #d4d4d8", borderRadius: 8, padding: 12 }}>
          <strong>Shutdown State</strong>
          <div>{telemetry ? (telemetry.kill ? "SHUT DOWN" : "RUNNING") : "--"}</div>
        </div>

        <div style={{ border: "1px solid #d4d4d8", borderRadius: 8, padding: 12 }}>
          <strong>System</strong>
          <div>{telemetry ? (telemetry.systemOn === null ? "Unknown" : telemetry.systemOn ? "ON" : "OFF") : "--"}</div>
        </div>

        {telemetry?.systemOn && telemetry?.uptimeSeconds !== null ? (
          <div style={{ border: "1px solid #d4d4d8", borderRadius: 8, padding: 12 }}>
            <strong>Uptime</strong>
            <div>{formatUptime(telemetry.uptimeSeconds)}</div>
          </div>
        ) : null}
      </div>

      <div style={{ marginTop: 16, height: 280, border: "1px solid #d4d4d8", borderRadius: 8, padding: 8 }}>
        <canvas ref={chartCanvasRef} />
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button type="button" onClick={() => sendShutdownCommand(1)} disabled={isSending}>
          Shut Off
        </button>
        <button type="button" onClick={() => sendShutdownCommand(0)} disabled={isSending}>
          Resume
        </button>
      </div>
    </section>
  );
}
