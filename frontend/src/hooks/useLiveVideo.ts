/**
 * Live video over WebRTC (WHEP).
 *
 * MediaMTX answers a WHEP handshake with an SDP answer; the resulting track is
 * attached to a `<video>` element. The hook keeps the connection alive: if it
 * drops it reconnects with a bounded backoff, and it closes the WHEP session on
 * unmount so MediaMTX frees the reader immediately.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";

import { buildWhepUrl, resolveSessionUrl } from "../lib/stream";
import { api } from "../services/api";
import type { CameraStatus } from "../types/rover";

const CAMERA_POLL_MS = 5_000;
const ICE_GATHERING_TIMEOUT_MS = 3_000;
const RETRY_DELAYS_MS = [1_000, 2_000, 5_000, 10_000];

export type StreamState = "idle" | "connecting" | "live" | "error";

export interface LiveVideo {
  videoRef: RefObject<HTMLVideoElement | null>;
  state: StreamState;
  error: string | null;
  camera: CameraStatus | null;
  whepUrl: string | null;
  /** Force an immediate reconnection attempt. */
  reconnect: () => void;
}

/** Resolve once ICE gathering finishes, or after a short timeout. */
function waitForIceGathering(connection: RTCPeerConnection): Promise<void> {
  if (connection.iceGatheringState === "complete") return Promise.resolve();

  return new Promise((resolve) => {
    const finish = () => {
      if (connection.iceGatheringState !== "complete") return;
      window.clearTimeout(timer);
      connection.removeEventListener("icegatheringstatechange", finish);
      resolve();
    };
    const timer = window.setTimeout(() => {
      connection.removeEventListener("icegatheringstatechange", finish);
      resolve();
    }, ICE_GATHERING_TIMEOUT_MS);
    connection.addEventListener("icegatheringstatechange", finish);
  });
}

export function useLiveVideo(): LiveVideo {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [camera, setCamera] = useState<CameraStatus | null>(null);
  const [state, setState] = useState<StreamState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // The port and the stream path are configuration that lives in the backend.
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const status = await api.cameraStatus();
        if (!cancelled) setCamera(status);
      } catch {
        // Not fatal: the stream state already reports the connection problem.
      } finally {
        if (!cancelled) timer = window.setTimeout(() => void poll(), CAMERA_POLL_MS);
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  const whepUrl = useMemo(
    () =>
      camera
        ? buildWhepUrl(
            camera.webrtc_port,
            camera.stream_path,
            window.location,
            import.meta.env.VITE_MEDIAMTX_BASE,
          )
        : null,
    [camera?.webrtc_port, camera?.stream_path],
  );

  const reconnect = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    if (!whepUrl) {
      setState("idle");
      return;
    }

    // Captured so the narrowing survives inside the nested `connect()`.
    const url: string = whepUrl;

    let cancelled = false;
    let connection: RTCPeerConnection | null = null;
    let sessionUrl: string | null = null;
    let retryTimer: number | undefined;
    let failures = 0;

    const closeSession = () => {
      if (sessionUrl) {
        void fetch(sessionUrl, { method: "DELETE" }).catch(() => {});
        sessionUrl = null;
      }
      connection?.close();
      connection = null;
    };

    const scheduleRetry = (reason: string) => {
      if (cancelled) return;
      const delay = RETRY_DELAYS_MS[Math.min(failures, RETRY_DELAYS_MS.length - 1)];
      failures += 1;
      setState("error");
      setError(`${reason}. Retrying in ${Math.round(delay / 1000)} s.`);
      retryTimer = window.setTimeout(() => {
        if (!cancelled) void connect();
      }, delay);
    };

    async function connect(): Promise<void> {
      closeSession();
      if (cancelled) return;

      setState("connecting");
      setError(null);

      try {
        const peer = new RTCPeerConnection();
        connection = peer;
        peer.addTransceiver("video", { direction: "recvonly" });

        peer.addEventListener("connectionstatechange", () => {
          if (cancelled) return;
          const current = peer.connectionState;
          if (current === "connected") {
            failures = 0;
            setState("live");
            setError(null);
          } else if (current === "failed") {
            scheduleRetry("WebRTC connection failed");
          }
        });

        peer.addEventListener("track", (event) => {
          const video = videoRef.current;
          if (!video) return;
          video.srcObject = new MediaStream([event.track]);
          void video.play().catch(() => {});
        });

        await peer.setLocalDescription(await peer.createOffer());
        await waitForIceGathering(peer);

        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/sdp" },
          body: peer.localDescription?.sdp ?? "",
        });
        if (!response.ok) {
          throw new Error(`MediaMTX answered ${response.status} to the WHEP request`);
        }

        sessionUrl = resolveSessionUrl(response.headers.get("Location"), response.url);
        await peer.setRemoteDescription({ type: "answer", sdp: await response.text() });

        // This is a control feed, not a movie: ask for the smallest playout
        // buffer. `jitterBufferTarget` is the current API (milliseconds);
        // `playoutDelayHint` is the older Chrome one, kept for compatibility.
        for (const receiver of peer.getReceivers()) {
          const lowLatency = receiver as RTCRtpReceiver & {
            jitterBufferTarget?: number;
            playoutDelayHint?: number;
          };
          lowLatency.jitterBufferTarget = 0;
          lowLatency.playoutDelayHint = 0;
        }

        if (peer.connectionState === "connected") {
          failures = 0;
          setState("live");
        }
      } catch (cause) {
        scheduleRetry(cause instanceof Error ? cause.message : String(cause));
      }
    }

    void connect();

    return () => {
      cancelled = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      closeSession();
    };
  }, [whepUrl, attempt]);

  return { videoRef, state, error, camera, whepUrl, reconnect };
}
