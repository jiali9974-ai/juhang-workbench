"""流程图：工作台每一步用什么模型，以及在网页上修改模型。

改动写回 config.yaml：只替换那一行的值，注释、空行、其他配置都不动；写完重新解析一遍核对，
不对就不写。改完对下一次任务生效（正在跑的任务可能已经读过旧配置）。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import yaml

from . import config

ENCODERS = [
    {"value": "h264_nvenc", "label": "H.264 · N 卡硬件编码", "note": "快，默认"},
    {"value": "hevc_nvenc", "label": "H.265 · N 卡硬件编码", "note": "同画质文件更小，个别老手机播放慢"},
    {"value": "libx264", "label": "H.264 · CPU 编码", "note": "没有 N 卡时用，慢很多"},
]
DEMUCS = [
    {"value": "htdemucs", "label": "HTDemucs", "note": "默认，已下载"},
    {"value": "htdemucs_ft", "label": "HTDemucs 精调版", "note": "分得更干净，慢约 4 倍；第一次用会联网下载"},
    {"value": "mdx_extra", "label": "MDX Extra", "note": "第一次用会联网下载"},
]
DEVICES = [
    {"value": "cuda:0", "label": "显卡 cuda:0", "note": "快"},
    {"value": "cpu", "label": "CPU", "note": "没有显卡时用，慢很多"},
]


def _config_path() -> Path:
    return Path(os.environ.get("JH_CONFIG", config.ROOT / "config.yaml"))


# ---------------- 可选项 ----------------

_llm_cache: dict = {"at": 0.0, "key": "", "models": [], "error": ""}


def llm_models(force: bool = False) -> tuple[list[str], str]:
    """中转站上能用的模型列表（缓存 10 分钟）。拿不到时返回空列表和原因。"""
    import requests

    cfg = config.load()["llm"]
    key = config.secret(cfg["api_key_env"])
    cache_key = f"{cfg['base_url']}|{bool(key)}"
    if not force and _llm_cache["key"] == cache_key and time.time() - _llm_cache["at"] < 600:
        return _llm_cache["models"], _llm_cache["error"]
    models, err = [], ""
    if not key:
        err = f"没有 API Key（secrets.yaml 里的 {cfg['api_key_env']}）"
    else:
        try:
            r = requests.get(cfg["base_url"].rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=8)
            r.raise_for_status()
            models = sorted({str(m["id"]) for m in r.json().get("data", []) if m.get("id")})
            if not models:
                err = "中转站没有返回模型列表"
        except Exception as e:  # noqa: BLE001
            err = f"拿不到中转站的模型列表：{str(e)[:120]}"
    _llm_cache.update(at=time.time(), key=cache_key, models=models, error=err)
    return models, err


def _asr_options(current: str) -> list[dict]:
    """和当前识别模型放在同一个目录里、像 FunASR 模型的文件夹（有 model.pt 和 config.yaml，排除 VAD）。"""
    base = Path(current).parent
    out = []
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.is_dir() and (d / "model.pt").exists() and (d / "config.yaml").exists() and "vad" not in d.name.lower():
                out.append({"value": f"{base.as_posix()}/{d.name}", "label": d.name})
    if not any(o["value"] == current for o in out):
        out.insert(0, {"value": current, "label": Path(current).name})
    return out


def _ming_models(current: str) -> list[dict]:
    base = Path(current).parent
    out = [{"value": f"{base.as_posix()}/{f.name}", "label": f.stem} for f in sorted(base.glob("*.gguf"))] if base.is_dir() else []
    if not any(o["value"] == current for o in out):
        out.insert(0, {"value": current, "label": Path(current).stem})
    return out


def _tts_options() -> list[dict]:
    from jh import ming_engine

    cfg = config.load()
    t = cfg["tts"]
    cv_dir = Path(cfg["paths"]["cosyvoice_repo"]) / t["cosyvoice3"]["model_dir"]
    cv_ok = (cv_dir / "llm.pt").exists() and (cv_dir / "flow.pt").exists() and not t["cosyvoice3"].get("broken")
    ming_ok, ming_msg = ming_engine.available()
    az_ok = bool(config.secret(t["azure"]["api_key_env"]))
    return [
        {"value": "ming", "label": "Ming-3.0 TTS 0.5B", "note": "克隆原声 · 约 2–3GB 显存" if ming_ok else ming_msg, "disabled": not ming_ok},
        {"value": "cosyvoice3", "label": "CosyVoice3 0.5B", "note": "本地模型" if cv_ok else (t["cosyvoice3"].get("broken") or "模型还没下载好"), "disabled": not cv_ok},
        {"value": "azure", "label": "Azure 粤语（云端）", "note": f"固定音色 {t['azure']['voice']}" if az_ok else "需要在 secrets.yaml 填 Key", "disabled": not az_ok},
    ]


# ---------------- 流程 ----------------

def _f(key: str, label: str, type_: str, value, options=None, note: str = "", custom: bool = False) -> dict:
    return {"key": key, "label": label, "type": type_, "value": value, "options": options or [], "note": note, "custom": custom}


def _info(label: str, value: str, note: str = "") -> dict:
    return {"key": None, "label": label, "type": "info", "value": value, "options": [], "note": note, "custom": False}


def describe() -> dict:
    cfg = config.load()
    a, llm, t, r, d = cfg["asr"], cfg["llm"], cfg["tts"], cfg["render"], cfg.get("dub", {})
    models, err = llm_models()
    llm_opts = [{"value": m, "label": m} for m in models]
    for m in [llm["model"], *llm.get("fallback_models", [])]:
        if m not in models:
            llm_opts.append({"value": m, "label": m, "note": "当前配置（中转站列表里没有）" if models else ""})
    key_ok = bool(config.secret(llm["api_key_env"]))
    dub_on = bool(cfg.get("script", {}).get("dub_mandarin", True))

    asr_fields = [
        _f("asr.sensevoice_dir", "识别模型", "select", a["sensevoice_dir"], _asr_options(a["sensevoice_dir"]),
           "SenseVoice：逐句识别并标出粤语 / 普通话"),
        _info("断句模型", Path(a["vad_dir"]).name, "FSMN-VAD：先把长视频切成一句一句"),
        _f("asr.device", "运行在", "select", a["device"], DEVICES),
    ]
    llm_fields = [
        _f("llm.model", "主模型", "select", llm["model"], llm_opts, err or ("" if key_ok else "没有 API Key"), custom=True),
        _f("llm.fallback_models", "备用模型", "list", llm.get("fallback_models", []), llm_opts,
           "主模型连续失败时按顺序换"),
        _f("llm.base_url", "接口地址", "text", llm["base_url"], note="OpenAI 兼容接口（中转站）；Key 在 secrets.yaml"),
    ]
    tts_fields = [
        _f("tts.engine", "配音引擎", "select", t["engine"], _tts_options(), "默认引擎；审核页每条脚本还能单独选"),
        _f("tts.ming.model", "Ming 模型文件", "select", t["ming"]["model"], _ming_models(t["ming"]["model"])),
    ]
    enc = _f("render.encoder", "视频编码", "select", r["encoder"], ENCODERS, f"{r['width']}×{r['height']} · {r['fps']}fps · {r['bitrate']}")
    matting_dir = config.data_root() / ((r.get("cover") or {}).get("matting_model") or "models/BiRefNet-portrait")
    matting_note = (
        "仅使用此模型抠图；显卡不可用或模型加载失败时停止出片并提示原因。"
        if (matting_dir / "model.safetensors").exists() else "未找到模型权重，需要补齐此模型后才能生成封面。"
    )

    clip = {
        "id": "clip", "title": "剪辑成片", "desc": "首页「开始生成」：识别 → 出脚本 → 出片",
        "steps": [
            {"id": "upload", "title": "上传素材", "desc": "视频存进项目文件夹（本机路径加载用硬链接）",
             "fields": [_info("素材目录", cfg["paths"]["material_root"])]},
            {"id": "asr", "title": "语音识别", "desc": "逐句识别，带逐字时间，用来剪口误和停顿", "fields": asr_fields},
            {"id": "script", "title": "出剪辑脚本", "desc": "大模型按「开头钩子 → 逐只表讲解 → 结尾引导」选句、写字幕",
             "fields": llm_fields},
            {"id": "tts", "title": "粤语配音", "desc": "把普通话的句子换成粤语配音" if dub_on else "已关闭：普通话保留原声，字幕写普通话",
             "off": not dub_on,
             "fields": [_f("script.dub_mandarin", "普通话转粤语配音", "toggle", dub_on), *tts_fields]},
            {"id": "look", "title": "美颜调色", "desc": "统一光线、磨皮、提亮；强度在「美颜设置」里调",
             "fields": [_info("人脸检测", "OpenCV Haar"), _info("人脸网格", "MediaPipe FaceMesh", "按老板肤色拉齐亮度和白平衡、局部磨皮")]},
            {"id": "cover", "title": "封面", "desc": "第一帧做封面：人像抠图 + 白描边 + 标题",
             "fields": [
                 _info("主抠图模型", matting_dir.name, matting_note),
                 _info("身体与手部定位", "MediaPipe Pose + Hands", "限制抠图范围，只保留人物身体、手臂和手。"),
                 _info("封面选帧", "MediaPipe FaceMesh", "检查人脸朝向、睁眼和表情，选取自然的封面画面。"),
             ]},
            {"id": "render", "title": "出片", "desc": "裁切放大 → 拼接 → 字幕 → 响度统一 → 背景音乐", "fields": [enc]},
        ],
    }
    dub = {
        "id": "dub", "title": "整条转粤语", "desc": "项目详情页「整条转粤语」：画面不剪，只换声音和字幕",
        "steps": [
            {"id": "dub-asr", "title": "语音识别", "desc": "和剪辑成片用同一个识别模型", "fields": asr_fields},
            {"id": "dub-translate", "title": "翻译成粤语", "desc": "逐句翻译，字数贴近原句跟嘴型", "fields": llm_fields[:1]},
            {"id": "dub-demucs", "title": "分离背景音乐", "desc": "去掉原人声，保留背景音乐和环境声",
             "fields": [_f("dub.demucs_model", "分离模型", "select", d.get("demucs_model", "htdemucs"), DEMUCS)]},
            {"id": "dub-tts", "title": "克隆原声配音", "desc": "用原主播的声音配粤语；开始时还能临时换引擎", "fields": tts_fields},
            {"id": "dub-render", "title": "换字幕出片", "desc": "模糊原字幕、压上粤语字幕", "fields": [enc]},
        ],
    }
    return {"root": "巨航剪辑工作台", "branches": [clip, dub], "llm_ready": key_ok}


# ---------------- 修改 ----------------

def _check(key: str, value):
    """校验网页传来的值，返回要写进 config.yaml 的值。"""
    cfg = config.load()
    if key == "asr.sensevoice_dir":
        if not any(o["value"] == value for o in _asr_options(cfg["asr"]["sensevoice_dir"])):
            raise ValueError("找不到这个识别模型")
        return value
    if key == "asr.device":
        if value not in {o["value"] for o in DEVICES}:
            raise ValueError("运行设备只能是 cuda:0 或 cpu")
        return value
    if key == "llm.model":
        v = str(value or "").strip()
        if not v or len(v) > 100 or re.search(r"\s", v):
            raise ValueError("模型名不能为空，也不能有空格")
        return v
    if key == "llm.fallback_models":
        if not isinstance(value, list):
            raise ValueError("备用模型要是列表")
        out = []
        for m in value:
            m = str(m or "").strip()
            if m and not re.search(r"\s", m) and m not in out:
                out.append(m)
        return out[:6]
    if key == "llm.base_url":
        v = str(value or "").strip().rstrip("/")
        if not re.match(r"^https?://\S+$", v):
            raise ValueError("接口地址要以 http:// 或 https:// 开头")
        return v
    if key == "script.dub_mandarin":
        return bool(value)
    if key == "tts.engine":
        opt = next((o for o in _tts_options() if o["value"] == value), None)
        if not opt:
            raise ValueError("没有这个配音引擎")
        if opt.get("disabled"):
            raise ValueError(f"{opt['label']} 现在用不了：{opt['note']}")
        return value
    if key == "tts.ming.model":
        if not any(o["value"] == value for o in _ming_models(cfg["tts"]["ming"]["model"])) or not Path(value).exists():
            raise ValueError("找不到这个 Ming 模型文件")
        return value
    if key == "render.encoder":
        if value not in {o["value"] for o in ENCODERS}:
            raise ValueError("不支持这个编码器")
        return value
    if key == "dub.demucs_model":
        if value not in {o["value"] for o in DEMUCS}:
            raise ValueError("不支持这个分离模型")
        return value
    raise ValueError(f"{key} 不能在网页上改")


_KEY_LINE = re.compile(r"^(\s*)([A-Za-z_][\w-]*):(.*)$")


def _split_comment(rest: str) -> tuple[str, str]:
    """「 "abc"   # 注释」→ (' "abc"', '   # 注释')：引号里的 # 不算注释。"""
    quote = None
    for i, ch in enumerate(rest):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or rest[i - 1] in " \t"):
            j = i
            while j > 0 and rest[j - 1] in " \t":
                j -= 1
            return rest[:j], rest[j:]
    return rest.rstrip(), ""


def _set_line(text: str, key: str, value) -> str:
    """把 config.yaml 里 key（a.b.c）那一行的值换掉，保留缩进和行尾注释。"""
    want = key.split(".")
    stack: list[tuple[int, str]] = []
    lines = text.splitlines(keepends=True)
    for n, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _KEY_LINE.match(line.rstrip("\r\n"))
        if not m:
            continue
        indent, name, rest = len(m.group(1)), m.group(2), m.group(3)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, name))
        if [s[1] for s in stack] == want:
            old, comment = _split_comment(rest)
            new = " " + json.dumps(value, ensure_ascii=False)
            if comment and len(new) < len(old):
                comment = " " * (len(old) - len(new)) + comment     # 注释尽量还在原来那一列
            elif comment and not comment.startswith((" ", "\t")):
                comment = "  " + comment
            eol = line[len(line.rstrip("\r\n")):]
            lines[n] = f"{m.group(1)}{name}:{new}{comment}{eol}"
            return "".join(lines)
    raise ValueError(f"config.yaml 里找不到 {key}")


def _get(data: dict, key: str):
    for p in key.split("."):
        data = data[p]
    return data


def update(changes: dict) -> dict:
    """改模型：校验 → 改 config.yaml 对应的行 → 重新解析核对 → 写回 → 清掉缓存。"""
    if not isinstance(changes, dict) or not changes:
        raise ValueError("没有要改的内容")
    vals = {k: _check(k, v) for k, v in changes.items()}
    path = _config_path()
    text = path.read_text(encoding="utf-8")
    new = text
    for k, v in vals.items():
        new = _set_line(new, k, v)
    parsed = yaml.safe_load(new)
    for k, v in vals.items():
        if _get(parsed, k) != v:
            raise ValueError(f"改 {k} 时出错，config.yaml 没有动")
    if new != text:
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(new, encoding="utf-8")
        os.replace(tmp, path)
    config.load.cache_clear()

    # 已经加载的模型按新配置重新加载
    if any(k.startswith("asr.") for k in vals):
        from jh import asr

        asr._models.cache_clear()
    if "tts.ming.model" in vals:
        from jh import ming_engine

        ming_engine.stop()
    if "llm.base_url" in vals:
        _llm_cache["at"] = 0.0
    return vals


def test_llm(model: str) -> dict:
    """用一句很短的话试一下这个模型能不能用、要多久。"""
    from jh import llm

    t0 = time.time()
    r = llm._client().chat.completions.create(
        model=model, messages=[{"role": "user", "content": "只回复两个字：收到"}], max_tokens=10)
    text = (r.choices[0].message.content or "").strip()
    return {"model": model, "reply": text[:40], "seconds": round(time.time() - t0, 1)}
