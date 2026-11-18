"""巨航剪辑工作台：本机网页服务。

启动：双击 start.bat，或运行  .venv/Scripts/python.exe app.py
然后浏览器打开 http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from jh import asr, config, deletion, media, outputs, render, script as scriptmod, uploads
from jh.jobs import JobQueue

app = FastAPI(title="巨航剪辑工作台")
jobs = JobQueue()
WEB = Path(__file__).parent / "web"


def _batch_dir(batch: str) -> Path:
    d = config.material_root() / batch
    if not d.is_dir() or ".." in batch:
        raise HTTPException(404, f"找不到批次 {batch}")
    return d


def _transcript_dir(batch: str) -> Path:
    return config.data_root() / "transcripts" / batch


def _load_transcripts(batch: str) -> list[dict]:
    d = _transcript_dir(batch)
    clips = media.list_clips(_batch_dir(batch))
    out = []
    for c in clips:
        f = d / f"{c.stem}.json"
        if f.exists():
            out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


# ---------------- 页面 ----------------

DIST = Path(__file__).parent / "frontend" / "dist"   # React 前端打包结果（cd frontend && npm run build）


@app.get("/", response_class=HTMLResponse)
def index():
    # 优先用打包好的 React 前端；没打包时退回旧的单文件页面
    page = DIST / "index.html" if (DIST / "index.html").exists() else WEB / "index.html"
    return page.read_text(encoding="utf-8")


@app.get("/assets/{name}")
def assets(name: str):
    f = (DIST / "assets" / name).resolve()
    if (DIST / "assets").resolve() not in f.parents or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/favicon.svg")
def favicon():
    return FileResponse(DIST / "favicon.svg", media_type="image/svg+xml")


# ---------------- GPU ----------------

@app.get("/api/gpu")
def gpu_status():
    mode = config.load().get("gpu", {}).get("mode", "local")
    info = {"mode": mode, "busy": jobs.busy()}
    if mode == "local":
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
            name, used, total, util = [x.strip() for x in r.stdout.strip().split(",")]
            info.update(state="running", name=name, mem=f"{used}/{total} MB", util=f"{util}%")
        except Exception:  # noqa: BLE001
            info.update(state="unknown", name="本机 GPU")
    return info


# ---------------- 批次 ----------------

@app.get("/api/batches")
def batches():
    root = config.material_root()
    out = []
    for d in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda x: -x.stat().st_mtime):
        clips = media.list_clips(d)
        done = sum((_transcript_dir(d.name) / f"{c.stem}.json").exists() for c in clips)
        scripts = scriptmod.list_scripts(d.name)
        outputs = list((config.output_root() / d.name).glob("*.mp4"))
        cache = config.data_root() / "clipinfo" / f"{d.name}.json"
        total = sum(json.loads(cache.read_text(encoding="utf-8")).values()) if cache.exists() else None
        out.append({"batch": d.name, "clips": len(clips), "transcribed": done, "total_seconds": total,
                    "scripts": len(scripts), "outputs": len(outputs),
                    "rendered": sum(s.get("status") == "rendered" for s in scripts)})
    return out


@app.get("/api/info")
def info():
    cfg = config.load()
    return {"llm": cfg["llm"]["model"],
            "llm_ready": bool(config.secret(cfg["llm"]["api_key_env"])),
            "gpu_mode": cfg.get("gpu", {}).get("mode", "local"),
            "min_seconds": None, "max_seconds": None}  # 兼容旧客户端；空值表示不限制时长


def _clip_durations(batch: str) -> dict:
    """素材时长缓存（只读容器头，很快）。"""
    import av

    cache = config.data_root() / "clipinfo" / f"{batch}.json"
    data = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    changed = False
    for c in media.list_clips(_batch_dir(batch)):
        if c.name not in data:
            with av.open(str(c)) as f:
                data[c.name] = round(f.duration / 1_000_000, 2) if f.duration else 0
            changed = True
    if changed:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


@app.get("/api/batches/{batch}/clips")
def clips(batch: str):
    durs = _clip_durations(batch)
    tdir = _transcript_dir(batch)
    out = []
    for c in media.list_clips(_batch_dir(batch)):
        f = tdir / f"{c.stem}.json"
        item = {"clip": c.name, "duration": durs.get(c.name, 0), "transcribed": f.exists(), "lang": {}, "sentences": 0}
        if f.exists():
            t = json.loads(f.read_text(encoding="utf-8"))
            item["sentences"] = len(t["sentences"])
            item["lang"] = asr.lang_stats([t])
            item["preview_text"] = "".join(s["text"] for s in t["sentences"][:4])[:60]
        out.append(item)
    return out


@app.get("/api/batches/{batch}/transcripts/{clip}")
def clip_transcript(batch: str, clip: str):
    f = _transcript_dir(batch) / f"{Path(clip).stem}.json"
    if not f.exists():
        raise HTTPException(404, "这条素材还没识别")
    return json.loads(f.read_text(encoding="utf-8"))


@app.get("/api/thumb")
def thumb(batch: str, clip: str, t: float = 1.0):
    """素材缩略图（竖屏 270×480，有缓存）。"""
    src = _batch_dir(batch) / clip
    if not src.exists() or "/" in clip or "\\" in clip:
        raise HTTPException(404)
    out = config.data_root() / "thumbs" / batch / f"{src.stem}_{t:.1f}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        media.run_ffmpeg(["-ss", f"{max(0.0, t):.2f}", "-i", str(src), "-frames:v", "1",
                          "-vf", "scale=270:480:force_original_aspect_ratio=increase,crop=270:480", "-q:v", "4", str(out)])
    return FileResponse(out, media_type="image/jpeg")


@app.get("/api/output_thumb/{batch}/{sid}.jpg")
def output_thumb(batch: str, sid: str):
    try:
        src = outputs.output_path(batch, sid)
    except ValueError:
        raise HTTPException(404)
    if not src.exists():
        raise HTTPException(404)
    cover = src.with_name(f"{sid}_封面.jpg")
    if cover.exists():                                   # 有做好的封面就用封面，没有才从成片截一帧
        out = config.data_root() / "thumbs" / batch / f"cover_{sid}_{int(cover.stat().st_mtime)}.jpg"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            media.run_ffmpeg(["-i", str(cover), "-vf", "scale=270:480", "-q:v", "3", str(out)])
    else:
        out = config.data_root() / "thumbs" / batch / f"out_{sid}_{int(src.stat().st_mtime)}.jpg"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            media.run_ffmpeg(["-ss", "1.5", "-i", str(src), "-frames:v", "1", "-vf", "scale=270:480", "-q:v", "4", str(out)])
    # 封面重做后地址不变：让浏览器每次都来问一下，不用旧图
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


# ---------------- 素材剪辑项目：新建、上传素材 ----------------

_BAD_NAME = set('\\/:*?"<>|')


def _safe_name(name: str) -> str:
    name = "".join(c for c in (name or "").strip() if c not in _BAD_NAME and ord(c) >= 32).strip(" .")
    return name[:60]


@app.post("/api/batches")
def create_batch(data: dict = Body(...)):
    """新建一个素材剪辑项目（在素材目录下建文件夹）。"""
    folder = str(data.get("folder") or "").strip().strip('"')
    if folder and not Path(folder).is_dir():
        raise HTTPException(400, f"找不到文件夹：{folder}")
    name = _safe_name(data.get("name", "") or (Path(folder).name if folder else ""))
    if not name or name in (".", ".."):
        raise HTTPException(400, "项目名不能为空，也不能有 \\ / : * ? \" < > | 这些字符")
    d = config.material_root() / name
    try:
        d.mkdir(parents=True)
    except FileExistsError:
        raise HTTPException(400, f"已经有叫「{name}」的项目了")
    job = jobs.submit("import", f"加载文件夹到 {name}", lambda pr: _import_folder(name, folder, pr)).to_dict() if folder else None
    return {"batch": name, "job": job}


@app.put("/api/batches/{batch}/upload")
async def upload_clip(batch: str, request: Request, filename: str,
                      upload_id: str | None = None, expected_size: int | None = None):
    """流式上传；同一队列项重试返回原结果，新素材同名时改名保存。"""
    d = _batch_dir(batch)
    name = _safe_name(Path(filename).name)
    ext = Path(name).suffix.lower()
    if ext not in media.VIDEO_EXTS:
        raise HTTPException(400, f"只支持 {'、'.join(sorted(media.VIDEO_EXTS))} 视频文件")
    if expected_size is None and request.headers.get("content-length"):
        expected_size = int(request.headers["content-length"])
    return await uploads.receive(d, config.data_root(), name, request.stream(),
                                 upload_id=upload_id, expected_size=expected_size)



def _import_folder(batch: str, src: str, progress=None) -> dict:
    """把本机一个文件夹（含子文件夹）里的视频加进项目：同一硬盘用硬链接（瞬间完成、不占额外空间），否则复制。"""
    import os
    import shutil

    root = Path(src.strip().strip('"'))
    if not root.is_dir():
        raise RuntimeError(f"找不到文件夹：{src}")
    dst = _batch_dir(batch)
    files = sorted(f for f in root.rglob("*") if f.is_file() and f.suffix.lower() in media.VIDEO_EXTS)
    if not files:
        raise RuntimeError("这个文件夹里没有 .mov / .mp4 / .m4v 视频")
    added, linked = [], 0
    for i, f in enumerate(files):
        if progress:
            progress(i, len(files), f"加载 {f.name}（{i + 1}/{len(files)}）")
        rel = f.relative_to(root)
        # 子文件夹里的文件：文件夹名_文件名，避免重名。文件夹名很长时只截前面的名字，扩展名一定保留（以前会把 .MOV 截掉）
        raw = "_".join(rel.parts[:-1] + (f.stem,))
        stem = "".join(c for c in raw if c not in _BAD_NAME and ord(c) >= 32).strip(" .")[: 80 - len(f.suffix)] or "clip"
        name = stem + f.suffix
        target, n = dst / name, 1
        while target.exists():
            if target.stat().st_size == f.stat().st_size:
                break                                    # 同名同大小，视为已加载过
            n += 1
            target = dst / f"{Path(name).stem}_{n}{Path(name).suffix}"
        if target.exists():
            continue
        try:
            os.link(f, target)                           # 同一硬盘：硬链接
            linked += 1
        except OSError:
            shutil.copy2(f, target)                      # 跨硬盘：复制
        added.append(target.name)
    return {"added": len(added), "linked": linked, "copied": len(added) - linked, "total": len(files)}


@app.post("/api/batches/{batch}/import_folder")
def import_folder(batch: str, data: dict = Body(...)):
    _batch_dir(batch)
    path = str(data.get("path") or "").strip()
    if not path:
        raise HTTPException(400, "请填写文件夹路径")
    if not Path(path.strip('"')).is_dir():
        raise HTTPException(400, f"找不到文件夹：{path}")
    return jobs.submit("import", f"加载文件夹到 {batch}", lambda pr: _import_folder(batch, path, pr)).to_dict()



@app.get("/api/batches/{batch}/transcripts")
def transcripts(batch: str):
    ts = _load_transcripts(batch)
    return {"stats": asr.lang_stats(ts), "transcripts": ts}


@app.post("/api/batches/{batch}/transcribe")
def transcribe(batch: str):
    folder = _batch_dir(batch)
    job = jobs.submit("transcribe", f"{batch} 语音识别",
                      lambda p: asr.lang_stats(asr.transcribe_folder(folder, _transcript_dir(batch), p)))
    return job.to_dict()


@app.post("/api/batches/{batch}/generate")
def generate(batch: str):
    folder = _batch_dir(batch)

    def run(p):
        ts = asr.transcribe_folder(folder, _transcript_dir(batch), p)
        p.set_stage("script")
        p(0, 1, "大模型出剪辑脚本中")
        scripts = scriptmod.generate(batch, ts, p)
        scriptmod.archive_batch(batch)   # 旧脚本和旧成片挪去 _old_时间 目录，不删除
        for s in scripts:
            scriptmod.save(s)
        p(1, 1, f"已生成 {len(scripts)} 条剪辑脚本，等你审核")
        return [s["id"] for s in scripts]

    return jobs.submit("generate", f"{batch} 识别并出脚本", run).to_dict()


# ---------------- 剪辑脚本 ----------------

@app.get("/api/batches/{batch}/scripts")
def scripts(batch: str):
    res = []
    for s in scriptmod.list_scripts(batch):
        out = config.output_root() / batch / f"{s['id']}.mp4"
        res.append({**s, "duration": round(scriptmod.total_duration(s), 1),
                    "has_output": out.exists()})
    return res


@app.put("/api/batches/{batch}/scripts/{sid}")
def save_script(batch: str, sid: str, data: dict = Body(...)):
    if data.get("id") != sid or data.get("batch") != batch:
        raise HTTPException(400, "脚本编号不匹配")
    scriptmod.save(data)
    return {"ok": True}


@app.delete("/api/batches/{batch}/scripts/{sid}")
def delete_script(batch: str, sid: str):
    p = scriptmod.scripts_dir(batch) / f"{sid}.json"
    if p.exists():
        p.unlink()
    return {"ok": True}


@app.post("/api/batches/{batch}/scripts/{sid}/render")
def render_script(batch: str, sid: str):
    s = scriptmod.load(batch, sid)

    def run(p):
        out = render.render(s, p, on_stage=p.set_stage)
        s2 = scriptmod.load(batch, sid)
        s2["status"] = "rendered"
        scriptmod.save(s2)
        return str(out)

    return jobs.submit("render", f"{sid} 出片", run).to_dict()


@app.post("/api/batches/{batch}/render_all")
def render_all(batch: str, data: dict = Body(default={})):
    """把这一批还没出片的脚本全部排队出片。all=true 时已出片的也重新出（比如调了美颜之后）。"""
    queued = []
    redo = bool((data or {}).get("all"))
    for s in scriptmod.list_scripts(batch):
        if s.get("status") == "rendered" and not redo:
            continue
        s["status"] = "approved"
        scriptmod.save(s)
        queued.append(render_script(batch, s["id"]))
    return queued


# ---------------- 美颜和调色强度（页面上调，批量出片都用这个） ----------------

@app.get("/api/look")
def get_look():
    from jh import look

    return {"settings": look.current(), "defaults": look.DEFAULTS}


@app.put("/api/look")
def put_look(data: dict = Body(...)):
    from jh import look

    return {"settings": look.save(data)}


@app.post("/api/look/preview")
def look_preview(data: dict = Body(...)):
    """出一组对比图（原片 / 按当前滑块设置美颜后），kind = face（人脸）或 watch（手表特写）。"""
    from jh import look

    try:
        if "source" in data or not data.get("batch"):
            return look.preview_source(data.get("source"), str(data.get("kind") or "face"),
                                       data.get("settings"), jobs.list())
        batch = str(data["batch"])
        _batch_dir(batch)
        return look.preview(batch, str(data.get("kind") or "face"), data.get("settings"), int(data.get("index") or 0))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/look/file/{name}")
def look_file(name: str):
    from jh import look

    f = (look._preview_dir() / name).resolve()
    if look._preview_dir().resolve() not in f.parents or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg")


@app.get("/api/preview_clip")
def preview_clip(batch: str, clip: str, start: float, end: float):
    """审核时看原片：把这句话在原素材里的片段转成小尺寸 MP4（有缓存）。"""
    src = _batch_dir(batch) / clip
    if not src.exists() or "/" in clip or "\\" in clip:
        raise HTTPException(404)
    s, e = max(0.0, start - 0.3), end + 0.3
    out = config.data_root() / "preview" / batch / f"{src.stem}_{s:.2f}_{e:.2f}.mp4"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        media.run_ffmpeg(["-ss", f"{s:.3f}", "-t", f"{e - s:.3f}", "-i", str(src),
                          "-vf", "scale=540:-2,fps=30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                          "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)])
    return FileResponse(out, media_type="video/mp4")


@app.post("/api/batches/{batch}/auto")
def auto(batch: str):
    """一键直接出片：识别 → 大模型出脚本 → 全部出片，中间不停下来审核。"""
    folder = _batch_dir(batch)

    def run(p):
        ts = asr.transcribe_folder(folder, _transcript_dir(batch), lambda i, n, m: p(i, n * 3, f"识别 {m}"))
        p.set_stage("script")
        p(1, 3, "大模型出剪辑脚本中")
        scripts = scriptmod.generate(batch, ts, lambda i, n, m: p(1 + (i / n if n else 0), 3, m))
        scriptmod.archive_batch(batch)
        for s in scripts:
            s["status"] = "approved"
            scriptmod.save(s)
        outs = []
        for i, s in enumerate(scripts):
            def sub(j, n, m, i=i):
                p(2 * len(scripts) + i * 1 + (j / n if n else 0), 3 * len(scripts), f"第 {i + 1}/{len(scripts)} 条：{m}")
            outs.append(str(render.render(s, sub, on_stage=p.set_stage)))
            s2 = scriptmod.load(batch, s["id"])
            s2["status"] = "rendered"
            scriptmod.save(s2)
        p(1, 1, f"完成，共出 {len(outs)} 条成片")
        return outs

    return jobs.submit("auto", f"{batch} 一键出片", run).to_dict()


class OutputSelection(BaseModel):
    batch: str = ""
    id: str = Field(min_length=1)


class ExportSelection(BaseModel):
    items: list[OutputSelection] = Field(min_length=1)


@app.get("/api/outputs")
def all_outputs():
    return outputs.list_outputs(jobs.list(10000))


@app.get("/api/root_output_thumb/{sid}.jpg")
def root_output_thumb(sid: str):
    return output_thumb("", sid)


@app.get("/api/root_outputs/{sid}.mp4")
def root_output(sid: str):
    return output("", sid)


@app.delete("/api/root_outputs/{sid}")
def delete_root_output(sid: str):
    return delete_output("", sid)


@app.post("/api/outputs/export")
def export_outputs(data: ExportSelection):
    try:
        token = outputs.export_outputs([(item.batch, item.id) for item in data.items], jobs.list(10000))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"url": f"/api/exports/{token}.zip"}


@app.delete("/api/outputs/{batch}/{sid}")
def delete_output(batch: str, sid: str):
    try:
        outputs.delete_output(batch, sid, jobs.list(10000))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.get("/api/exports/{token}.zip")
def download_export(token: str):
    try:
        path = outputs.export_path(token)
    except ValueError:
        raise HTTPException(404)
    if not path.is_file():
        raise HTTPException(404, "导出文件已过期，请重新导出")
    return FileResponse(path, media_type="application/zip", filename="成片.zip",
                        background=BackgroundTask(path.unlink, missing_ok=True))


@app.get("/api/outputs/{batch}/{sid}.mp4")
def output(batch: str, sid: str):
    try:
        f = outputs.output_path(batch, sid)
    except ValueError:
        raise HTTPException(404)
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="video/mp4", filename=f"{sid}.mp4")


# ---------------- 任务 ----------------

@app.get("/api/jobs")
def job_list():
    return jobs.list()


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = jobs.jobs.get(jid)
    if not j:
        raise HTTPException(404)
    return j.to_dict()


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    try:
        return jobs.cancel(jid)
    except KeyError:
        raise HTTPException(404, "找不到任务")


# ---------------- 直接删除项目 ----------------


def _busy_with(name: str) -> bool:
    return any(j["status"] in ("queued", "running") and name in j["title"] for j in jobs.list(200))


@app.delete("/api/batches/{batch}")
def delete_batch(batch: str):
    """直接删除项目的素材、识别结果、脚本和成片。"""
    try:
        d = deletion.child_path(config.material_root(), batch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not d.is_dir():
        raise HTTPException(404, f"找不到批次 {batch}")
    if _busy_with(batch):
        raise HTTPException(409, "这个项目还有任务在跑，等跑完再删")
    root = config.data_root()
    targets = [(config.material_root(), batch), (config.output_root(), batch)]
    targets.extend((root / sub, batch) for sub in ("transcripts", "scripts", "renders", "preview", "thumbs", "upload_receipts"))
    targets.append((root / "clipinfo", f"{batch}.json"))
    try:
        deletion.delete_children(targets)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ---------------- 流程图：每一步用的模型，网页上直接改 ----------------

# 这几项要重新加载模型，有任务在跑时不让改
_NEEDS_IDLE = {"asr.sensevoice_dir", "asr.device"}


@app.get("/api/pipeline")
def pipeline_get():
    from jh import pipeline

    return pipeline.describe()


@app.put("/api/pipeline")
def pipeline_put(data: dict = Body(...)):
    from jh import pipeline

    changes = (data or {}).get("changes") or {}
    if _NEEDS_IDLE & set(changes) and jobs.busy():
        raise HTTPException(409, "有任务在跑，识别模型要等任务跑完再换（其他模型现在就能改）")
    try:
        saved = pipeline.update(changes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"saved": saved, "pipeline": pipeline.describe()}


@app.post("/api/pipeline/llm_models")
def pipeline_llm_models():
    """重新向中转站要一次模型列表。"""
    from jh import pipeline

    models, err = pipeline.llm_models(force=True)
    return {"models": models, "error": err}


@app.post("/api/pipeline/test_llm")
def pipeline_test_llm(data: dict = Body(...)):
    from jh import pipeline

    model = str((data or {}).get("model") or "").strip()
    if not model:
        raise HTTPException(400, "请选一个模型")
    try:
        return pipeline.test_llm(model)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"{model} 调用失败：{str(e)[:200]}")


if __name__ == "__main__":
    import os

    # JH_PORT：同时开第二个工作台（比如测试新版本）时换个端口
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("JH_PORT", "8765")))
