/**
 * Whether the live `<video>` is actually receiving frames right now.
 *
 * Different from WebRTC connection state: the connection can stay "live" while
 * MediaMTX has no publisher, which looks like a frozen or black picture. The
 * honest signal for "the picture is moving" is the video element's `currentTime`
 * advancing, so this hook watches that.
 *
 * Used to keep the model-switch reload overlay running until the new stream is
 * really on screen, not just until the server says it is publishing.
 */

import { useEffect, useRef, useState, type RefObject } from "react";

/** Without a new frame for this long, the video counts as frozen. */
const STALE_MS = 1_500;

export function useVideoAlive(
  videoRef: RefObject<HTMLVideoElement | null>,
  intervalMs = 300,
): boolean {
  const [alive, setAlive] = useState(false);
  const lastTimeRef = useRef(-1);
  const lastAdvanceRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = () => {
      const video = videoRef.current;
      if (video !== null && Number.isFinite(video.currentTime)) {
        const now = video.currentTime;
        if (now !== lastTimeRef.current) {
          lastTimeRef.current = now;
          lastAdvanceRef.current = performance.now();
        }
      }
      setAlive(videoRef.current !== null && performance.now() - lastAdvanceRef.current <= STALE_MS);
      if (!cancelled) timer = window.setTimeout(tick, intervalMs);
    };

    tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [videoRef, intervalMs]);

  return alive;
}