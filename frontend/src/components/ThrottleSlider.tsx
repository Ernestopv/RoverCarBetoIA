import { memo, useCallback, type ChangeEvent, type CSSProperties } from "react";

interface ThrottleSliderProps {
  /** Current limit in the `0..1` range. */
  value: number;
  onChange: (value: number) => void;
}

const INPUT_ID = "throttle-input";

/**
 * Throttle fader.
 *
 * Scales how much of the configured maximum speed the stick and keyboard may
 * command — the same idea as the dual-rate switch on an RC transmitter. It is a
 * ceiling, not a target, and it can never exceed the limits enforced by the
 * backend safety layer.
 *
 * A native `input[type=range]` gives keyboard operation and screen-reader
 * support for free.
 */
export const ThrottleSlider = memo(function ThrottleSlider({
  value,
  onChange,
}: ThrottleSliderProps) {
  const percent = Math.round(value * 100);
  const fill: CSSProperties = { "--fill": `${percent}%` } as CSSProperties;

  const handleChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      onChange(Number(event.target.value) / 100);
    },
    [onChange],
  );

  return (
    <div className="fader">
      <div className="fader__head">
        <label className="fader__label" htmlFor={INPUT_ID}>
          Throttle
        </label>
        <span className="fader__value">{percent}%</span>
      </div>
      <input
        id={INPUT_ID}
        className="fader__input"
        type="range"
        min={0}
        max={100}
        step={5}
        value={percent}
        style={fill}
        onChange={handleChange}
      />
      <div className="fader__scale" aria-hidden="true">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
    </div>
  );
});
