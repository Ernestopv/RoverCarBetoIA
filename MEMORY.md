# MEMORY.md

Persistent notes for AI agents working in this repository.

It records **explicit user decisions** and **protected functionality**.

> If something here looks redundant, like dead code, or improvable: **it is not,
> it is deliberate**. Read it before refactoring, deleting, or "cleaning up".

---

## ⛔ PROTECTED · «Sim» view of the video panel

**Explicit user decision.** Do not delete, do not simplify, do not degrade.

### What it is

The synthetic scene of the video panel, drawn in the browser with canvas, which
**reacts to the joystick**: it scrolls the ground according to `linear` and moves
the vanishing point according to `angular`.

```text
frontend/src/components/SimulatedFeed.tsx   ← the canvas
frontend/src/components/VideoPanel.tsx      ← Live / Sim selector
```

### How it behaves

| Situation | Result |
| --- | --- |
| `CAMERA_MODE=simulator` | Starts in **Sim** (the normal development case) |
| `CAMERA_MODE=imx500` | Will start in **Live** |
| `Sim` view | Label "Simulated view". **No** error banner |
| `Live` view without signal | Banner "NO LIVE VIDEO" + reason + URL + Retry button |

### Why it is protected

1. It is the **visual driving feedback** while there is no real camera. The
   pattern that FFmpeg publishes (`testsrc2`) is **static**: it does not react to
   anything.
2. It has already been deleted **twice** for being considered "a placeholder",
   and the user had to ask for it to come back both times.

### Rules if it has to be touched

- **Never** remove the reactivity to `linear` / `angular`: it is its reason to
  exist.
- **Never** leave it unlabeled. A rover is driven by camera, and a fake feed that
  looks real is worse than a black panel. The "Simulated view" label or the
  "NO LIVE VIDEO" banner must always be visible.
- **Never** degrade it to "fallback only". That was the mistake: as a *fallback*
  it is never seen while the stream works, and the user is left without feedback.
- The `<video>` must remain **always mounted** even when it is covered: if it is
  unmounted, the `ref` is `null` when the WebRTC track arrives and the stream
  does not hook up.

### Verification

Measured in Chrome by comparing pixels between frames:

```text
Rover stopped ............... 0 pixels change (out of 4644)
Joystick at 0.80 ............ 774 pixels change (77 %)
```

---

## Other explicit user decisions

Do not revert without asking first:

- **Interface in English.** All text visible to the user is in English.
- **No STOP button.** It was removed at the user's request. Stopping is covered
  by: releasing the joystick (with reinforced release on loss of focus and window
  blur), the Space key, the backend watchdog (0.5 s), and the
  `POST /api/v1/rover/stop` endpoint.
- **Speed control (throttle)** in the Drive panel. It is a **limit**: it can
  never amplify a command, and `NaN`/`Infinity` fail to 0 (no movement).
- **Video: WebRTC via MediaMTX**, not µStreamer/MJPEG. Discarded because of
  bandwidth (2.5 vs 10–40 Mbit/s) and, above all, because the IMX500 only
  delivers inference through Picamera2, which must be the sole owner of the
  camera.

---

## Mistakes already made · do not repeat

- **Deleting code that works and the user already approved** without asking. It
  happened with `SimulatedFeed` and with the STOP button. When in doubt: ask, do
  not delete.
- **Declaring an improvement as done without being able to see it.** In this
  environment the agent cannot see images: verify layouts and colors by measuring
  the DOM, with pixels, or with screenshots that the user reviews.
- **Recomputing by hand what the library already does.** With the IMX500, the
  crop, the scaling, and the mirroring of the coordinates were written by hand,
  instead of using `IMX500.convert_inference_coords()` and the
  `network_intrinsics` settings. A "horizontal offset" was chased for days that
  was that self-made calculation. The official AI Camera documentation says it
  explicitly: the sensor crops by the ROI and the library converts. **Before
  writing a coordinate mapping, look for the official helper.**
- **Taking a fact as good without measuring it.** The detection spec claimed that
  "the inference runs on raw sensor data, which is why the boxes have to be
  mirrored". Nobody checked it, it guided the design, and it turned out to be
  **false**: when removing the mirror and using `convert_inference_coords`, the
  boxes line up over the live video. The mirror *was* the error. The same with
  the coordinate order: `picamera2` contradicts itself between `scale_boxes`,
  `scale_coords`, and `draw_keypoints`. **Order and orientation are measured in
  the data, not read in the documentation.**
