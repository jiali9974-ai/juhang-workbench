"""Detect this instance's devices on every boot, including GPU-free clones."""
import json
from pathlib import Path
import subprocess
import sys

import yaml


def select(cfg: dict) -> dict:
    import torch

    gpu = torch.cuda.is_available()
    cfg["asr"]["device"] = "cuda:0" if gpu else "cpu"
    cfg.setdefault("gpu", {})["mode"] = "local" if gpu else "cpu"
    encoder = "libx264"
    if gpu:
        # An advertised encoder is insufficient: test an actual encoding session.
        try:
            probe = subprocess.run([
                cfg["paths"]["ffmpeg"], "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=size=640x360:rate=1", "-frames:v", "1",
                "-c:v", "h264_nvenc", "-f", "null", "-",
            ], capture_output=True, timeout=20)
            if probe.returncode == 0:
                encoder = "h264_nvenc"
        except (OSError, subprocess.TimeoutExpired):
            pass
    cfg["render"]["encoder"] = encoder
    print(json.dumps({"asr_device": cfg["asr"]["device"], "encoder": encoder}))
    return cfg


if __name__ == "__main__":
    path = Path(sys.argv[1])
    cfg = select(yaml.safe_load(path.read_text(encoding="utf-8")))
    temporary = path.with_suffix(".device.next.yaml")
    temporary.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(path)
