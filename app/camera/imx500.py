"""Raspberry Pi AI Camera (IMX500) driver.

Only runs on the Raspberry Pi: `picamera2` and `libcamera` are required.

**Imports are resolved inside the methods on purpose**, so this module can be
imported (and its failure path tested) on any platform. On a development machine
`start()` raises a clear :class:`CameraStreamError` instead of an ImportError at
import time.

The camera is owned by Picamera2, and that is deliberate: `picamera2.devices.IMX500`
executes the network **inside the sensor** and exposes both the video stream and
the inference outputs. If MediaMTX took the camera instead (`source: rpiCamera`),
the inference would be lost.

Nothing is written to disk: the H.264 stream produced by the hardware encoder is
handed straight to FFmpeg, which publishes it to MediaMTX over RTSP.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Sequence
from typing import Any

from app.ai.detection import (
    DEFAULT_BBOX_ORDER,
    DEFAULT_SCORE_THRESHOLD,
    InferenceFrame,
    clamp01,
    normalize_sensor_boxes,
)
from app.ai.pose import (
    DEFAULT_PERSON_THRESHOLD,
    PoseFrame,
    PoseObservation,
)
from app.camera.health import rtsp_describe_ok, wait_until_published
from app.camera.interface import Camera, CameraStatus
from app.core.exceptions import CameraError, CameraStreamError

logger = logging.getLogger(__name__)

#: How long to wait for a fresh metadata frame before giving up on this loop.
_METADATA_TIMEOUT_MS = 1000

#: The ``task`` a pose network declares, and the joints it emits.
_POSE_TASK = "pose estimation"
_KEYPOINT_COUNT = 17


class Imx500Camera(Camera):
    """Live video from the IMX500 through MediaMTX."""

    def __init__(
        self,
        *,
        network_file: str,
        rtsp_url: str,
        stream_path: str,
        webrtc_port: int,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        bitrate_kbps: int = 2500,
        buffer_count: int = 3,
        hflip: bool = False,
        vflip: bool = False,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        pose_threshold: float = DEFAULT_PERSON_THRESHOLD,
        on_result: Callable[[], None] | None = None,
    ) -> None:
        self._network_file = network_file
        self._rtsp_url = rtsp_url
        self._stream_path = stream_path
        self._webrtc_port = webrtc_port
        self._width = width
        self._height = height
        self._fps = fps
        self._bitrate_kbps = bitrate_kbps
        self._buffer_count = buffer_count
        self._hflip = hflip
        self._vflip = vflip
        self._score_threshold = score_threshold
        self._pose_threshold = pose_threshold
        self._on_result = on_result

        self._picam2: Any = None
        self._imx500: Any = None
        self._imx500_class: Any = None
        self._started = False
        self._last_error: str | None = None
        self._lock = asyncio.Lock()

        # Latest inference result, published by the background metadata loop.
        self._labels: tuple[str, ...] = ()
        self._input_size: tuple[int, int] | None = None
        # What the loaded network does. It decides which result is published.
        self._task = ""
        # How the network describes its own boxes, read from its intrinsics.
        self._bbox_normalization = False
        self._bbox_order = DEFAULT_BBOX_ORDER
        self._preserve_aspect_ratio = False
        self._last_inference: InferenceFrame | None = None
        self._last_pose: PoseFrame | None = None
        # Set while a model switch is restarting the camera, so the stream
        # watchdog never fights a deliberate reload.
        self._reloading = False
        self._inference_thread: threading.Thread | None = None
        self._closing = threading.Event()

    # --- Inference source ----------------------------------------------------

    @property
    def network_file(self) -> str:
        """The network currently loaded in the sensor, as a full path."""
        return self._network_file

    @property
    def is_reloading(self) -> bool:
        """Whether a camera restart (model switch) is in progress.

        The stream watchdog must not restart the camera again while the publish
        is briefly down for a deliberate switch.
        """
        return self._reloading

    @property
    def detection_labels(self) -> Sequence[str]:
        """Class labels baked into the network loaded in the sensor."""
        return self._labels

    def latest_inference(self) -> InferenceFrame | None:
        """Most recent detection result, or ``None`` if there is none yet.

        Also ``None`` when the loaded network does something else: a pose network
        has no boxes to report.
        """
        return self._last_inference

    def latest_pose(self) -> PoseFrame | None:
        """Most recent pose result, or ``None`` when the network is not a pose one."""
        return self._last_pose

    @property
    def is_running(self) -> bool:
        return self._started and self._picam2 is not None

    async def start(self) -> None:
        async with self._lock:
            if self._picam2 is not None:
                return
            await asyncio.to_thread(self._start_blocking)

    async def stop(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._stop_blocking)

    async def status(self) -> CameraStatus:
        return CameraStatus(
            mode="imx500",
            running=self.is_running,
            width=self._width,
            height=self._height,
            fps=self._fps,
            stream_path=self._stream_path,
            webrtc_port=self._webrtc_port,
            model=self._network_file.rsplit("/", 1)[-1],
            last_error=self._last_error,
        )

    async def reload(self, network_file: str, *, wait_for_publish: bool = False) -> None:
        """Swap the network running in the sensor.

        The sensor holds one network at a time, so the camera has to be stopped,
        pointed at the new model and started again. The stream drops while the
        sensor starts up with the new firmware — tens of seconds the first time it
        is uploaded, less afterwards (the RP2040 caches it).

        With ``wait_for_publish`` the call only returns once the stream is being
        published again (or after a bounded wait): the sensor takes a few seconds
        to produce frames after the camera is up, and an operator-facing switch
        should not answer before the picture can really come back.

        If the new network fails to start, the previous one is restored rather
        than leaving the camera broken. The change is not written to the
        configuration file: it applies for this run only.
        """
        if not self._started:
            raise CameraStreamError("Cannot switch models while the camera is stopped")

        self._reloading = True
        previous = self._network_file
        try:
            await self.stop()
            self._network_file = network_file
            await self.start()
            if wait_for_publish:
                await wait_until_published(lambda: rtsp_describe_ok(self._rtsp_url))
        except CameraError:
            logger.exception("New network failed to start; restoring %s", previous)
            self._network_file = previous
            await self.start()
            raise
        finally:
            self._reloading = False

    # --- Blocking implementation ---------------------------------------------

    def _imports(self) -> tuple[Any, Any, Any, Any, Any]:
        """Import the Pi-only libraries, with an actionable error message."""
        try:
            from libcamera import Transform
            from picamera2 import Picamera2
            from picamera2.devices import IMX500
            from picamera2.encoders import H264Encoder
            from picamera2.outputs import FfmpegOutput
        except ImportError as exc:  # pragma: no cover - depends on the platform
            raise CameraStreamError(
                "The IMX500 camera needs picamera2 and libcamera, which only exist on "
                f"Raspberry Pi OS. Import failed: {exc}"
            ) from exc
        return Picamera2, IMX500, H264Encoder, FfmpegOutput, Transform

    def ffmpeg_target(self) -> str:
        """The FFmpeg destination passed to :class:`FfmpegOutput`.

        ``FfmpegOutput`` accepts a free-form string of FFmpeg options followed by
        a destination (see its docstring), which is how the hardware encoded
        stream reaches MediaMTX without touching disk.
        """
        return f"-rtsp_transport tcp -f rtsp {self._rtsp_url}"

    def transform_args(self) -> dict[str, int]:
        """Mirror flags for libcamera, when the camera is mounted upside down.

        This transform belongs to the **video**: the ISP applies it on the way to
        the stream.

        Detections are deliberately **not** mirrored to match. Verified on the
        unit: with the official conversion in place, the boxes land on the objects
        as they appear in the stream, with no flip applied here. The flip that used
        to be applied was what pushed them off target.
        """
        return {"hflip": int(self._hflip), "vflip": int(self._vflip)}

    def _start_blocking(self) -> None:
        logger.info("Starting IMX500 camera with network %s", self._network_file)
        try:
            Picamera2, IMX500, H264Encoder, FfmpegOutput, Transform = self._imports()

            imx500 = IMX500(self._network_file)
            self._read_intrinsics(imx500)
            picam2 = Picamera2(imx500.camera_num)

            config = picam2.create_preview_configuration(
                main={"size": (self._width, self._height), "format": "RGB888"},
                buffer_count=self._buffer_count,
                transform=Transform(**self.transform_args()),
                controls={"FrameRate": self._fps},
            )
            picam2.configure(config)

            encoder = H264Encoder(
                bitrate=self._bitrate_kbps * 1000,
                # Keyframe every ~0.5 s. On a lossy Wi-Fi link (measured ~10 %
                # loss) a decoder that misses a packet must wait for the next
                # IDR; halving the GOP halves that stale period, which is felt
                # as "delay". Bitrate headroom is measured (1.95 of 3 Mbit/s),
                # see docs/specs/live-video.md.
                iperiod=max(1, self._fps // 2),
                repeat=True,
            )
            output = FfmpegOutput(self.ffmpeg_target())
            picam2.start_recording(encoder, output)

            if self._preserve_aspect_ratio:
                # Let the sensor crop its own field of view the way its network
                # asks for, instead of trying to undo the difference afterwards.
                try:
                    imx500.set_auto_aspect_ratio()
                    logger.info("Inference ROI matched to the input tensor aspect ratio")
                except Exception:
                    logger.warning(
                        "Could not set the inference aspect ratio; boxes may be offset",
                        exc_info=True,
                    )
        except CameraStreamError as exc:
            # Keep the reason for `status()`: it is what the operator sees.
            self._last_error = str(exc)
            raise
        except Exception as exc:
            self._last_error = str(exc)
            raise CameraStreamError(f"Could not start the IMX500 camera: {exc}") from exc

        self._imx500 = imx500
        self._imx500_class = IMX500
        self._picam2 = picam2
        self._started = True
        self._last_error = None

        self._start_inference_loop()

        logger.info(
            "IMX500 camera streaming %dx%d @ %dfps to %s (hflip=%s, vflip=%s)",
            self._width,
            self._height,
            self._fps,
            self._rtsp_url,
            self._hflip,
            self._vflip,
        )

    def _read_intrinsics(self, imx500: Any) -> None:
        """Read what the network declares about itself.

        The boxes cannot be interpreted without this: whether they need
        normalising and in which order they arrive are declared per network, and
        assuming either is exactly how boxes end up in the wrong place.
        """
        try:
            intrinsics = imx500.network_intrinsics
            labels = getattr(intrinsics, "labels", None)
            self._labels = tuple(labels) if labels else ()
            self._task = str(getattr(intrinsics, "task", None) or "")

            size = imx500.get_input_size()
            self._input_size = (int(size[0]), int(size[1]))

            self._bbox_normalization = bool(getattr(intrinsics, "bbox_normalization", None))
            self._bbox_order = getattr(intrinsics, "bbox_order", None) or DEFAULT_BBOX_ORDER
            self._preserve_aspect_ratio = bool(getattr(intrinsics, "preserve_aspect_ratio", None))

            logger.info(
                "IMX500 network: task=%s, %d labels, input=%dx%d, "
                "bbox_normalization=%s, bbox_order=%s, preserve_aspect_ratio=%s",
                getattr(intrinsics, "task", None),
                len(self._labels),
                self._input_size[0],
                self._input_size[1],
                self._bbox_normalization,
                self._bbox_order,
                self._preserve_aspect_ratio,
            )
        except Exception:
            logger.exception("Could not read the network intrinsics")

    def _start_inference_loop(self) -> None:
        """Publish inference results in the background.

        Reading metadata does not disturb the recording: verified on the real
        unit, `capture_metadata()` and `start_recording()` coexist.

        The loop lives in a thread because `capture_metadata()` blocks, and
        blocking the event loop would freeze the whole API.
        """
        self._closing.clear()
        self._inference_thread = threading.Thread(
            target=self._inference_loop, name="imx500-inference", daemon=True
        )
        self._inference_thread.start()

    def _inference_loop(self) -> None:
        while not self._closing.is_set():
            picam2 = self._picam2
            imx500 = self._imx500
            if picam2 is None or imx500 is None:
                return

            try:
                metadata = picam2.capture_metadata()
            except Exception:
                # The camera was stopped underneath us: nothing to publish.
                if not self._closing.is_set():
                    logger.debug("Metadata capture failed", exc_info=True)
                continue

            try:
                outputs = imx500.get_outputs(metadata, add_batch=True)
            except Exception:
                logger.debug("Could not decode inference outputs", exc_info=True)
                continue

            if outputs is None:
                # The inference runs slower than the frame rate, so some frames
                # carry no fresh result. That is normal, not an error.
                continue

            kpi = self._imx500_class.get_kpi_info(metadata) if self._imx500_class else None
            dnn_ms = kpi[0] if kpi else None
            dsp_ms = kpi[1] if kpi else None

            if self._task == _POSE_TASK:
                try:
                    self._last_pose = self._convert_pose(
                        outputs, metadata, picam2, imx500, dnn_ms, dsp_ms
                    )
                except Exception:
                    logger.debug("Could not map the pose keypoints", exc_info=True)
                    continue
                self._notify()
                continue

            try:
                boxes, scores, classes = self._convert_boxes(
                    outputs[0][0], outputs[1][0], outputs[2][0], metadata, picam2, imx500
                )
            except Exception:
                logger.debug("Could not map the detection boxes", exc_info=True)
                continue

            self._last_inference = InferenceFrame(
                boxes=boxes,
                scores=scores,
                classes=classes,
                dnn_ms=dnn_ms,
                dsp_ms=dsp_ms,
            )
            self._notify()

    def _notify(self) -> None:
        """Tell whoever is listening that a fresh result is available.

        The listener is called from the inference thread, so it must not block and
        a failure in it must never take the inference loop down with it.
        """
        callback = self._on_result
        if callback is None:
            return
        try:
            callback()
        except Exception:
            logger.debug("A result listener failed", exc_info=True)

    def _point_on_frame(
        self,
        x: float,
        y: float,
        input_size: tuple[int, int],
        metadata: dict,
        picam2: Any,
        imx500: Any,
    ) -> tuple[float, float]:
        """Map one normalised point of the input tensor onto the video frame.

        Uses the same official conversion as the boxes. It converts *boxes*, so it
        is asked about a one-pixel box and the centre is taken.
        """
        input_width, input_height = input_size
        px, py, width, height = imx500.convert_inference_coords(
            (y, x, y + 1.0 / input_height, x + 1.0 / input_width), metadata, picam2
        )
        return (
            clamp01((px + width / 2) / self._width),
            clamp01((py + height / 2) / self._height),
        )

    def _convert_pose(
        self,
        outputs: Sequence[Any],
        metadata: dict,
        picam2: Any,
        imx500: Any,
        dnn_ms: float | None,
        dsp_ms: float | None,
    ) -> PoseFrame:
        """Decode the pose network and map the joints onto the video frame.

        The decoding is picamera2's. ``higherhrnet_coco`` is post-processed on the
        sensor, and `postprocess_higherhrnet` turns its three tensors into people
        with their joints. It is imported here rather than at module level because
        it pulls in numpy and OpenCV, which do not exist off the Pi.
        """
        from picamera2.devices.imx500.postprocess_highernet import postprocess_higherhrnet

        input_width, input_height = self._input_size or (1, 1)

        keypoints, scores, _boxes = postprocess_higherhrnet(
            outputs=outputs,
            # The joints come back scaled to this size, so asking for the input
            # size means they arrive in the input tensor's pixels.
            img_size=(input_height, input_width),
            img_w_pad=(0, 0),
            img_h_pad=(0, 0),
            detection_threshold=self._pose_threshold,
            network_postprocess=True,
        )

        people: list[PoseObservation] = []
        for index, score in enumerate(scores):
            flat = keypoints[index]
            joints: list[tuple[float, float, float]] = []
            for joint in range(_KEYPOINT_COUNT):
                confidence = float(flat[3 * joint + 2])
                x, y = self._point_on_frame(
                    float(flat[3 * joint]) / input_width,
                    float(flat[3 * joint + 1]) / input_height,
                    (input_width, input_height),
                    metadata,
                    picam2,
                    imx500,
                )
                joints.append((x, y, confidence))
            people.append(PoseObservation(score=float(score), keypoints=joints))

        return PoseFrame(people=people, dnn_ms=dnn_ms, dsp_ms=dsp_ms)

    def _convert_boxes(
        self,
        raw_boxes: Any,
        raw_scores: Any,
        raw_classes: Any,
        metadata: dict,
        picam2: Any,
        imx500: Any,
    ) -> tuple[list[list[float]], list[float], list[float]]:
        """Map the network's boxes onto the video frame.

        Two steps, and neither should be written by hand:

        1. :func:`normalize_sensor_boxes` interprets what the network declares
           about its own boxes: whether they need normalising, and in which order
           they arrive.
        2. ``IMX500.convert_inference_coords`` is picamera2's official conversion
           from the input tensor's coordinate space to the ISP output. It exists
           because the sensor crops the image to its region of interest *and* the
           ISP crops it again into the stream, and both have to be undone; it
           needs the frame metadata, which is only available here.

        Boxes below the score threshold are dropped before converting: the network
        offers a hundred slots per frame and converting the empty ones is wasted
        work.
        """
        prepared = normalize_sensor_boxes(
            raw_boxes,
            needs_normalization=self._bbox_normalization,
            order=self._bbox_order,
            input_size=self._input_size,
        )

        boxes: list[list[float]] = []
        scores: list[float] = []
        classes: list[float] = []

        for box, score, class_id in zip(prepared, raw_scores, raw_classes, strict=False):
            confidence = float(score)
            if confidence < self._score_threshold:
                continue

            x_min, y_min, x_max, y_max = box
            # The helper takes (y0, x0, y1, x1) and answers (x, y, width, height)
            # in pixels of the ISP output.
            x, y, width, height = imx500.convert_inference_coords(
                (y_min, x_min, y_max, x_max), metadata, picam2
            )

            boxes.append(
                [
                    clamp01(x / self._width),
                    clamp01(y / self._height),
                    clamp01((x + width) / self._width),
                    clamp01((y + height) / self._height),
                ]
            )
            scores.append(confidence)
            classes.append(float(class_id))

        return boxes, scores, classes

    def _stop_inference_loop(self) -> None:
        self._closing.set()
        thread, self._inference_thread = self._inference_thread, None
        if thread is not None:
            thread.join(timeout=3)
        # Both results: a stale pose must not linger after switching to detection.
        self._last_inference = None
        self._last_pose = None

    def _stop_blocking(self) -> None:
        self._stop_inference_loop()

        picam2, self._picam2 = self._picam2, None
        self._started = False
        if picam2 is None:
            return

        try:
            picam2.stop_recording()
        except Exception:
            logger.exception("Error stopping the IMX500 recording")
        try:
            picam2.close()
        except Exception:
            logger.exception("Error closing the IMX500 camera")

        self._imx500 = None
        logger.info("IMX500 camera stopped")
