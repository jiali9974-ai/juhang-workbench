"""Generate AutoDL paths without changing the tracked desktop configuration."""
import sys
import subprocess
import hashlib
from pathlib import Path

import yaml
from select_device import select


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
    subprocess.run(["bash", str(source / "deploy/autodl/install_nvenc_compat.sh"), str(base)],
                   check=True, timeout=60)
    digest = hashlib.sha256((source / "deploy/autodl/nvenc-compat/nvenc_fix.c").read_bytes()).hexdigest()[:20]
    ffmpeg = str(base / "engines/nvenc-compat" / digest / "ffmpeg")
    cfg["paths"].update(material_root=str(base / "materials"), data_root=str(base / "data"),
                        output_root=str(base / "outputs"), ffmpeg=ffmpeg, cosyvoice_repo="")
    cfg = select(cfg)
    # This server edits source footage and keeps its original speech.
    cfg["script"]["dub_mandarin"] = False
    output.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("Server video encoder:", cfg["render"]["encoder"])


if __name__ == "__main__":
    make(*(Path(arg).resolve() for arg in sys.argv[1:]))
