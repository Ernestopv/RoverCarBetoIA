import type { TelemetrySnapshot } from "../types/rover";

interface TelemetryPanelProps {
  telemetry: TelemetrySnapshot | null;
  /** Short name of the loaded AI network, shown next to the inference gauge. */
  aiModel?: string | null;
}

const CELLS = 20;

/** Stable keys: the list is fixed, so no cell is ever re-keyed. */
const CELL_KEYS = Array.from({ length: CELLS }, (_, index) => `cell-${index}`);

function format(value: number | null | undefined, digits = 1, unit = ""): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}${unit}`;
}

function Gauge({ label, value }: { label: string; value: string }) {
  return (
    <div className="gauge">
      <span className="gauge__label">{label}</span>
      <span className="gauge__value">{value}</span>
    </div>
  );
}

function batteryTone(percentage: number | null): string {
  if (percentage === null) return "unknown";
  if (percentage < 20) return "low";
  if (percentage < 50) return "medium";
  return "ok";
}

export function TelemetryPanel({ telemetry, aiModel = null }: TelemetryPanelProps) {
  if (!telemetry) {
    return <p className="empty">Waiting for telemetry.</p>;
  }

  const { rover } = telemetry;
  const battery = rover.battery_percentage;
  const filled = battery === null ? 0 : Math.round((battery / 100) * CELLS);
  const heading = (rover.pose.heading * 180) / Math.PI;
  const currentA = rover.battery_current_ma === null ? null : rover.battery_current_ma / 1000;

  return (
    <div className="readouts">
      <div className={`batt batt--${batteryTone(battery)}`}>
        <div className="batt__top">
          <span className="batt__label">Battery</span>
          <span className="batt__value">{battery === null ? "—" : `${battery.toFixed(0)}%`}</span>
        </div>
        {rover.battery_charge_state === "charging" && (
          <span className="batt__state" role="status">
            Charging
          </span>
        )}
        <div className="batt__cells" role="img" aria-label={`Battery ${battery ?? 0} percent`}>
          {CELL_KEYS.map((key, index) => (
            <span key={key} className={`batt__cell${index < filled ? " batt__cell--on" : ""}`} />
          ))}
        </div>
      </div>

      <div className="gauges">
        <Gauge label="Pack" value={format(rover.battery_voltage, 2, " V")} />
        <Gauge label="Current" value={format(currentA, 2, " A")} />
        <Gauge label="Latency" value={format(rover.latency_ms, 0, " ms")} />
        <Gauge label="CPU temp" value={format(telemetry.cpu_temperature_c, 1, " °C")} />
        <Gauge label="AI inference" value={format(telemetry.ai_inference_ms, 1, " ms")} />
        <Gauge label="Model" value={aiModel ?? "—"} />
        <Gauge
          label="Objects"
          value={telemetry.detections === null ? "—" : String(telemetry.detections)}
        />
        <Gauge label="Last command" value={format(rover.last_command_age_s, 2, " s")} />
        <Gauge label="Position X" value={format(rover.pose.x, 2, " m")} />
        <Gauge label="Position Y" value={format(rover.pose.y, 2, " m")} />
        <Gauge label="Heading" value={format(((heading % 360) + 360) % 360, 0, "°")} />
      </div>

      <span className="readouts__stamp">
        Updated {new Date(telemetry.timestamp).toLocaleTimeString("en-GB")}
      </span>
    </div>
  );
}
