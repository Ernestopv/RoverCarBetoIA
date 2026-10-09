# Spec — AI detection (Phase 6)

Status: backend, overlay, and tracking implemented, with tests green and **the
coordinate mapping validated by eye on the live video**. Phase 6 closed. See
*Migration to the official approach*.

Reference for the sensor, the API, and the model catalog:
[`imx500.md`](imx500.md).

## Objective

Turn what the rover's camera sees into usable object detections, without
recording anything, and expose them to the interface.

## How it works

The network runs **inside the IMX500 sensor**, not on the Raspberry Pi:

```text
IMX500 (neural network on the sensor)
   │  already post-processed tensors
   ▼
Picamera2 · capture_metadata()  ← coexists with start_recording(): verified
   │
   ▼
InferenceFrame  →  decode_detections()  →  GET /api/v1/ai/detections
                                              →  overlay in the browser
```

There is no NMS to do on the Pi: the model is the `_pp` variant (post-processed) and
returns the boxes already decoded.

## Facts verified on the unit

| Item | Value |
| --- | --- |
| Model | `imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk` |
| Task | object detection · 90 labels · input **320×320** |
| Outputs | `[(1,100,4), (1,100), (1,100), (1,1)]` |
| Box format | **(y0, x0, y1, x1), already normalized 0..1** |
| Observed confidences | 0.07 .. 0.73 |
| Latency | ≈ **26 ms** per inference |
| Inference rate | 26 fps declared |

### `bbox_normalization` is read backwards

`efficientdet_lite0_pp` declares `"cpu": {"bbox_normalization": true}` and returns
values in **0..320**. That is **not** a lie from the metadata: the flag means
*"they are pixels, they must be normalized"*, not *"they are already normalized"*. The official example
does exactly that:

```python
if intrinsics.bbox_normalization:
    boxes = boxes / input_h
```

Reading it straight led to boxes like `x[-218.97..-5.72]`. SSD-MobileNetV2 declares
nothing because it already returns 0..1.

### `output[3]` is not the number of detections

It equals `[100.0]`, which is the number of *slots*. The model fills up to 100
and you must filter by score to know how many are real.

### Orientation with respect to the video: resolved — no mirroring

The spec previously claimed that the inference runs on raw sensor data and that
therefore the boxes have to be mirrored. **It was false.** With the official conversion in
place, the boxes fall on top of the objects as they appear in the stream, without
applying any rotation. The mirror that was applied before was precisely what
decentered them.

Verified by eye by the user on the live video.

## Migration to the official approach (applied)

The root error was **recomputing by hand** what the sensor and the library already do:
the crop (sensor ROI) and the coordinate conversion. This is what was done:

### 1. `app/camera/imx500.py`

- **Out** `_normalize_boxes` (with its value-range heuristic) and
  `_visible_region` (the `ScalerCrop` crop computation by hand).
- **In** `imx500.convert_inference_coords(box, metadata, picam2)` per box: the
  official helper, which returns the box in pixels of the ISP output image.
  From there, divide by the stream size to get 0..1.
- The settings **are read from the network** instead of being assumed: `bbox_normalization`,
  `bbox_order`, and `preserve_aspect_ratio` from `imx500.network_intrinsics`.
- `imx500.set_auto_aspect_ratio()` is called when the network declares
  `preserve_aspect_ratio`, so that the ROI matches the input tensor.
- It filters by threshold **before** converting, as the official example does: the network
  offers 100 slots per frame and converting the empty ones is wasted work.

### 2. `app/ai/detection.py`

- **Out** `crop_to_frame`, the `normalized` flag, and `mirror_box`, along with their tests.
- **In** `normalize_sensor_boxes`, which interprets what the network declares about
  its own boxes. It is pure and testable, and there is the only pitfall left:
  `bbox_normalization: true` means *"they are pixels, normalize them"*, not *"they are already
  normalized"*. The name is read backwards.
- `InferenceFrame` now only carries final boxes in
  `(x_min, y_min, x_max, y_max)` over `0..1`.

### 3. Configuration

- `camera_network_file` default → `ssd_mobilenetv2_fpnlite_320x320_pp`.
- The threshold (`AI_SCORE_THRESHOLD`) also reaches the camera, which uses it to avoid
  converting boxes that will be discarded. Value on the Pi: 0.55, the one from the official
  example.

### 4. Verification

- On the unit, with the migration applied, startup logs what the network declares:
  `bbox_normalization=False, bbox_order=yx, preserve_aspect_ratio=False`, which
  is correct for SSD-MobileNetV2.
- The boxes come out **within range** (`x[0.010..0.852] y[0.764..0.999]`), without the
  negative values or the collapses at `~1.0` of the by-hand attempts.
- **Pending**: check it by eye with the overlay, and decide on the mirror.

## Design

- `app/ai/detection.py` — models (`Detection`, `DetectionSnapshot`),
  `InferenceFrame`, pure decoding, and `DetectionService`.
- `app/ai/tracking.py` — stable identity across frames: greedy
  IoU matching between boxes of the same label, with a grace period so that an
  object occluded for a couple of frames recovers its identity. It is pure logic and is
  tested without hardware.
- `app/ai/pose.py` — the equivalent for the pose network: joints, COCO names,
  and skeleton. It discards the joints the network left at zero and derives the
  box from the ones it did find.
- `app/ai/broadcast.py` — the bridge between the camera thread and the event
  loop: it notifies whoever is listening when there is a new result, without delivering
  the data to them, so that a slow browser does not slow down the inference or the
  others.
- The inference loop lives in the camera driver, in a **separate thread**,
  because `capture_metadata()` blocks and blocking the event loop would freeze
  the whole API. It publishes the last result (the most recent one wins) and notifies.
- `DetectionService` consumes the camera through the `InferenceSource` protocol, and
  `PoseService` through `PoseSource`, so they do not depend on the concrete
  implementation. The same camera implements both.
- `GET /ai/detections`, `GET /ai/pose`, and **`WS /ai/stream`**. The WebSocket is what
  the interface uses: the backend pushes each result as soon as it arrives.
- Frontend: `DetectionOverlay` draws the boxes and `PoseOverlay` the skeleton, both
  with an SVG that replicates the video's `object-fit: cover` so they do not come off
  when cropping. `useAiStream` keeps the connection, with spaced reconnection.

## Privacy

**Nothing is saved.** The tensors live in memory, the last one replaces the
previous one, and there is not a single write to disk. No captures, no crops of the
detected objects, no history. The overlay is drawn in the browser.

## Acceptance criteria

| Criterion | Status |
| --- | --- |
| `available: true` with the sensor producing tensors | ✔ |
| Reported inference latency | ✔ ≈26 ms |
| Model labels exposed | ✔ 90 |
| Boxes normalized 0..1 and well ordered | ✔ |
| **Mapping with `convert_inference_coords`** | ✔ applied and verified on the unit |
| **Visual validation of the boxes** | ✔ confirmed by the user live |
| **Mirror** | ✔ discarded: not needed, and applying it was the error |
| Inference and video at the same time | ✔ verified |
| Metrics in `/telemetry` (`ai_inference_ms`, `detections`) | ✔ |
| Box overlay on the video | ✔ implemented |
| Tracking across frames | ✔ implemented |
| Changing the network from the interface (`POST /ai/model`) | ✔ verified live in both directions |
| Configurable score filter | ✔ `AI_SCORE_THRESHOLD` |
| `pytest` green | ✔ 156 tests |

## Pending

The phase is closed. What remains does not block anything:

1. **Parked**: the pose estimation (`higherhrnet_coco`) is measured and its
   decoder exists in picamera2, but it is not integrated for now. See
   [`imx500.md`](imx500.md).
2. **Natural next step**: stable identity across frames is already done
   (`tracking.py`); what would add value now is using those identities for something
   (following a person, warning about an obstacle), and that belongs to Phase 7.
