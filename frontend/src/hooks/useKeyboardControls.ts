/**
 * Keyboard driving: arrows or WASD move the rover, Space triggers STOP.
 *
 * The keys are mapped onto the same direction names as the on-screen D-pad, so a
 * held "Forward" is the same direction whether it came from a key or a button.
 * The current set is exposed so the pad can light up in step with the keys.
 *
 * Releasing the last held key sends the stop command directly, the same way
 * releasing the stick or an on-screen arrow stops the rover: stopping is the
 * release path, not the backend watchdog. Simultaneous sources keep working as
 * they always have (the last command wins).
 */

import { useEffect, useRef, useState } from "react";

import { KEY_DIRECTIONS, padCommand } from "../lib/input";

export function useKeyboardControls(
  move: (linear: number, angular: number) => void,
  stop: () => void,
): readonly string[] {
  /** Direction names currently held on the keyboard. */
  const heldRef = useRef(new Set<string>());
  const [held, setHeld] = useState<readonly string[]>([]);

  useEffect(() => {
    const syncHeld = () => setHeld([...heldRef.current]);

    const update = () => {
      const command = padCommand(heldRef.current);
      if (command.linear === 0 && command.angular === 0) {
        // Nothing held any more: stop now, not after the backend watchdog.
        stop();
      } else {
        move(command.linear, command.angular);
      }
      syncHeld();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code === "Space") {
        event.preventDefault();
        heldRef.current.clear();
        syncHeld();
        stop();
        return;
      }
      const direction = KEY_DIRECTIONS[event.key];
      if (!direction) return;
      event.preventDefault();
      heldRef.current.add(direction);
      update();
    };

    const onKeyUp = (event: KeyboardEvent) => {
      const direction = KEY_DIRECTIONS[event.key];
      if (!direction) return;
      heldRef.current.delete(direction);
      update();
    };

    const onBlur = () => {
      if (heldRef.current.size === 0) return;
      heldRef.current.clear();
      update();
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, [move, stop]);

  return held;
}