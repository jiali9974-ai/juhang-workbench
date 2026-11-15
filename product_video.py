"""产品图 → MiniMax H3 静音镜头 → 本地剪辑和粤语字幕。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageFilter, ImageOps

from jh import config, h3_comfy, media, render


@dataclass(frozen=True)
class Shot:
    id: str
    image: Path
    seconds: float
    subtitle: str
    motion: str
    start: float = 0
    lock_view: bool = False
    seed: int | None = None
    prompt_override: str | None = None

    @property
    def prompt(self) -> str:
        if self.prompt_override is not None:
            return self.prompt_override
        if self.lock_view:
            return (
                "One continuous vertical product detail shot with identical beginning and end framing. "
                + self.motion + " Preserve the exact visible surfaces, shapes, engravings, and position. "
                "Use clean footage with no addition of captions, people speaking, or graphic elements."
            )
        return (
            "A single vertical handheld-style close-up of the exact watch in the supplied photograph. "
            + self.motion + " Preserve the exact dial markings, visible brand mark, hands, date, bezel scale, "
            "bracelet and glove in the image. Restrained realistic motion. "
            "No people speaking, graphic overlays, subtitles, captions, or added text."
        )

    @property
    def source_key(self) -> str:
        digest = hashlib.sha256(self.image.read_bytes())
        digest.update(self.prompt.encode("utf-8"))
        if self.seed is not None:
            digest.update(f"|seed:{self.seed}".encode("ascii"))
        return digest.hexdigest()


def load_plan(path: Path, product_root: Path) -> tuple[str, list[Shot]]:
    plan = json.loads(path.read_text(encoding="utf-8-sig"))
    product_root = product_root.resolve()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", plan["id"]):
        raise ValueError("方案 id 请用小写字母、数字和连字符")
    seen = set()
    shots = []
    for item in plan["shots"]:
        shot_id = item["id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", shot_id) or shot_id in seen:
            raise ValueError(f"无效或重复的镜头 id：{shot_id}")
        seen.add(shot_id)
        image = (product_root / item["image"]).resolve()
        if not image.is_relative_to(product_root) or not image.is_file():
            raise ValueError(f"产品图目录下找不到 {item['image']}")
        seconds, start = float(item["seconds"]), float(item.get("start", 0))
        subtitle, motion = item["subtitle"].strip(), item.get("motion", "").strip()
        prompt_override = item.get("prompt")
        if prompt_override is not None:
            prompt_override = prompt_override.strip()
        if not (0.5 <= seconds <= 12 and start >= 0 and start + seconds <= 15):
            raise ValueError(f"{shot_id} 的剪辑区间超出 0–15 秒或镜头时长无效")
        if not (prompt_override or motion) or re.search(r"[{}\\\r\n]", subtitle):
            raise ValueError(f"{shot_id} 需要运动描述，字幕请使用单行纯文本")
        lock_view = item.get("lock_view", False)
        if not isinstance(lock_view, bool):
            raise ValueError(f"{shot_id} 的 lock_view 必须是布尔值")
        seed = item.get("seed")
        if seed is not None and (type(seed) is not int or not 0 <= seed < 2**64):
            raise ValueError(f"{shot_id} 的 seed 必须是 0 到 2^64-1 的整数")
        shots.append(Shot(shot_id, image, seconds, subtitle, motion, start, lock_view, seed, prompt_override or None))
    if not shots:
        raise ValueError("方案至少需要一个镜头")
    return plan["id"], shots


def prepare_frame(source: Path, target: Path) -> None:
    width, height = h3_comfy.SIZE
    with Image.open(source) as raw:
        photo = ImageOps.exif_transpose(raw).convert("RGB")
    fit = ImageOps.contain(photo, (width, height), Image.Resampling.LANCZOS)
    canvas = ImageOps.fit(photo, (width, height), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(27))
    canvas.paste(fit, ((width - fit.width) // 2, (height - fit.height) // 2))
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target)


def generate(shots: list[Shot], root: Path, api: h3_comfy.ComfyH3, turbo: bool, timeout: float) -> None:
    clip_dir = root / "shots"
    clip_dir.mkdir(parents=True, exist_ok=True)
    folder = f"jh-product-video/{root.name}"
    vae = None
    for index, shot in enumerate(shots, 1):
        print(f"[{index}/{len(shots)}] {shot.id}", flush=True)
        clip = clip_dir / f"{shot.id}.mp4"
        state_path = clip.with_suffix(".task.json")
        source_key = shot.source_key
        if state_path.exists():
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            if saved.get("source_key") != source_key:
                raise RuntimeError(f"{shot.id} 的原图或运动描述已修改，请使用新的方案 id 或镜头 id")
            if clip.exists():
                print(f"复用 {clip}", flush=True)
                continue
            if not saved.get("task_id"):
                raise RuntimeError(f"{shot.id} 上次提交未确认，请先检查 ComfyUI 队列和历史：{state_path}")
            if saved["url"] != api.url:
                raise ValueError(f"{shot.id} 的任务位于上次使用的 ComfyUI 地址 {saved['url']}")
            task_id = saved["task_id"]
        else:
            if vae is None:
                vae = api.preflight(turbo)
            frames = root / "frames"
            frames.mkdir(exist_ok=True)
            with TemporaryDirectory(dir=frames) as temp:
                frame = Path(temp) / f"{shot.id}.png"
                prepare_frame(shot.image, frame)
                uploaded = api.upload(frame, folder)
            seed = shot.seed if shot.seed is not None else int(source_key[:12], 16)
            graph = h3_comfy.workflow(uploaded, shot.prompt, f"{folder}/{shot.id}",
                                     shot.start + shot.seconds, seed, vae, turbo, shot.lock_view)
            workflows = root / "workflows"
            workflows.mkdir(exist_ok=True)
            with state_path.open("x", encoding="utf-8") as handle:
                saved = {"url": api.url, "source_key": source_key}
                json.dump(saved, handle)
            try:
                (workflows / f"{shot.id}.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except OSError:
                state_path.unlink()
                raise
            try:
                task_id = api.submit(graph)
            except h3_comfy.ComfyRequestError as error:
                if error.status in {400, 401, 403, 404, 422}:
                    state_path.unlink()
                raise
            saved["task_id"] = task_id
            staging = state_path.with_suffix(".tmp")
            staging.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
            staging.replace(state_path)
        result = api.wait(task_id, timeout)
        with TemporaryDirectory(dir=clip_dir) as temp:
            raw = Path(temp) / "h3.mp4"
            api.download(result, raw)
            media.probe(raw)
            raw.replace(clip)
        print(f"H3 镜头已保存 {clip}", flush=True)


def compose(shots: list[Shot], root: Path, preview: bool) -> Path:
    cfg = config.load()
    width = int(cfg["render"]["width"])
    height = int(cfg["render"]["height"])
    fps = int(cfg["render"]["fps"])
    clips = [root / "shots" / f"{shot.id}.mp4" for shot in shots]
    if not preview:
        missing = [shot.id for shot, clip in zip(shots, clips) if not clip.is_file()]
        if missing:
            raise ValueError("还缺少 H3 镜头：" + "、".join(missing))
        for shot, clip in zip(shots, clips):
            state = json.loads(clip.with_suffix(".task.json").read_text(encoding="utf-8"))
            if state.get("source_key") != shot.source_key:
                raise ValueError(f"{shot.id} 的镜头与当前原图或提示词不匹配")

    root.mkdir(parents=True, exist_ok=True)
    result = root / ("photo-timing-preview.mp4" if preview else "minimax-final.mp4")
    with TemporaryDirectory(dir=root) as temp:
        work = Path(temp)
        segments = []
        for index, (shot, clip) in enumerate(zip(shots, clips)):
            frames = round(shot.seconds * fps)
            duration = frames / fps
            out = work / f"seg-{index:02d}.mp4"
            print(f"剪辑 {index + 1}/{len(shots)} {shot.id}", flush=True)
            if preview:
                frame = work / f"frame-{index:02d}.png"
                prepare_frame(shot.image, frame)
                source = ["-loop", "1", "-framerate", str(fps), "-i", str(frame)]
                vf = (f"scale={width * 2}:{height * 2}:flags=lanczos,"
                      f"zoompan=z='1+0.025*on/{max(1, frames-1)}':x='iw/2-iw/zoom/2':"
                      f"y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps={fps}")
            else:
                length = media.probe(clip).duration
                if length + 1 / fps < shot.start + duration:
                    raise ValueError(f"{shot.id} 的 H3 原片只有 {length:.2f} 秒，所选剪辑区间超出了原片")
                source = ["-ss", f"{shot.start:.3f}", "-i", str(clip)]
                vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                      f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}")
            media.run_ffmpeg([*source, "-an", "-vf", f"{vf},setsar=1,format=yuv420p",
                              "-frames:v", str(frames), *render._venc(), str(out)])
            subs = render.timed_chunks(shot.subtitle, 0.12, duration - 0.08,
                                       cfg["style"]["subtitle"]["max_chars_per_line"]) if shot.subtitle else []
            segments.append(render.Segment(clip=out, v_start=0, v_dur=duration, subs=subs))

        concat = work / "concat.txt"
        concat.write_text("".join(f"file '{segment.clip.name}'\n" for segment in segments), encoding="utf-8")
        media.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(work / "body.mp4")])
        render.build_ass(segments, sum(segment.v_dur for segment in segments), work / "video.ass")
        shutil.copytree(cfg["style"]["font_dir"], work / "fonts")
        cmd = [config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", "body.mp4",
               "-vf", "subtitles=video.ass:fontsdir=fonts", "-an", *render._venc(),
               "-movflags", "+faststart", "result.mp4"]
        completed = subprocess.run(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.returncode:
            raise RuntimeError("字幕合成失败：" + completed.stderr[-1800:])
        (work / "result.mp4").replace(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "generate", "render"))
    parser.add_argument("plan", type=Path)
    parser.add_argument("--products", type=Path, default=config.ROOT.parent / "产品图")
    parser.add_argument("--shot", action="append", help="指定生成镜头 id，可重复使用")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:18188")
    parser.add_argument("--turbo", action="store_true", help="云端使用官方 8 步 H3 LoRA")
    parser.add_argument("--timeout", type=float, default=1200, help="每个镜头等待秒数，超时后可续查")
    args = parser.parse_args()
    try:
        plan_id, shots = load_plan(args.plan, args.products)
        root = config.data_root() / "product_video" / plan_id
        if args.command == "generate":
            if args.shot:
                wanted = set(args.shot)
                unknown = wanted - {shot.id for shot in shots}
                if unknown:
                    raise ValueError("未找到镜头：" + "、".join(sorted(unknown)))
                shots = [shot for shot in shots if shot.id in wanted]
            if not math.isfinite(args.timeout) or args.timeout <= 0:
                raise ValueError("等待秒数必须是正数")
            generate(shots, root, h3_comfy.ComfyH3(args.comfy_url), args.turbo, args.timeout)
        else:
            if args.shot:
                raise ValueError("--shot 用于 generate")
            print(compose(shots, root, preview=args.command == "preview"), flush=True)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        print(f"产品图出片失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
