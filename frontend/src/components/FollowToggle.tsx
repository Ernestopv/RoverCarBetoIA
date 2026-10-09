/**
 * Operator control for the person-following behaviour.
 *
 * A single toggle, off by default. It is honest about what the rover is doing:
 * "Searching…" when enabled but with no person in view, "Following #id" when it
 * has one. The backend stops the rover the moment the target is lost, so the
 * control never has to promise more than that.
 */

import type { Follow } from "../hooks/useFollow";

interface FollowToggleProps {
  follow: Follow;
}

export function FollowToggle({ follow }: FollowToggleProps) {
  const { status, error, pending, setEnabled } = follow;

  // Until the behaviour status is known there is nothing useful to show.
  if (status === null) return null;

  const on = status.enabled;
  const state = on ? (status.has_target ? `Following #${status.target_id}` : "Searching…") : null;

  return (
    <div className="follow">
      <div className="follow__head">
        <span className="follow__label">Follow person</span>
        {state !== null && (
          <span className="follow__state" role="status">
            {state}
          </span>
        )}
      </div>

      <button
        type="button"
        className={`follow__toggle${on ? " follow__toggle--on" : ""}`}
        aria-pressed={on}
        disabled={pending}
        onClick={() => void setEnabled(!on)}
      >
        {on ? "Stop following" : "Follow person"}
      </button>

      {error !== null && (
        <p className="follow__error" role="alert">
          {error}
        </p>
      )}

      <p className="follow__hint">
        Off by default. The rover never reverses and stops if the person is lost.
      </p>
    </div>
  );
}
