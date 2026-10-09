/**
 * Shown over the video while the sensor reloads another network.
 *
 * The camera genuinely restarts, so there is no picture for tens of seconds and
 * there is no progress to report. This says so like an instrument would: a
 * targeting frame and a slow scan line, in the colour this console reserves for
 * "the machine is working". The only animation on the scene stops under
 * `prefers-reduced-motion`.
 */

interface ReloadVeilProps {
  /** Short name of the network being loaded, e.g. "Pose". */
  target: string | null;
}

export function ReloadVeil({ target }: ReloadVeilProps) {
  return (
    <div className="veil" role="status" aria-live="polite">
      <div className="veil__frame" aria-hidden="true">
        <span className="veil__corner veil__corner--tl" />
        <span className="veil__corner veil__corner--tr" />
        <span className="veil__corner veil__corner--bl" />
        <span className="veil__corner veil__corner--br" />
        <span className="veil__scan" />
      </div>
      <p className="veil__text">
        <strong>Reloading network{target ? ` to ${target}` : ""}…</strong>
        <span className="veil__hint">The picture returns when the sensor is ready.</span>
      </p>
    </div>
  );
}