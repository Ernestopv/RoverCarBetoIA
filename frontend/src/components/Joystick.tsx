/**
 * Virtual joystick.
 *
 * Outputs a normalized command in the `-1..1` range: pushing up moves forward
 * and pushing right turns right.
 *
 * Releasing the knob is the primary way to stop the rover, so the release path
 * is deliberately redundant: pointer up, pointer cancel, lost pointer capture,
 * or the window losing focus all report a stop.
 */

import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";

import { shapeCommand } from "../lib/input";
import type { MotionCommand } from "../types/rover";

interface JoystickProps {
  onChange: (command: MotionCommand) => void;
  onRelease: () => void;
  disabled?: boolean;
}

interface Offset {
  x: number;
  y: number;
}

const IDLE: Offset = { x: 0, y: 0 };

function clampUnit(value: number): number {
  return Math.max(-1, Math.min(1, value));
}

export function Joystick({ onChange, onRelease, disabled = false }: JoystickProps) {
  const padRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef(false);
  const [engaged, setEngaged] = useState(false);
  const [offset, setOffset] = useState<Offset>(IDLE);

  const release = useCallback(() => {
    if (!activeRef.current) return;
    activeRef.current = false;
    setEngaged(false);
    setOffset(IDLE);
    onRelease();
  }, [onRelease]);

  // Safety net: if the window loses focus mid-drag the pointer events stop
  // arriving, so the command must be released explicitly.
  useEffect(() => {
    window.addEventListener("blur", release);
    return () => window.removeEventListener("blur", release);
  }, [release]);

  const applyFromPointer = useCallback(
    (clientX: number, clientY: number) => {
      const pad = padRef.current;
      if (!pad) return;

      const rect = pad.getBoundingClientRect();
      const maxRadius = rect.width / 2 - 14;
      let dx = clientX - (rect.left + rect.width / 2);
      let dy = clientY - (rect.top + rect.height / 2);

      const distance = Math.hypot(dx, dy);
      if (distance > maxRadius) {
        dx = (dx / distance) * maxRadius;
        dy = (dy / distance) * maxRadius;
      }

      setOffset({ x: dx, y: dy });
      onChange(
        shapeCommand({
          linear: clampUnit(-dy / maxRadius),
          angular: clampUnit(-dx / maxRadius),
        }),
      );
    },
    [onChange],
  );

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    activeRef.current = true;
    setEngaged(true);
    event.currentTarget.setPointerCapture(event.pointerId);
    applyFromPointer(event.clientX, event.clientY);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!activeRef.current || disabled) return;
    applyFromPointer(event.clientX, event.clientY);
  };

  const className = [
    "stick",
    disabled ? "stick--disabled" : "",
    engaged ? "stick--engaged" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={className}>
      <div
        ref={padRef}
        className="stick__well"
        role="group"
        aria-label="Driving joystick"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={release}
        onPointerCancel={release}
        onLostPointerCapture={release}
      >
        <span className="stick__axis" />
        <span
          className="stick__knob"
          style={{ transform: `translate(${offset.x}px, ${offset.y}px)` }}
        />
      </div>
      <p className="stick__hint">Drag to drive, release to stop.</p>
    </div>
  );
}
