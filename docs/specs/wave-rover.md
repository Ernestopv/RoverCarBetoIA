# Spec — WAVE ROVER (Phase 4)

Status: driver implemented and **verified by reading the real chassis**. Pending the
verification with movement, which requires explicit authorization.

## Goal

Control the WAVE ROVER chassis from the Raspberry Pi over Wi-Fi, with the same
`Rover` interface used by the simulator, and without exposing protocol details to
the API.

## Protocol (verified against the unit, not invented)

Transport: **HTTP GET**, with no authentication or session.

```http
GET http://192.168.4.1/js?json={"T":130}
```

The network is created by the chassis itself: AP **`UGV`** at **`192.168.4.1`**. The Pi
connects through a second interface (`wlan1`).

| Command | JSON | Response |
| --- | --- | --- |
| `CMD_SPEED_CTRL` | `{"T":1,"L":<l>,"R":<r>}` | — |
| `CMD_BASE_FEEDBACK` | `{"T":130}` | `{"T":1001,...}` |
| `CMD_GET_IMU_DATA` | `{"T":126}` | `{"T":1002,...}` |

`L`/`R` are wheel speeds in **-0.5 … +0.5** (0.5 = 100 % PWM; this
chassis has no encoders). **There is no STOP command**: stopping is `T:1` with
`L=0, R=0`.

Real feedback of `T:130` captured from the unit:

```json
{"T":1001,"L":0,"R":0,"r":-5.157,"p":-18.017,"y":168.188,
 "temp":61.67,"v":12.15782,"c":582.0,"pwr":8940.0,"ov":false}
```

`v` = pack voltage · `r/p/y` = attitude · `L/R` = current speeds.

## Mapping to the internal model

The internal model uses `linear`/`angular` in -1…1; the chassis uses wheels. The
differential mix lives **only in the driver**:

```text
left  = linear - angular
right = linear + angular
      → rescaled to fit within ±0.5 preserving the ratio
```

## Edge cases

| Case | Behavior |
| --- | --- |
| No link | `RoverConnectionError`; the state becomes `disconnected` |
| No response | `RoverTimeoutError` after `WAVE_ROVER_TIMEOUT` |
| Invalid JSON | `RoverProtocolError` |
| Failure refreshing status | The last reading is kept (the screen is not cleared) |
| STOP with link down | The local state is cleared anyway; the chassis stops on its own |

## Safety

- The chassis has **its own 3 s heartbeat**: without new commands, it stops
  on its own. It is a third safety net, independent of the Pi.
- Our watchdog (0.5 s) stops earlier, and the command loop resends every 150 ms.
- The safety layer clamps the speeds before they leave the backend.
- **No automated test triggers physical movement.**

## Calibration

Three **independent** adjustments. The first two are changed without rebuilding the image.

### 1 · Per-wheel trim (so it goes straight)

`WAVE_ROVER_LEFT_TRIM` / `WAVE_ROVER_RIGHT_TRIM`, in the Pi's `.env`.

Procedure: drive straight for 3.5 s at ~30 % PWM and observe. If the robot drifts
**to the right**, the left wheel is running faster: lower `LEFT_TRIM`. Conversely,
lower the right one. It is applied **after** normalizing and is clamped to the
protocol range, so the correction is not undone.

**Calibrated value for this unit** (2026-10-07, battery ~11.7 V):

```env
WAVE_ROVER_LEFT_TRIM=0.95
WAVE_ROVER_RIGHT_TRIM=1.0
```

> Calibration depends on voltage: with less charge there is less torque and
> static friction weighs more. If it starts to twist again as it discharges, it is
> not a fault.

### 2 · Joystick feel (precision)

`frontend/src/lib/input.ts`:

```ts
export const STICK_DEADZONE = 0.06;
export const STICK_EXPO = 0.35;
```

- **Deadzone**: ignores center jitter, so that "centered" really means
  going straight.
- **Expo**: `0` linear, `1` cubic. It gives fine control near the center **without
  losing travel** at the extreme (`out(1) = 1`); the remaining travel is rescaled, so
  there is no jump when leaving the deadzone.

It requires rebuilding the interface (`up -d --build ui`). The `Forward` /
`Turn` indicator on the panel shows the already shaped command, so the calibration
is visible on screen: half travel reads ≈0.35 instead of 0.50.

### 3 · Joystick → wheels mapping

`app/rover/wave_rover_wifi.py::mix_differential`. It converts `linear`/`angular`
(±1) into `L`/`R` (±0.5) preserving the ratio, and applies the trim at the end.

### Where the calibration lives

The Pi's `.env` (`~/rovercarbeto/.env`). **It is not in the repository**, because
it is specific to this unit: `.env.example` documents the values and the
procedure, not the result.

## Stop on link loss (verified)

It is the most important safety net, because it acts when the Raspberry Pi can no
longer do anything:

| Layer | Where it lives | Does it survive the Pi going down? | Status |
| --- | --- | --- | --- |
| Speed clamping | backend | No | ✔ tests |
| Watchdog (0.5 s without commands) | backend | No | ✔ seen in logs |
| **Chassis heartbeat (3 s)** | **chassis** | **Yes** | **✔ verified live** |

**Test performed**: the robot was moving forward at 30 %; the link to the
chassis was cut for 7 s. Since the link was cut, **our watchdog could not deliver
its STOP either** — the robot was left with the last command received. It
stopped on its own. The credit goes exclusively to the chassis firmware.

Technical detail of the test (a trap to remember): the API runs in a container,
so its traffic **does not go through the host's `OUTPUT` chain** but through
`FORWARD`. Cutting on `OUTPUT` does nothing and the test comes out invalid silently.
The test includes an **explicit verification** that the cut takes effect
before moving anything.

## Battery: what was measured

A 90 s probe on the real chassis (2026-10-07):

- The chassis measures voltage with **~5 mV resolution** and current (`c`, mA).
- The voltage oscillates ±50 mV with load (360–870 mA at rest: the whole system
  is powered from the pack), but it **was not smoothed**, and the percentage was
  calculated with a straight line between 9.9 and 12.6 V. Result: the number jumped
  or stayed stuck at the integer 83 %, because the plateau of the Li-ion
  curve makes 12.1 V last a long time almost without moving.

Changes applied (return to the battery improvements):

1. **Discharge curve** (`WAVE_ROVER_BATTERY_CURVE`): piecewise interpolation
   of a real 3S Li-ion table instead of the straight line. On the plateau it reports ~85 %
   for 12.15 V and, importantly, **does not hide a depleted pack**: at 10.5 V the
   straight line gave 22 % and the curve gives 5 %.
2. **Smoothing**: moving average of 8 voltage readings (deque). It kills the load
   ripple and reveals the real trend.
3. **Current** exposed: `battery_current_ma` in the status and a meter in the
   interface, because the chassis already reported it and now it explains the variations.

Measured after the change: `V=12.17 V → 85.7 %`, with smooth variation (~0.5 % between
readings) and live current (~450–615 mA).

### Charger detection (inferred, not measured)

The chassis does **not** report "charger connected": there is no field for that. But the
transition leaves a clear fingerprint in the voltage — and crucially, the charger
fingerprint is **orders of magnitude larger** than normal noise:

| Signal | Measured magnitude |
| --- | --- |
| Plug in / unplug | change of ~0.25-0.35 V **in seconds** (~1500 mV/min) |
| Smoothed voltage ripple | tens of mV |
| Discharge trickle at rest | ~15-20 mV/min |

With that signature, the driver:

- measures the slope of the smoothed voltage over a 120 s window;
- **ignores the trend until it has 60 s of history** (a startup decides nothing
  about noise);
- with slope > **+150 mV/min** → `charging`; < **−150 mV/min** → `discharging`;
  otherwise it **keeps the last verdict** (hysteresis, it does not blink);
- exposes it as `battery_charge_state` in the telemetry and as a
  "Charging" indicator in the interface.

The clock is injectable so that tests can advance the window without sleeping.

**Practical warning**: the charger holds the voltage ~0.25 V **above** the
pack's real resting voltage, so while it is plugged in the percentage read from the
voltage is **inflated** (measured: 77-79 % with the real pack at ~55 %). With the
charger connected, the reliable reading is the current and the Charging state, not the %.

## Acceptance criteria

| Criterion | Status |
| --- | --- |
| Wi-Fi connection and `connection: connected` | ✔ verified |
| Real battery voltage and percentage | ✔ 12.17 V → 85.7 %, live current |
| Charger detection (`battery_charge_state`) | ✔ transition verified live (charging on plug in) |
| Real heading from the chassis IMU | ✔ (see note on the magnetometer) |
| Latency per command | ✔ 20.2 ms |
| Differential mix within ±0.5 | ✔ unit tests |
| Explicit STOP (`T:1` with 0,0) | ✔ verified |
| Watchdog: stops after 0.5 s without commands | ✔ it fired during the tests |
| **Stop on link loss (chassis heartbeat)** | ✔ **the robot stopped on its own** |
| Trim calibrated (goes straight) | ✔ `LEFT_TRIM=0.95` |
| An isolated failure does not block the driver | ✔ fixed (see below) |
| `pytest` green | ✔ 85 tests |
| `move` produces useful movement | ✔ verified (limited by the power supply) |

## Commissioning findings

### `boot.mission` disables movement on every boot

The chassis carries a boot file with `{"T":138,"L":0,"R":0}` repeated. The
*speed rate* **0 means the chassis ignores all movement commands** (not "slow
speed": nothing). Since it is reapplied on every power-up, without handling it the robot
would not respond after each power cycle.

The driver resolves it on connect: it reads the rate (`T:139`) and **only changes
it if it is zero**, respecting a manually chosen value. Configurable with
`WAVE_ROVER_SPEED_RATE` (0..1; the chassis rejects values > 1).

**A low rate moves little**: it remains the main suspect for the weak movement.

### An isolated failure must not block the driver

First version: on a timeout it flagged `ERROR` and `is_connected` stopped being
true, so **all subsequent commands responded 503** until the process was
restarted. Fixed: a failure is *reported* (status + `last_error`) but does not close
the door, and any response recovers `CONNECTED`.

### Yaw is not useful to verify movement

The heading of this chassis comes from the **magnetometer**. A 43° jump was
measured without sending any command, and disturbances from motors and metal
deflect it. **It is not a reliable indicator that the robot has turned**; movement
verification requires direct observation.

## Note on power

During commissioning the robot moved with very little force. Using data, the
power cut-off (35/35 responses while driving, p95 32 ms) and the voltage drop
(0.086 V) were ruled out, and the command turned out to be identical to the one from
the official web. After fixing the power, **the movement works**.

It remains a recommendation from the wiki itself: use 18650 cells with a **high
discharge rate**. With normal cells the torque drops and the chassis moves with less force,
especially with a low battery.

## Pending decision: Wi-Fi or serial

The official Waveshare program (`ugv_rpi/base_ctrl.py`) uses **serial UART** at
115200 (`/dev/ttyAMA0`), not Wi-Fi. On this Pi the port is `/dev/serial0 →
ttyAMA10` and it is **taken by the system console** (`console=serial0,115200`),
so using it would require editing `cmdline.txt` and restarting.

Wi-Fi was implemented because `AGENTS.md` specifies it and because it is verified
(16–29 ms per command). The differential mix and the protocol parsing are
pure functions, agnostic of the transport, so adding a serial transport later would be a local change.
