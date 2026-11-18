"""用人脸网格和引导滤波对 YUV420 画面的脸部皮肤做局部磨皮。"""
from __future__ import annotations

import subprocess
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile

import av
import cv2
import numpy as np

from . import cancellation, config, media

_FACE = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365,
    379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93,
    234, 127, 162, 21, 54, 103, 67, 109,
]
_FEATURES = [
    (0.018, [
        [70, 63, 105, 66, 107, 168, 133, 155, 153, 145, 144, 163, 7, 33],
        [300, 293, 334, 296, 336, 168, 362, 382, 380, 374, 373, 390, 249, 263],
    ]),
    (0.012, [[61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405,
               314, 17, 84, 181, 91, 146]]),
    (0.005, [[98, 97, 2, 326, 327, 294, 4, 64]]),
]


def _ellipse(radius: int) -> np.ndarray:
    size = 2 * radius + 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def _smooth_luma(y: np.ndarray, points: np.ndarray, face_width: float, strength: float) -> None:
    height, width = y.shape
    outline = points[_FACE]

    feather = max(4, round(face_width * 0.018))
    radius = max(4, min(12, round(face_width * 0.026)))
    margin = 3 * feather + 2 * radius
    x0, y0 = np.maximum(np.floor(outline.min(axis=0)).astype(int) - margin, 0)
    x1, y1 = np.minimum(np.ceil(outline.max(axis=0)).astype(int) + margin, [width, height])
    if x1 - x0 < 30 or y1 - y0 < 30:
        return

    landmarks = np.rint(points - [x0, y0]).astype(np.int32)
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(mask, [landmarks[_FACE]], 255)
    for fraction, features in _FEATURES:
        protected = np.zeros_like(mask)
        for feature in features:
            cv2.fillConvexPoly(protected, cv2.convexHull(landmarks[feature]), 255)
        extra = max(2, round(face_width * fraction))
        mask[cv2.dilate(protected, _ellipse(extra)) != 0] = 0
    mask = cv2.erode(mask, _ellipse(max(3, feather // 2)),
                     borderType=cv2.BORDER_CONSTANT, borderValue=0)
    alpha = cv2.GaussianBlur(mask, (0, 0), sigmaX=feather * 0.48).astype(np.float32) / 255

    roi = y[y0:y1, x0:x1]
    luma = roi.astype(np.float32)
    base = cv2.ximgproc.guidedFilter(luma, luma, radius, 100.0)
    # 保留细纹理，默认滑杆 50 对应试片的力度。
    fine_detail = luma - cv2.GaussianBlur(luma, (5, 5), 0.85)
    lift = 1.6 * np.clip((luma - 35) / 50, 0, 1) * np.clip((233 - luma) / 45, 0, 1)
    delta = (2 * strength) * alpha * (lift - 0.65 * (luma - base - 0.28 * fine_detail))
    roi[:] = np.rint(luma + delta).clip(0, 255).astype(np.uint8)


class FaceTracker:
    def __init__(self, width: int, height: int, *, still: bool = False):
        from mediapipe.python.solutions.face_mesh import FaceMesh

        if not hasattr(getattr(cv2, "ximgproc", None), "guidedFilter"):
            raise RuntimeError("局部磨皮需要带 ximgproc 的 OpenCV（opencv-contrib-python）")
        self.width, self.height = width, height
        self.small_width = min(width, 432)
        self.small_height = max(2, round(height / width * self.small_width / 2) * 2)
        self.still = still
        self.make_mesh = FaceMesh
        self.mesh = self._new_mesh()
        self.previous_points = None
        self.previous_probe = None

    def _new_mesh(self):
        return self.make_mesh(static_image_mode=self.still, max_num_faces=1,
                              min_detection_confidence=0.66, min_tracking_confidence=0.65)

    def close(self) -> None:
        self.mesh.close()

    def apply(self, frame: bytearray, strength: float) -> bool:
        w, h = self.width, self.height
        sw, sh = self.small_width, self.small_height
        y_end = w * h
        u_end = y_end + y_end // 4
        samples = np.frombuffer(frame, dtype=np.uint8)
        y = samples[:y_end].reshape(h, w)
        u = samples[y_end:u_end].reshape(h // 2, w // 2)
        v = samples[u_end:].reshape(h // 2, w // 2)
        # 硬切后丢弃上一帧的网格和遮罩位置。
        if not self.still:
            probe = cv2.resize(y, (48, 80), interpolation=cv2.INTER_AREA)
            if self.previous_probe is not None and cv2.absdiff(probe, self.previous_probe).mean() > 20:
                self.close()
                self.mesh = self._new_mesh()
                self.previous_points = None
            self.previous_probe = probe
        planes = [
            cv2.resize(y, (sw, sh), interpolation=cv2.INTER_AREA),
            cv2.resize(u, (sw // 2, sh // 2), interpolation=cv2.INTER_AREA),
            cv2.resize(v, (sw // 2, sh // 2), interpolation=cv2.INTER_AREA),
        ]
        small = np.concatenate([plane.ravel() for plane in planes]).reshape(sh * 3 // 2, sw)
        image = cv2.cvtColor(small, cv2.COLOR_YUV2RGB_I420)
        faces = self.mesh.process(image).multi_face_landmarks
        if not faces:
            self.previous_points = None
            return False
        points = np.array([(p.x * w, p.y * h) for p in faces[0].landmark], dtype=np.float32)
        if self.previous_points is not None:
            points = 0.80 * points + 0.20 * self.previous_points
        self.previous_points = points
        face_width = np.ptp(points[_FACE, 0])
        if not 100 * w / 1440 <= face_width <= w * 0.8:
            return False
        if strength:
            _smooth_luma(y, points, face_width, strength)
        return True

    def has_face(self, decode: list[str]) -> bool:
        return self.apply(_read_frame(decode, self.width, self.height), 0.0)


def _ffmpeg(args: list[str]) -> list[str]:
    return [config.ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args]


def _raw_output() -> list[str]:
    return ["-an", "-pix_fmt", "yuv420p", "-threads:v", "1", "-f", "rawvideo", "pipe:1"]


def _raw_input(width: int, height: int, fps: int) -> list[str]:
    return ["-f", "rawvideo", "-pixel_format", "yuv420p", "-video_size", f"{width}x{height}",
            "-framerate", str(fps), "-i", "pipe:0"]


def _read_frame(decode: list[str], width: int, height: int) -> bytearray:
    raw = cancellation.run_process(_ffmpeg([*decode, "-frames:v", "1", *_raw_output()]), capture_output=True)
    if raw.returncode or len(raw.stdout) != width * height * 3 // 2:
        raise RuntimeError("无法读取磨皮预览帧：" + raw.stderr.decode("utf-8", "replace")[-1000:])
    return bytearray(raw.stdout)


def still(decode: list[str], encode: list[str], width: int, height: int, strength: float) -> bytes:
    """取一帧磨皮后交给 FFmpeg，供预览和封面共用。"""
    frame = _read_frame(decode, width, height)
    if strength:
        tracker = FaceTracker(width, height, still=True)
        try:
            tracker.apply(frame, strength)
        finally:
            tracker.close()
    result = cancellation.run_process(
        _ffmpeg([*_raw_input(width, height, 25), "-frames:v", "1", *encode]),
        input=frame, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError("磨皮预览编码失败：" + result.stderr.decode("utf-8", "replace")[-1000:])
    return result.stdout


def video(inputs: list[str], encoder: list[str], out: Path,
          width: int, height: int, fps: int, strength: float) -> None:
    """沿用裁切好的无损画面和音轨，磨皮后只编码视频。"""
    if config.load()["render"]["encoder"] == "h264_nvenc":
        lossless = ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "lossless"]
    else:
        lossless = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "0"]
    tracker = FaceTracker(width, height)
    frame = bytearray(width * height * 3 // 2)
    try:
        with TemporaryDirectory(prefix="skin-", dir=out.parent) as work:
            source = str(Path(work) / "segment.mp4")
            media.run_ffmpeg([*inputs, *lossless, source])
            with av.open(source) as container, TemporaryFile() as log:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                stream.thread_count = 6
                codec = stream.codec_context
                # 原始画面的 FFmpeg 输入没有标签，补回无损视频的色彩参数。
                color = ["-colorspace", str(codec.colorspace), "-color_range", str(codec.color_range),
                         "-color_primaries", str(codec.color_primaries), "-color_trc", str(codec.color_trc)]
                cmd = _ffmpeg([*_raw_input(width, height, fps), "-i", source, "-map", "0:v:0", "-map", "1:a:0",
                               "-c:a", "copy", *encoder, *color, str(out)])
                with subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log) as writer:
                    packed = np.frombuffer(frame, dtype=np.uint8)
                    try:
                        for picture in container.decode(stream):
                            cancellation.check()
                            offset = 0
                            for plane in picture.planes:
                                rows = np.frombuffer(plane, dtype=np.uint8).reshape(plane.height, plane.line_size)
                                end = offset + plane.width * plane.height
                                packed[offset:end].reshape(plane.height, plane.width)[:] = rows[:, :plane.width]
                                offset = end
                            tracker.apply(frame, strength)
                            cancellation.check()
                            writer.stdin.write(frame)
                        writer.stdin.close()
                        while writer.poll() is None:
                            cancellation.check()
                            try:
                                writer.wait(timeout=0.2)
                            except subprocess.TimeoutExpired:
                                continue
                        failed = writer.returncode != 0
                    except BrokenPipeError:
                        failed = True
                    finally:
                        if writer.poll() is None:
                            writer.kill()
                            writer.wait()
                        with suppress(BrokenPipeError):
                            writer.stdin.close()
                    if failed:
                        log.seek(0)
                        raise RuntimeError("视频磨皮编码失败：" + log.read().decode("utf-8", "replace")[-2000:])
    finally:
        tracker.close()
