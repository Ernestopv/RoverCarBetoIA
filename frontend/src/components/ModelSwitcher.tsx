/**
 * Choice of which AI network the sensor runs.
 *
 * Two buttons with clear roles. While a switch runs both are disabled, the target
 * is named ("Configuring Pose…") and a thin indeterminate sweep runs underneath —
 * the only animation on the panel. It answers the operator's action and stops as
 * soon as the new network is live; under `prefers-reduced-motion` it collapses to
 * a quiet half-bar instead of moving.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { CameraModels } from "../hooks/useCameraModels";
import { shortModelName } from "../lib/models";

interface ModelSwitcherProps {
  models: CameraModels;
}

export function ModelSwitcher({ models }: ModelSwitcherProps) {
  const { report, active, target, switching, error, switchTo } = models;
  // A short amber pulse on whichever button just became active: it confirms the
  // switch landed, in the colour this console uses for "the machine did it".
  const [justLoaded, setJustLoaded] = useState(false);
  const initialActiveRef = useRef(true);

  useEffect(() => {
    if (initialActiveRef.current) {
      initialActiveRef.current = false;
      return;
    }
    setJustLoaded(true);
    const timer = window.setTimeout(() => setJustLoaded(false), 700);
    return () => window.clearTimeout(timer);
  }, [active]);

  const choose = useCallback(
    (id: string) => {
      if (switching) return;
      void switchTo(id);
    },
    [switching, switchTo],
  );

  if (report === null) return null;

  return (
    <div className="model">
      <div className="model__head">
        <span className="model__label">AI model</span>
        {switching && (
          <span className="model__state" role="status">
            Configuring {shortModelName(target)}…
          </span>
        )}
      </div>

      <div className="model__options" role="group" aria-label="AI model">
        {report.models.map((model) => (
          <button
            key={model.id}
            type="button"
            className={`model__option${justLoaded && active === model.id ? " model__option--loaded" : ""}`}
            aria-pressed={active === model.id}
            title={model.description}
            disabled={switching || active === model.id}
            onClick={() => choose(model.id)}
          >
            {shortModelName(model.id) ?? model.task}
          </button>
        ))}
      </div>

      {switching && (
        <div className="model__progress" aria-hidden="true">
          <span className="model__progress-track" />
        </div>
      )}

      {error !== null && (
        <p className="model__error" role="alert">
          {error}
        </p>
      )}

      <p className="model__hint">
        Switching reloads the camera and the video drops for a moment.
      </p>
    </div>
  );
}