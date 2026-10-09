import { memo } from "react";

import type { ConnectionState } from "../types/rover";

interface ConnectionStatusProps {
  online: boolean;
  connection: ConnectionState | null;
  latencyMs: number | null;
}

const LABELS: Record<ConnectionState, string> = {
  connected: "Connected",
  connecting: "Connecting",
  disconnected: "Disconnected",
  error: "Error",
};

function toneOf(online: boolean, connection: ConnectionState | null): string {
  if (!online) return "offline";
  if (connection === "connected") return "ok";
  if (connection === "connecting") return "warn";
  return "error";
}

/** Link chip. Memoised: its props are primitives and change rarely. */
export const ConnectionStatus = memo(function ConnectionStatus({
  online,
  connection,
  latencyMs,
}: ConnectionStatusProps) {
  const tone = toneOf(online, connection);
  const label = !online ? "No connection" : connection ? LABELS[connection] : "Unknown";

  return (
    <div className={`link link--${tone}`} role="status">
      <span className="link__dot" aria-hidden="true" />
      <span className="link__label">{label}</span>
      <span className="link__latency">{latencyMs === null ? "—" : `${latencyMs.toFixed(0)} ms`}</span>
    </div>
  );
});
