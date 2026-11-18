"""素材探测与 ffmpeg 小工具。"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import av

from . import cancellation, config

VIDEO_EXTS = {".mov", ".mp4", ".m4v"}


@dataclass
class ClipInfo:
    path: Path
    duration: float
    width: int        # 旋转后的显示宽度
    height: int       # 旋转后的显示高度
    fps: float
    rotation: int

    @property
    def name(self) -> str:
        return self.path.name


def probe(path: Path) -> ClipInfo:
    with av.open(str(path)) as c:
        v = c.streams.video[0]
        w, h = v.codec_context.width, v.codec_context.height
        dur = float(c.duration / 1_000_000) if c.duration else float(v.duration * v.time_base)
        fps = float(v.average_rate) if v.average_rate else 0.0
    rot = _rotation_via_ffmpeg(path)  # iPhone 竖拍是带旋转标记的横向画面
    if abs(rot) in (90, 270):
        w, h = h, w
    return ClipInfo(path=path, duration=dur, width=w, height=h, fps=fps, rotation=rot)


def _rotation_via_ffmpeg(path: Path) -> int:
    out = cancellation.run_process([config.ffmpeg(), "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True, encoding="utf-8", errors="ignore").stderr
    for line in out.splitlines():
        if "rotation of" in line:
            try:
                return int(round(float(line.split("rotation of")[1].split("degrees")[0])))
            except ValueError:
                pass
    return 0


def list_clips(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTS)


def run_ffmpeg(args: list[str]) -> None:
    # 完整写入后才替换目标，取消或失败不会留下可被缓存误用的半个文件。
    target = Path(args[-1])
    with tempfile.TemporaryDirectory(prefix=".ffmpeg-", dir=target.parent) as temporary:
        output = Path(temporary) / target.name
        cmd = [config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args[:-1], str(output)]
        r = cancellation.run_process(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 失败: {' '.join(cmd)}\n{r.stderr[-2000:]}")
        cancellation.check()
        output.replace(target)


def extract_audio_16k(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        run_ffmpeg(["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)])
    return dst
