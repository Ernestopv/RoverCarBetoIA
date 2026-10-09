# Spec — Live video (Phase 5)

Status: **complete and verified**, simulator and real camera (Phase 5a and 5b).

## Goal

Live video from the rover camera in the browser, with the lowest possible latency,
without recording or persisting media, with a swappable source
(simulated now, IMX500 later) without touching the API or the frontend.

## Requirements

**Functional**

- RF1 · A single stream, path `rover`.
- RF2 · Swappable source: `CAMERA_MODE=simulator|imx500`.
- RF3 · Queryable status: publishing yes/no, resolution, fps, restarts, last error.
- RF4 · Auto-start with the API and auto-recovery of the publisher.

**Non-functional**

- RNF1 · End-to-end latency ≤ 150 ms on LAN. Measured: transport + buffer ≈ 20 ms.
- RNF2 · ≤ 3 Mbit/s at 720p30 (H.264).
- RNF3 · **Zero** frame persistence: `record: false`, no media file.
- RNF4 · A camera failure **never** blocks rover control.
- RNF5 · A failure on either side (camera or viewer) does not affect
  control or telemetry.
- RNF6 · Capacity: 1 input stream (2.5 Mbit/s) and ≤ 3 viewers (≈ 7.5 Mbit/s
  output). There is no database, cache or queue: nothing is persisted and the
  video is live, so those blocks do not apply by design.
- RNF7 · Observability: `/api/v1/camera/status`, publisher logs and MediaMTX
  control (`readers`) to know whether a viewer is receiving.

## Architecture

```text
camera (Picamera2 | simulator)
   │  RTSP · TCP · loopback on the Pi
   ▼
MediaMTX ── WebRTC/WHEP ──► <video> in React
   │
   ├── record: false           (privacy invariant)
   └── API :9997               (diagnostics, 127.0.0.1 only)
```

Pieces: `app/camera/{interface,simulator,stream,factory}.py` · `mediamtx` service
· `<video>` + WHEP in the frontend.

**Structural rule:** only one process may own the camera, and it is the one that performs
inference (Picamera2). If another takes it, Phase 6 breaks.

## Interfaces / API

| Interface | Contract |
| --- | --- |
| `GET /api/v1/camera/status` | `CameraStatus`: `mode, running, width, height, fps, stream_path, webrtc_port, restarts, last_error, timestamp` |
| `POST http://<host>:<webrtc_port>/<path>/whep` | Offer SDP → `201` + answer SDP. `DELETE` to the `Location` closes the session |
| `Camera` (internal) | `start()`, `stop()`, `status()`, `is_running` |
| Config | `CAMERA_MODE`, `CAMERA_WIDTH/HEIGHT/FPS/BITRATE_KBPS/STREAM_PATH`, `MEDIAMTX_HOST/RTSP_PORT/WEBRTC_PORT` |

The WHEP URL is composed by **the browser** with its own hostname; the backend only
publishes `stream_path` and `webrtc_port`.

## Decisions

| Decision | Discarded | Reason |
| --- | --- | --- |
| WebRTC/WHEP via MediaMTX | MJPEG (µStreamer), HLS | ~20 ms vs 2–10 s; 2.5 vs 10–40 Mbit/s |
| MediaMTX as sole intermediary | µStreamer + Janus, FFmpeg direct to browser | one piece instead of two; several outputs from the same stream |
| Picamera2 owns the camera | MediaMTX `source: rpiCamera` | the IMX500 inference is only obtained through Picamera2 |
| FFmpeg as simulated publisher | OpenCV/PyAV | no native Python dependencies; all in memory |
| `-tune zerolatency`, `-profile baseline`, `-g <fps>` | x264 defaults | no B-frames or lookahead; fast entry into the stream |
| Explicit `record: false` | — | verifiable privacy invariant |
| No active redundancy | MediaMTX replicas | 1 rover, 1 camera: recovery is restart + reconnect |

## Edge cases

- MediaMTX starts after the publisher → supervisor with 1/2/5/10 s backoff.
- FFmpeg missing or camera busy → `last_error` + `running=false`; control continues.
- Viewer joins mid-stream → a keyframe every 1 s bounds the startup.
- Lossy network → WebRTC adapts; `jitterBufferDelay` and `packetsLost` are monitored.
- Viewer closes abruptly → MediaMTX releases the session by timeout.
- Page served over HTTPS → WHEP over HTTP blocked (mixed content). Accepted: the
  stack is HTTP on the local network.
- `CAMERA_MODE=imx500` without driver → `ConfigurationError` with an explicit message, without
  breaking the API startup.

## Acceptance criteria

All verified on the running stack, except the real driver:

| Criterion | Result |
| --- | --- |
| `GET /camera/status` → `running: true`, `last_error: null` | ✔ |
| MediaMTX `ready: true`, `tracks: ["H264"]` | ✔ `1280x720 Baseline` |
| WHEP negotiated and ≥ 25 fps without loss in 10 s | ✔ 201, 298 frames, 0 lost, 0 NACK |
| Transport + jitter buffer ≤ 50 ms | ✔ 17.9 ms (RTT 1 ms) |
| Real `<video>` decodes the stream | ✔ `videoWidth 1280`, `readyState 4` |
| `record: false`; no media file on disk | ✔ confirmed in the effective config |
| Kill FFmpeg → restart and `restarts` increments | ✔ returns to `ready` in ~1 s |
| Camera failure does not alter `/rover/move` or `/telemetry` | ✔ during the kill |
| `pytest` green (lifecycle, restart, camera error) | ✔ 59 tests |

### Verification on the Raspberry Pi (Phase 5b)

With `CAMERA_MODE=imx500`, checked on the real board:

```text
libcamera v0.7.2+rpt20260817 · libpisp v1.7.0
tuning file /usr/share/libcamera/ipa/rpi/pisp/imx500.json
Registered camera .../imx500@1a to CFE device /dev/media1 and ISP device /dev/media0
Camera now open · Configuration successful! · Camera started

MediaMTX ..... ready: true · tracks: ["H264"] · 1280x720 Baseline level 3.1
WHEP real .... HTTP 201 · connectionState connected
               200 frames decoded in 8 s (27 fps)
               0 packets lost · 2.4 MB
               RTT 19 ms · jitter buffer 39 ms
```

Startup: `docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build`.

### Latency / smoothness tuning (this session)

The *absolute* latency was already low (transport ≈ 20 ms + browser
jitter buffer at 0): it is maintained. The perceived problem was **smoothness**: without setting
`FrameRate` the sensor self-limited to ~17 fps, and the pose inference (which
depends on the frame rate) dropped to ~2.7/s. By setting
`controls={"FrameRate": 30}` in the IMX500 driver configuration (the pattern from
the official example):

- video: 17 → **30 fps** (measured at the sensor with the camera publishing);
- pose inference: ~2.7 → **~5/s at the sensor, ~4/s delivered** by the stack.

Measured boundaries: at `FrameRate=10` the inference reaches its nominal (10/s) but
the video worsens to 10 fps; **30 fps is the balance** between smoothness and skeleton
rate.

**GOP at 0.5 s (this revision).** The real publisher (`FfmpegOutput`) does not have the
low-latency flags that the simulator does use (`-tune zerolatency`). On a lossy
Wi-Fi link (measured ~10 %), a decoder that loses a packet waits
for the next IDR: with `iperiod=fps` (1 s) that is up to **1 s of delayed image**
perceived as "delay". `iperiod=max(1, fps//2)` (0.5 s) halves that wait. Cost
measured in bitrate: **1.95 → 2.54 Mbit/s** (RNF2 limit = 3 Mbit/s).

**Duplicated load (finding).** MediaMTX can have **several simultaneous WebRTC
readers**; in the revision there were **3 sessions from the same PC** (3 open
tabs), each pulling ~2.5 Mbit/s → ~7.5 Mbit/s over the same Wi-Fi →
saturation, jitter and delay. Practical rule: **a single rover tab**. Sessions are
closed with `DELETE` when the page unmounts, but a tab closed
abruptly can leave the reader until MediaMTX expires it.

Recorded debt: MediaMTX `writeQueueSize` (512 by default) untouched —
there is no evidence that it adds perceptible latency; it would be adjusted only with an
end-to-end measurement that justifies it.

---

Diagnosis (8 rows): explicit RF/RNF ✔ · capacity estimation ✔ ·
redundancy declared as not applicable with reason ✔ · DB/cache/queues declared
N/A ✔ · observability ✔ · deployment via the existing `docker compose` ✔ ·
**fails**: deployment strategy without documented rollback → add
`docker compose` with a version-tagged image when there is CI.
