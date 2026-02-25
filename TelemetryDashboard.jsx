import React, { useEffect, useMemo, useRef, useState } from "react";
import { Chart } from "chart.js/auto";

const HISTORY_WINDOW_MS = 3 * 60 * 1000;
const POLL_INTERVAL_MS = 1000;

function normalizeTelemetry(payload) {
  const temperature = Number(payload?.temperature ?? payload?.temp ?? 0);
  const heaterOn = Boolean(
    payload?.heater_on ?? payload?.heaterOn ?? payload?.heater
  );
  const kill = Boolean(payload?.kill ?? payload?.kill_state ?? payload?.killed);

  return {
    temperature,
    heaterOn,
    kill,
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
          );
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

    const labels = history.map((point) =>
      new Date(point.timestamp).toLocaleTimeString([], { hour12: false })
    );
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

  const sendKillCommand = async (value) => {
    setIsSending(true);
    setCommandStatus("");

    try {
      const response = await fetch(commandUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ type: "KILL", value }),
      });

      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.error || `Command request failed (${response.status})`);
      }

      setCommandStatus(value === 1 ? "KILL command sent" : "UNKILL command sent");
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
          <div>{telemetry ? `${telemetry.temperature.toFixed(1)} °C` : "--"}</div>
        </div>

        <div style={{ border: "1px solid #d4d4d8", borderRadius: 8, padding: 12 }}>
          <strong>Heater</strong>
          <div>{telemetry ? (telemetry.heaterOn ? "ON" : "OFF") : "--"}</div>
        </div>

        <div style={{ border: "1px solid #d4d4d8", borderRadius: 8, padding: 12 }}>
          <strong>Kill State</strong>
          <div>{telemetry ? (telemetry.kill ? "KILLED" : "ACTIVE") : "--"}</div>
        </div>
      </div>

      <div style={{ marginTop: 16, height: 280, border: "1px solid #d4d4d8", borderRadius: 8, padding: 8 }}>
        <canvas ref={chartCanvasRef} />
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button type="button" onClick={() => sendKillCommand(1)} disabled={isSending}>
          KILL
        </button>
        <button type="button" onClick={() => sendKillCommand(0)} disabled={isSending}>
          UNKILL
        </button>
      </div>
    </section>
  );
}
