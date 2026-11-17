"""Generate AutoDL paths without changing the tracked desktop configuration."""
import sys
import subprocess
from pathlib import Path

import yaml


def make(source: Path, base: Path, output: Path) -> None:
    cfg = yaml.safe_load((source / "config.yaml").read_text(encoding="utf-8"))

    def fix(value):
        if isinstance(value, dict):
            return {k: fix(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fix(v) for v in value]
        if isinstance(value, str):
            normalized = value.replace("\\", "/")
            for old, new in [
                ("D:/巨航/outputs", base / "outputs"),
                ("D:/巨航/workbench/data", base / "data"),
                ("D:/jhwb/models", base / "models"),
                ("D:/巨航/workbench/models", base / "models"),
                ("D:/巨航/workbench/", str(source) + "/"),
                ("D:/jhwb/", str(source) + "/"),
            ]:
                if normalized.startswith(old):
                    return str(new) + normalized[len(old):]
        return value

    cfg = fix(cfg)
    cfg["paths"].update(material_root=str(base / "materials"), data_root=str(base / "data"),
                        output_root=str(base / "outputs"), ffmpeg="/usr/bin/ffmpeg", cosyvoice_repo="")
    cfg["asr"]["device"] = "cuda:0"
    # Test an actual session: a listed encoder does not prove a vGPU permits it.
    probe = subprocess.run([
        "/usr/bin/ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=size=640x360:rate=1", "-frames:v", "1",
        "-c:v", "h264_nvenc", "-f", "null", "-",
    ], capture_output=True, timeout=20)
    cfg["render"]["encoder"] = "h264_nvenc" if probe.returncode == 0 else "libx264"
    cfg.setdefault("gpu", {})["mode"] = "local"
    # This server edits source footage and keeps its original speech.
    cfg["script"]["dub_mandarin"] = False
    output.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("Server video encoder:", cfg["render"]["encoder"])


if __name__ == "__main__":
    make(*(Path(arg).resolve() for arg in sys.argv[1:]))
