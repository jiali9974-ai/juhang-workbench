"""剪辑脚本：把一批素材的识别结果交给大模型，按参考视频的结构选段并写粤语字幕。

剪辑脚本（edit script）结构，工作台里可以直接改：
{
  "id": "9.23_01",
  "batch": "9.23",
  "title": "两只日志 126333 / 126334",
  "voice_mode": "auto",          # auto：有普通话就整条用 TTS；original：保留原声；tts_all：全部 TTS
  "status": "draft",             # draft 草稿 / approved 已确认 / rendered 已出片
  "lines": [
    {"clip": "xxx.MOV", "start": 12.3, "end": 15.8, "src_lang": "yue",
     "src_text": "识别原文", "subtitle": "呢两只表呢", "role": "hook", "zoom": null}
  ]
}
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import config

SYSTEM_PROMPT = """你是一名短视频剪辑导演，负责把名表商家的口播原始素材剪成抖音竖屏带货短视频。

## 参考成片的结构（必须遵守）
1. 开头钩子（1–3 句）：老板出镜，一句话说清这条视频卖什么，例如“呢两只表呢”“今日想处理一批表啊”。
2. 产品讲解（主体）：逐只表讲型号、表径、表盘颜色、材质、链带、年份、配件、公价和现价等卖点。
3. 结尾引导（1–2 句）：例如“如果你哋钟意嘅话，我将两只表嘅底价都发畀你哋”。
每条成片 25–45 秒，通常聚焦 1–2 只表。

## 选段规则
- 只能从给出的原话句子里选，用句子编号引用；不要编造原话里没有的型号、价格、年份等信息。
- 老板经常把同一组表重拍好几遍（相邻几条素材讲的是同一组表）。同一组表只出一条成片，挑讲得最完整、最顺的那一遍；不要为同一组表出多条。
- 去掉口误、重复、说到一半重来的句子（例如“以前嘅公价咧要去到以前嘅公价咧要去到”只保留完整的那句）；去掉“嗯”“啊”这类单独的语气词。
- 每条成片选中句子的时长（方括号里的起止秒数之差）加起来必须在 {min_s}–{max_s} 秒之间；达不到的素材不要出。
- 同一条素材内保持原来的先后顺序；一条成片可以用 1–3 条相邻的素材。

## 字幕规则（字幕同时也是配音文案）
- 每句写成粤语口语书面字，用简体字：呢、嘅、系、唔、畀、啲、咗、嚟、佢、哋、冇、睇、嘢、咁、噉。
- 原话是粤语（yue）：只改正语音识别的错别字，保持口语，不要改成书面语。粤语句子会保留老板原声，所以字幕必须和这一句原话一一对应：不能加词、不能把别的句子的内容并进来、不能删掉意思。
- 原话是普通话（zh）：翻译成自然的粤语口语，意思不变。
- 语音识别常见错字，必须按下表改：
{glossary}
- 这些词认不准、也不知道正确写法，原样保留：{keep}
- 一个句子编号对应一条字幕；字幕不要加句末句号，可以保留逗号。

## 输出
只输出 JSON，不要任何解释，格式：
{"videos": [
  {"title": "简短标题", "lines": [
     {"ref": "C2-S5", "role": "hook|product|cta", "subtitle": "粤语字幕"}
  ]}
]}
"""


def build_transcript_text(transcripts: list[dict]) -> tuple[str, dict]:
    """把一批识别结果编号成 C{素材}-S{句子}，返回给模型看的文本和编号索引。"""
    lines, index = [], {}
    for ci, t in enumerate(transcripts, 1):
        lines.append(f"\n### 素材 C{ci}：{t['clip']}（{t['duration']:.0f} 秒）")
        for si, s in enumerate(t["sentences"], 1):
            ref = f"C{ci}-S{si}"
            index[ref] = (t, s)
            lines.append(f"{ref} [{s['start']:.1f}-{s['end']:.1f}] ({s['lang']}) {s['text']}")
    return "\n".join(lines), index


def _client():
    from openai import OpenAI

    cfg = config.load()["llm"]
    key = config.secret(cfg["api_key_env"])
    if not key:
        raise RuntimeError(f"没有设置大模型 API Key：在 secrets.yaml 里填 {cfg['api_key_env']}")
    return OpenAI(base_url=cfg["base_url"], api_key=key), cfg["model"]


def _extract_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _groups(transcripts: list[dict], max_speech: float = 360) -> list[list[dict]]:
    """按拍摄顺序把素材分组，每组人声不超过约 6 分钟，避免一次让模型输出太长。"""
    groups, cur, acc = [], [], 0.0
    for t in transcripts:
        sp = sum(s["end"] - s["start"] for s in t["sentences"])
        if cur and acc + sp > max_speech:
            groups.append(cur)
            cur, acc = [], 0.0
        cur.append(t)
        acc += sp
    if cur:
        groups.append(cur)
    return groups


def system_prompt() -> str:
    sc = config.load().get("script", {})
    glossary = "\n".join(f"  - {g}" for g in sc.get("glossary", [])) or "  （无）"
    return (SYSTEM_PROMPT.replace("{min_s}", str(sc.get("min_seconds", 25)))
            .replace("{max_s}", str(sc.get("max_seconds", 45)))
            .replace("{glossary}", glossary)
            .replace("{keep}", "、".join(sc.get("keep_as_is", [])) or "（无）"))


def _ask(client, model: str, batch: str, body: str, done_titles: list[str]) -> dict:
    done = ("\n\n前面几组素材已经出过这些成片，同一组表不要再出：\n" + "\n".join(f"- {t}" for t in done_titles)) if done_titles else ""
    last_err = None
    for _ in range(3):
        resp = client.chat.completions.create(
            model=model,
            temperature=0.3,
            max_tokens=8000,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": f"以下是拍摄批次 {batch} 的一组素材识别结果：\n{body}{done}"},
            ],
        )
        try:
            return _extract_json(resp.choices[0].message.content)
        except json.JSONDecodeError as e:  # 偶尔输出不完整，重试
            last_err = e
    raise RuntimeError(f"大模型返回的脚本格式不对：{last_err}")


def generate(batch: str, transcripts: list[dict], progress=None) -> list[dict]:
    """调用大模型生成这一批素材的剪辑脚本（草稿）。素材多时分组请求。"""
    client, model = _client()
    _, index = build_transcript_text(transcripts)          # 全批统一编号
    numbered = {t["clip"]: ci for ci, t in enumerate(transcripts, 1)}
    videos: list[dict] = []
    groups = _groups(transcripts)
    for gi, g in enumerate(groups):
        if progress:
            progress(gi, len(groups), f"大模型出脚本 {gi + 1}/{len(groups)} 组")
        lines = []
        for t in g:
            ci = numbered[t["clip"]]
            lines.append(f"\n### 素材 C{ci}：{t['clip']}（{t['duration']:.0f} 秒）")
            for si, s in enumerate(t["sentences"], 1):
                lines.append(f"C{ci}-S{si} [{s['start']:.1f}-{s['end']:.1f}] ({s['lang']}) {s['text']}")
        videos += _ask(client, model, batch, "\n".join(lines), [v.get("title", "") for v in videos]).get("videos", [])
    scripts = from_llm_output(batch, {"videos": videos}, index)
    # 兜底：时长明显不够的不要（模型偶尔不守规矩）
    min_s = config.load().get("script", {}).get("min_seconds", 25)
    kept = [s for s in scripts if total_duration(s) >= min_s * 0.7]
    for i, s in enumerate(kept, 1):
        s["id"] = f"{batch}_{i:02d}"
    return kept


def from_llm_output(batch: str, data: dict, index: dict) -> list[dict]:
    scripts = []
    for vi, v in enumerate(data.get("videos", []), 1):
        lines = []
        for item in v.get("lines", []):
            ref = item.get("ref", "").strip()
            if ref not in index:
                continue  # 模型引用了不存在的句子，丢掉
            t, s = index[ref]
            lines.append({
                "ref": ref,
                "clip": t["clip"],
                "start": s["start"],
                "end": s["end"],
                "src_lang": s["lang"],
                "src_text": s["text"],
                "subtitle": item.get("subtitle", "").strip(),
                "role": item.get("role", "product"),
                "zoom": None,
            })
        if lines:
            scripts.append({
                "id": f"{batch}_{vi:02d}",
                "batch": batch,
                "title": v.get("title", f"{batch} 第{vi}条"),
                "voice_mode": "auto",
                "status": "draft",
                "lines": lines,
            })
    return scripts


def scripts_dir(batch: str) -> Path:
    p = config.data_root() / "scripts" / batch
    p.mkdir(parents=True, exist_ok=True)
    return p


def archive_batch(batch: str) -> Path | None:
    """重新出脚本前，把这一批旧的脚本和成片挪进 _old_时间 目录（不删除）。"""
    import shutil
    import time

    stamp = time.strftime("%Y%m%d_%H%M%S")
    moved = None
    for base in (scripts_dir(batch), config.data_root() / "outputs" / batch):
        files = [p for p in base.glob("*") if p.is_file()] if base.exists() else []
        if files:
            dst = base / f"_old_{stamp}"
            dst.mkdir(parents=True, exist_ok=True)
            for f in files:
                shutil.move(str(f), dst / f.name)
            moved = dst
    return moved


def save(script: dict) -> Path:
    p = scripts_dir(script["batch"]) / f"{script['id']}.json"
    p.write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load(batch: str, script_id: str) -> dict:
    return json.loads((scripts_dir(batch) / f"{script_id}.json").read_text(encoding="utf-8"))


def list_scripts(batch: str) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(scripts_dir(batch).glob("*.json"))]


def resolved_voice_mode(script: dict) -> str:
    """auto 模式下：只要有一句原话是普通话，整条都用 TTS，保证声音一致。"""
    mode = script.get("voice_mode", "auto")
    if mode != "auto":
        return mode
    return "tts_all" if any(l["src_lang"] == "zh" for l in script["lines"]) else "original"


def total_duration(script: dict) -> float:
    return sum(l["end"] - l["start"] for l in script["lines"])
