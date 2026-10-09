# TASKS.md — RoverCarBeto

Backlog of **technical tasks, technical debt, and improvements** detected during
development.

It does not replace the phased roadmap in [`AGENTS.md`](AGENTS.md) (sections 26
and 27), which sets the construction order of the project. This file holds the
concrete things that come up while programming and that are not an entire phase.

**Statuses:** `pending` · `in progress` · `done`

---

## T-001 · Generate the frontend types from the backend's OpenAPI

**Status:** done
**Detected in:** Phase 3 (web interface), while refactoring the React code.

> **How it was resolved (session summary):** `openapi-typescript` was discarded
> because it requires `typescript@^5` as a peer and the project uses
> TypeScript 7 (the native compiler), which no longer exposes the compiler API
> (`ts.factory`). A custom dependency-free generator was written,
> `frontend/scripts/gen-api.mjs`, which reads `/openapi.json` from the running
> backend and produces `frontend/src/types/api.ts`:
> - it fails if any of the types that the frontend aliases is missing (the guard
>   already caught real drift: the body is called `MotionRequest`, not
>   `MotionCommand`);
> - it treats response fields as always present (the backend serializes
>   everything), reserving `| null` for those that model `None`;
> - `src/types/rover.ts` is now a re-export of the generated names (the only
>   original thing is `AiStreamMessage`, which goes over WebSocket and is not in
>   the OpenAPI).
> Command: `npm run gen:api` (with `ROVER_API_URL` to point to another backend;
> on port 8000 it is advisable to verify that Docker/something else does not have
> it occupied).

### Context

`frontend/src/types/rover.ts` is **manually duplicated** from the backend's
Pydantic models:

| TypeScript type  | Backend source                                  |
| ---------------- | ----------------------------------------------- |
| `RoverStatus`    | `app/rover/models.py`                           |
| `ConnectionState`| `app/rover/models.py`                           |
| `MotionCommand`  | `app/rover/models.py`                           |
| `TelemetrySnapshot` | `app/telemetry/service.py`                   |
| `HealthResponse` | `app/api/schemas/health.py`                     |

Any change in the backend (adding a telemetry field, renaming
`battery_percentage`, adding a state to `ConnectionState`) **does not break
compilation**: the frontend would keep compiling against an outdated type and the
failure would show up at runtime, as an `undefined` field rendered in the
interface. It is exactly the kind of silent failure that the project wants to
avoid.

### Scope

- Generate the TypeScript types from `GET /openapi.json` (FastAPI already exposes
  it) with [`openapi-typescript`](https://github.com/openapi-ts/openapi-typescript).
- Replace the manual content of `src/types/rover.ts` with the generated types,
  keeping readable aliases (`RoverStatus`, `TelemetrySnapshot`, ...) so as not to
  touch the components.
- Add an npm script (`npm run gen:api`) and document it.

### Acceptance criteria

- [ ] `npm run gen:api` regenerates the types from the running backend.
- [ ] No API type is written by hand in the frontend.
- [ ] A field change in the backend causes a **compilation error** in the
      frontend if the types have not been regenerated.
- [ ] `npm run typecheck`, `npm test`, and `npm run build` still pass.
- [ ] `README.md` documents the command and when it has to be run.
- [ ] It is compatible with the "no hardware" rule: the backend in
      `simulator` mode already serves the OpenAPI.

### Notes and risks

- **Decide whether the generated file is version-controlled.** Recommended:
  **yes** (it allows compiling and building the Docker image without a backend
  running) and add a check in the build that it is up to date.
- `openapi-typescript` is a **development** dependency: it does not go into the
  bundle.
- The generated names come from the `response_model`s, which is where Pydantic
  publishes `RoverStatus` and `TelemetrySnapshot` in `components.schemas`.
- Implicit dependency: if an endpoint stops declaring its `response_model`, the
  generated type loses reliability. Keep the `response_model`s up to date.
- There is no need to regenerate on every production build if the file is
  version-controlled.

---

## T-002 · Remove the RTP packet remux in MediaMTX

**Status:** done
**Detected in:** Phase 5a, in the MediaMTX logs.

> **How it was resolved (session summary):** `udpMaxPayloadSize: 1472` in
> `docker/mediamtx.yml`. The parameter counts the full UDP payload **including
> the RTP header (12 bytes)**: 1472 − 12 = 1460, exactly the size of
> our H.264 packets. With 1472 + 8 (UDP) + 20 (IP) = 1500 it fits in the
> standard MTU, without remux or fragmentation. Verified live: **0 warnings**
> after the change with a WebRTC reader actually reading.
>
> **Robustness gap found in the process (new, T-003):** restarting
> MediaMTX does not recover the publisher: the camera does not publish again
> until the api is also restarted.

### Context

MediaMTX warns on every start of the stream:

```
[path rover] RTP packets are too big (1460 > 1440), remuxing them into smaller ones
```

It resolves it on its own, so **it does not break anything**, but it forces
MediaMTX to repacketize every packet. On the Pi that is CPU that adds to the
encoder and the inference, and extra work in the lowest-latency path.

### Scope

- Adjust the encoder so that it does not generate packets above the effective
  MTU: lower bitrate, smaller keyframes, or the equivalent `-x264-params`.
- Or adjust `udpMaxPayloadSize` in `docker/mediamtx.yml` if the problem is the
  MTU.
- Measure before/after with the MediaMTX logs and `inboundBytes`.

### Acceptance criteria

- [ ] The message `RTP packets are too big` disappears from the logs.
- [ ] RNF1 (latency) and RNF2 (≤ 3 Mbit/s) from the spec are maintained.
- [ ] The video keeps decoding without losses.

### Notes and risks

- Low priority: it is efficiency, not correctness.
- Lowering the bitrate reduces quality; it has to be balanced, not simply
  lowered.
- Verify on the Pi: that is where the CPU cost really matters.

---

## T-003 · The camera does not publish again after restarting MediaMTX

**Status:** done
**Detected in:** T-002, while restarting MediaMTX to verify the remux.

> **How it was resolved (session summary):** a stream health watchdog
> (`app/camera/health.py`) that every 2 s does a raw RTSP `DESCRIBE` to the
> publication URL: `200 OK` = alive, anything else (or a connection error) =
> dead. If the death is confirmed **3 checks in a row**, it restarts the
> camera (`reload`, the same path as the model change) with bounded backoff
> (5/15/30 s) that resets with the first healthy check.
>
> A direct RTSP `DESCRIBE` was chosen because the MediaMTX HTTP API responded
> 404 to all its routes without a clue (not even with auth).
>
> Verified live: **restarting MediaMTX** (without touching the api), the
> watchdog detected the death at ~5 s, restarted the camera, and the stream was
> published again (`DESCRIBE` → `200 OK`). It only applies to the IMX500 camera:
> the simulated one already self-heals its own FFmpeg.

---

## T-004 · False "Backend unreachable" banner due to transient Wi-Fi blips

**Status:** done
**Detected in:** post-Phase 5 session, user complaint (the banner appeared after
a while of inactivity).

> **How it was resolved (session summary):** the Pi's `wlan0` link to
> the router is marginal (-56/-58 dBm, congested channel, 1408 retries in
> ~4 h) and, after a period of inactivity, the first packets get stuck for a few
> seconds. The frontend marked "Backend unreachable" with **a single** timeout of
> 5 s — first-hand evidence: an SSH connection of our own to the Pi timed out and
> recovered on retry, without touching the backend.
>
> Solution: debounce in `frontend/src/lib/roverState.ts` —
> `FAILURE_BANNER_AFTER = 3` **consecutive** failures before marking `offline`
> and showing the banner; any success resets the counter. **Safety is not
> touched**: the command loop of `useRover` still aborts motion on the
> first delivery failure (`releaseCommand()`); only the *indication* is deferred.
>
> Verified: 42 frontend tests green (new cases: 1 and 2 failures do not
> activate the banner, the 3rd does, success resets), clean typecheck, deployed
> on the Pi (bundle `index-Dj_L-YfD.js`), real telemetry ~30 ms.

---

## T-005 · Ghost DNS 192.168.4.1 in the Pi's `/etc/resolv.conf`

**Status:** done
**Detected in:** T-004, while rebuilding the frontend on the Pi.

> **How it was resolved (session summary):** `192.168.4.1` is the gateway of
> the **WAVE ROVER UGV** network (wlan1 = chassis client, IP 192.168.4.2).
> Since it is the motors' network, **re-activating the UGV profile is forbidden**
> (`nmcli con up UGV`) to apply changes: re-associating wlan1 would cut the
> critical link to the motor controller.
>
> Non-invasive solution:
> - `sudo nmcli con modify UGV ipv4.ignore-auto-dns yes` → on the next
>   DHCP renewal of wlan1, NM no longer mixes the chassis DNS into `resolv.conf`
>   (the profile still has `ipv4.dns: --`, it was only necessary to ignore the
>   DHCP).
> - Rewrite `/etc/resolv.conf` by hand (scp + `sudo cp`) leaving only
>   `nameserver 192.168.1.1` — zero interruption of wlan1.
>
> Verified on the Pi:
> - `resolv.conf` with only `192.168.1.1` (the ghost is no longer queried);
> - `getent ahostsv4 registry-1.docker.io` → resolves (98.83.57.58);
> - TCP 443 to `registry-1.docker.io` → OK (the build no longer depends on
>   retries);
> - **link to the chassis intact**: ping to 192.168.4.1 0 % loss, `wlan1` still
>   has 192.168.4.2, `rover/status` → `connection: connected`.
>
> Process note: the first rewrite of `resolv.conf` from PowerShell left
> literal `\n` (escaping) and broke resolution — it was fixed by writing the
> file locally and copying it (scp + `sudo cp`), which is the method to repeat.

### Context

`/etc/resolv.conf` (generated by NetworkManager) lists two DNS servers:

```
nameserver 192.168.1.1   ← home router (DHCP of wlan0), correct
nameserver 192.168.4.1   ← gateway of the WAVE ROVER UGV network (wlan1, the
                           chassis/motor controller): its DHCP DNS
                           announcement exists, but there is NO listener on :53
                           there (connection refused when querying it)
```

The Pi's `wlan1` is a **client** on the chassis network (IP 192.168.4.2,
gateway 192.168.4.1 = WAVE ROVER): the motors' network. It is not an AP of the
Pi.

When the link to `192.168.1.1` falters (the same problem as T-004), Docker
falls back to the ghost DNS and the build/download fails:

```
failed to do request: Head "https://registry-1.docker.io/...": lookup
registry-1.docker.io on 192.168.4.1:53: read: connection refused
```

With a healthy link resolution works and retrying the build fixes it (verified:
second attempt, exit 0). But it is fragile.

### Scope

- Remove the merge of the chassis DNS into `resolv.conf` **without re-activating
  the UGV profile** (re-associating wlan1 would cut the critical link to the
  motors): `sudo nmcli con modify UGV ipv4.ignore-auto-dns yes` (it stops mixing
  the DNS from wlan1's DHCP on the next renewal) + manual rewrite of
  `resolv.conf` (scp + `sudo cp`, not from PowerShell because of the `\n`
  escaping).
- Discarded alternative: set the DNS of the docker daemon in
  `/etc/docker/daemon.json` (`"dns": ["192.168.1.1", "1.1.1.1"]`) — it requires
  restarting the daemon (it restarts the containers; it adds nothing once the
  ghost is not announced).

### Acceptance criteria

- [x] `docker compose up -d --build` on the Pi does not depend on retrying
      because of DNS: `getent` resolves `registry-1.docker.io` and TCP 443
      responds; the only nameserver is the router's.
- [x] The link with the WAVE ROVER is not interrupted: wlan1 still has
      192.168.4.2, ping to the chassis 0 % loss, `rover/status` →
      `connection: connected`.

### Notes and risks

- **WARNING**: do not run `nmcli con up UGV` / `con down UGV` without a reason —
  it is the critical network to the motor controller. Profile changes are applied
  with `nmcli con modify` (via `sudo`, the profile is system-wide) without
  re-activating.
- To rewrite `resolv.conf` manually, use scp + `sudo cp` from a
  local file: it avoids the `\n` escaping of PowerShell strings.

---

## T-006 · Add the remaining telemetry metrics

**Status:** pending
**Detected in:** Phase 6 review; `AGENTS.md` §16 lists more fields than are exposed.

### Context

`TelemetrySnapshot` only exposes `timestamp`, the rover status,
`cpu_temperature_c`, `ai_inference_ms`, and `detections`. `AGENTS.md` §16 also
lists `wifi_signal`, `cpu_usage`, `memory_usage`, `disk_usage`, and `camera_fps`.
Not all sensors are guaranteed, so the fields must stay optional.

### Scope

- Add the metrics that can be read reliably on the Pi (Wi-Fi signal, CPU, memory,
  disk, camera FPS) as **optional** fields that are `null` when unavailable.
- Keep `/telemetry` working unchanged off the Pi.
- Document the new fields in `README.md`.

### Acceptance criteria

- [ ] New fields are optional and `null` when the source is missing.
- [ ] `pytest` covers the present/absent cases with mocks.
- [ ] No new hard dependency without justification (or read `/proc` directly).

### Notes and risks

- `camera_fps` already exists in `/camera/status`; decide whether to mirror it.
- `psutil` would be a new dependency: justify it or parse `/proc`/`/sys`.

---

## T-007 · Decide Wi-Fi vs serial transport for the WAVE ROVER

**Status:** done
**Detected in:** `docs/specs/wave-rover.md`, "Pending decision".

> **How it was resolved (session summary):** the transport-agnostic logic was
> extracted into `app/rover/wave_rover_chassis.py`; `WaveRoverWifiDriver` became a
> thin HTTP transport over it, and a new `WaveRoverSerialDriver` (pyserial) added
> the UART path. Selection is `WAVE_ROVER_TRANSPORT` (`wifi` default; `serial`
> opted in on the Pi). The serial driver **does not wait for a reply on motion
> commands** (fire-and-forget, like Wi-Fi) and skips the chassis's command echo;
> status/rate queries still read the reply. Verified: benched in the container on
> the unit with the rover stopped, then driven live — command latency dropped from
> ~1 s (waiting for feedback) to **35–51 ms** end-to-end. The container user was
> added to the `dialout` group (`Dockerfile.pi`) so it can open `/dev/ttyAMA0`.

### Findings (verified on the unit, 2026-10-09)

- **No cabling is needed.** The official method is *"connect the robot to the
  Raspberry Pi … via a 40PIN UART interface"*; the Pi is already mounted on the
  chassis through that header, so the UART is wired already.
- **The header UART was disabled** and had to be enabled. The official
  `ugv_rpi/setup.sh` config, applied and verified:
  - `config.txt`: `dtparam=uart0=on`, `enable_uart=1`, `dtoverlay=disable-bt`.
  - `cmdline.txt`: remove `console=serial0,115200`.
  - Effect: `/dev/serial0 -> ttyAMA0`, `GPIO14 = TXD0`, `GPIO15 = RXD0`.
- **The chassis answers on `/dev/ttyAMA0` at 115200.** `{"T":130}` returns
  `{"T":1001,"L":0,"R":0,"r":..,"p":..,"y":..,"temp":..,"v":..,"c":..,"pwr":..,"ov":false}`.
- **Side effect:** `dtoverlay=disable-bt` disables Bluetooth (revertible).
- **Backups:** `~/rovercarbeto-backups/config.txt.bak-20261009-122004` and
  `cmdline.txt.bak-20261009-122004`.

### Decision

Add a serial transport **behind the same `Rover` interface**, selectable with
`WAVE_ROVER_TRANSPORT`. It is **benched and verified**, and runs in production on
the unit (`WAVE_ROVER_TRANSPORT=serial`); `wifi` remains the **code default**, so
rolling back is just removing that line from the Pi's `.env`.

### Scope

- Extract the transport-agnostic logic into a shared base (pure functions, battery
  and charge inference, command/feedback parsing).
- Add `WaveRoverSerialDriver` (pyserial); keep `WaveRoverWifiDriver`.
- Config + factory selection; tests.

### Acceptance criteria

- [x] `/dev/ttyAMA0` enabled and the chassis answers (verified).
- [x] Serial transport behind the same interface; Wi-Fi default unchanged.
- [x] Tests added; simulator and API unaffected.
- [x] Bench test with the rover stopped.

### Notes and risks

- Bluetooth stays disabled while `dtoverlay=disable-bt` is present.
- The serial reply is line-based JSON; a command may produce several lines.

---

## T-008 · Document a deployment rollback

**Status:** pending
**Detected in:** `docs/specs/live-video.md` diagnostics ("deployment strategy
without documented rollback").

### Context

Deployment to the Pi is a manual `docker compose` run; there is no documented
rollback and images are not version-tagged.

### Scope

- Document the rollback procedure (back up the compose file, restore, `up -d`).
- If images are ever version-tagged, document pinning a version in Compose.

### Acceptance criteria

- [ ] The rollback procedure is written down.
- [ ] A rollback has been rehearsed at least once.

### Notes and risks

- The project intentionally avoids CI/CD (`AGENTS.md` §7), so this stays manual.

---

## T-009 · End-to-end tests for the frontend

**Status:** pending
**Detected in:** Phase 3-6 review; only unit tests exist today.

### Context

The frontend has 42 Vitest unit tests but no browser-level (end-to-end) coverage
of driving, stopping, or the "no video" fallback.

### Scope

- Add a minimal browser test suite against the **simulator** backend.

### Acceptance criteria

- [ ] Runs without hardware.
- [ ] Covers move/stop and the "no video" banner.
- [ ] Kept separate from the fast default test run.

### Notes and risks

- Adds a dependency (e.g. Playwright); weigh the value against the cost.

---

## T-010 · Authentication if the API is exposed beyond the LAN

**Status:** pending
**Detected in:** Phase 4 review; the API has no authentication.

### Context

The API is open. On a private rover LAN that is acceptable; if it is ever exposed
beyond the LAN, an unauthenticated motion endpoint is a risk.

### Scope

- Conditional: only act if the exposure changes. Prefer a simple token/basic auth
  at the edge (nginx) over touching every route.

### Acceptance criteria

- [ ] When enabled, motion endpoints reject unauthenticated requests.
- [ ] Simulator/development is unaffected by default.

### Notes and risks

- Do not add until there is a real need; it must not weaken the safety layer.

---

## Template for new tasks

```markdown
## T-00N · Short, concrete title

**Status:** pending
**Detected in:** phase or context

### Context
What problem exists and what consequence it has if it is not fixed.

### Scope
What is included and what is not included in the task.

### Acceptance criteria
- [ ] Verifiable, in the imperative.

### Notes and risks
Open decisions, dependencies, cost.
```
