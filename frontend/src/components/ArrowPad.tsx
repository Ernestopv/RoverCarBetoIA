/**
 * D-pad drive control.
 *
 * Hold a direction to drive; releasing it stops the rover — and so does losing
 * the window's focus or the pointer, exactly like the joystick. The command is
 * `±1` in each axis and the *shared* throttle limits it, so this control follows
 * the same dual-rate idea as the stick and the keyboard.
 *
 * The buttons are also lit by the keyboard: directions are a shared vocabulary
 * (`PAD_DIRECTIONS`), so holding the up arrow lights the up button. Both drive
 * through the same `move`/`stop` path; when both are pressed at once the last
 * command wins, the same as the stick and the keyboard doing it today.
 */

import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";

import { PAD_DIRECTIONS, padCommand } from "../lib/input";
import type { MotionCommand } from "../types/rover";

interface ArrowPadProps {
  onCommand: (command: MotionCommand) => void;
  onRelease: () => void;
  disabled?: boolean;
  /** Directions also held on the keyboard, so the buttons light up in step. */
  keyboardHeld?: readonly string[];
}

const LABELS: Record<string, string> = {
  Forward: "▲",
  Back: "▼",
  "Turn left": "◀",
  "Turn right": "▶",
};

const AREAS: Record<string, string> = {
  Forward: "forward",
  Back: "back",
  "Turn left": "left",
  "Turn right": "right",
};

const BUTTONS = PAD_DIRECTIONS.map((direction) => ({
  ...direction,
  label: LABELS[direction.name],
  area: AREAS[direction.name],
}));

export function ArrowPad({
  onCommand,
  onRelease,
  disabled = false,
  keyboardHeld = [],
}: ArrowPadProps) {
  /** Which directions are held right now. A ref: pointer events read it synchronously. */
  const heldRef = useRef(new Set<string>());
  /** Only a command followed by an empty release must trigger `onRelease`. */
  const commandedRef = useRef(false);
  const [held, setHeld] = useState<readonly string[]>([]);

  const syncHeld = () => setHeld([...heldRef.current]);

  const update = useCallback(() => {
    commandedRef.current = true;
    onCommand(padCommand(heldRef.current));
  }, [onCommand]);

  const release = useCallback(
    (name: string) => {
      if (!heldRef.current.delete(name)) return;
      syncHeld();
      if (heldRef.current.size > 0) {
        update();
        return;
      }
      if (!commandedRef.current) return;
      commandedRef.current = false;
      onRelease();
    },
    [onRelease, update],
  );

  // Safety net, same as the stick: if the window loses focus mid-press the
  // pointer events stop arriving, so the rover must never be left driving.
  useEffect(() => {
    const clearAll = () => {
      if (heldRef.current.size === 0) return;
      heldRef.current.clear();
      syncHeld();
      if (!commandedRef.current) return;
      commandedRef.current = false;
      onRelease();
    };
    window.addEventListener("blur", clearAll);
    return () => window.removeEventListener("blur", clearAll);
  }, [onRelease]);

  const press = useCallback(
    (event: PointerEvent<HTMLButtonElement>, name: string) => {
      if (disabled) return;
      // Keep receiving the pointer even when it leaves the button, so a release
      // is always observed.
      event.currentTarget.setPointerCapture(event.pointerId);
      heldRef.current.add(name);
      syncHeld();
      update();
    },
    [disabled, update],
  );

  const buttonClass = (name: string) =>
    `pad__button${held.includes(name) || keyboardHeld.includes(name) ? " pad__button--pressed" : ""}`;

  return (
    <div className="pad">
      <div className="pad__grid" role="group" aria-label="Directional drive">
        {BUTTONS.map((direction) => (
          <button
            key={direction.name}
            type="button"
            className={buttonClass(direction.name)}
            style={{ gridArea: direction.area }}
            aria-label={direction.name}
            title={direction.name}
            disabled={disabled}
            onPointerDown={(event) => press(event, direction.name)}
            onPointerUp={() => release(direction.name)}
            onPointerCancel={() => release(direction.name)}
            onLostPointerCapture={() => release(direction.name)}
          >
            {direction.label}
          </button>
        ))}
      </div>
      <p className="pad__hint">Hold to drive, release to stop.</p>
    </div>
  );
}