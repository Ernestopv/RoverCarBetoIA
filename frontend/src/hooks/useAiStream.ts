/**
 * Live AI results, pushed by the backend.
 *
 * A WebSocket and not polling, deliberately. Polling made the interface sample
 * **slower than the sensor**: the pose network infers ten times a second and the
 * browser was asking four, so most results were produced and thrown away without
 * ever reaching the screen, which is what made the skeleton look sluggish. Here
 * the backend sends each result the moment the sensor produces it, so nothing is
 * lost and there is no per-request overhead.
 *
 * Both snapshots arrive in every message; the one that does not match the loaded
 * network says `available: false`. The sensor only holds one network at a time.
 *
 * Nothing is stored: each message replaces the previous one.
 */

import { useEffect, useState } from "react";

import { API_BASE } from "../services/api";
import type { AiStreamMessage, DetectionSnapshot, PoseSnapshot } from "../types/rover";

/** Bounded, so a backend that stays down is retried gently instead of hammered. */
const RECONNECT_DELAYS_MS = [1_000, 2_000, 5_000];

export interface AiStream {
  detections: DetectionSnapshot | null;
  pose: PoseSnapshot | null;
  /** Whether the push connection is up. */
  connected: boolean;
}

function streamUrl(): string {
  // `API_BASE` is relative by default, but it can be an absolute URL when the
  // backend lives on another host (`VITE_API_BASE`).
  if (/^https?:\/\//.test(API_BASE)) {
    return `${API_BASE.replace(/^http/, "ws")}/ai/stream`;
  }
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${API_BASE}/ai/stream`;
}

export function useAiStream(): AiStream {
  const [detections, setDetections] = useState<DetectionSnapshot | null>(null);
  const [pose, setPose] = useState<PoseSnapshot | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let attempt = 0;
    let stopped = false;

    const open = () => {
      if (stopped) return;
      socket = new WebSocket(streamUrl());

      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };

      socket.onmessage = (event) => {
        const message = JSON.parse(event.data as string) as AiStreamMessage;
        setDetections(message.detections);
        setPose(message.pose);
      };

      socket.onerror = () => {
        // A failure is always followed by `onclose`, which schedules the retry.
        socket?.close();
      };

      socket.onclose = () => {
        setConnected(false);
        if (stopped) return;
        const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)];
        attempt += 1;
        retry = window.setTimeout(open, delay);
      };
    };

    open();

    return () => {
      stopped = true;
      if (retry !== undefined) window.clearTimeout(retry);
      socket?.close();
    };
  }, []);

  return { detections, pose, connected };
}
