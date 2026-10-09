/**
 * Live-video URL helpers.
 *
 * MediaMTX runs inside the compose network, so the backend cannot tell the
 * browser where to reach it: from inside a container the host is a Docker
 * service name. The browser therefore builds the URL from its own hostname plus
 * the port and path published by `GET /camera/status`.
 */

export interface LocationLike {
  protocol: string;
  hostname: string;
}

/** Strip leading and trailing slashes. */
function trimSlashes(value: string): string {
  return value.replace(/^\/+|\/+$/g, "");
}

/**
 * URL of the MediaMTX WebRTC (WHEP) endpoint for a stream.
 *
 * `baseOverride` (e.g. from an env var) wins over the derived origin.
 */
export function buildWhepUrl(
  port: number,
  streamPath: string,
  location: LocationLike,
  baseOverride?: string,
): string {
  const origin =
    baseOverride?.replace(/\/+$/, "") ?? `${location.protocol}//${location.hostname}:${port}`;
  return `${origin}/${trimSlashes(streamPath)}/whep`;
}

/**
 * Absolute URL of the WHEP session returned in the `Location` header, used to
 * close the session with `DELETE` when the viewer goes away.
 */
export function resolveSessionUrl(locationHeader: string | null, base: string): string | null {
  if (!locationHeader) return null;
  try {
    return new URL(locationHeader, base).toString();
  } catch {
    return null;
  }
}
