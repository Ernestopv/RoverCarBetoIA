import { memo } from "react";

import { isIdleCommand } from "../lib/motion";
import type { MotionCommand } from "../types/rover";

interface AxisProps {
  label: string;
  value: number;
  live: boolean;
}

function Axis({ label, value, live }: AxisProps) {
  return (
    <div className={live ? "axis axis--live" : "axis"}>
      <span className="axis__label">{label}</span>
      <span className="axis__value">{value.toFixed(2)}</span>
    </div>
  );
}

/**
 * Effective command being sent, already scaled by the throttle.
 *
 * Memoised: the parent re-renders on every status poll and every command tick,
 * but these values only change when the operator actually moves a control.
 */
export const AxesReadout = memo(function AxesReadout({ command }: { command: MotionCommand }) {
  const live = !isIdleCommand(command);

  return (
    <div className="axes">
      <Axis label="Forward" value={command.linear} live={live} />
      <Axis label="Turn" value={command.angular} live={live} />
    </div>
  );
});
