"""剪辑脚本：存取、配音模式、句子里面剪口误（keep）。

出脚本的智能体在 jh/script_agent.py：按 skills/edit_script.md，一组素材调用一次大模型，
三个阶段（分析句子 → 逐句质检 → 组合并整体检查，不合格就重选）在这一次调用里做完。

剪辑脚本（edit script）结构，工作台里可以直接改：
{
  "id": "9.23_01",
  "batch": "9.23",
  "title": "两只日志 126333 / 126334",
  "cover": ["封面第一行", "封面第二行"],
  "voice_mode": "auto",          # auto：有普通话就整条用 TTS；original：保留原声；tts_all：全部 TTS
  "status": "draft",             # draft 草稿 / approved 已确认 / rendered 已出片
  "lines": [
    {"ref": "C1-S3", "clip": "xxx.MOV", "start": 12.3, "end": 15.8, "src_lang": "yue",
     "src_text": "识别原文", "keep": "原文删掉口误和犹豫声之后", "words": [["字", 12.3, 12.5], ...],
     "subtitle": "呢两只表呢", "role": "hook", "zoom": null}
  ]
}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config


def _extract_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def dub_mandarin() -> bool:
    """普通话的句子要不要转成粤语配音。False = 全部保留素材原声，普通话字幕就写普通话。"""
    return bool(config.load().get("script", {}).get("dub_mandarin", True))


def generate(batch: str, transcripts: list[dict], progress=None) -> list[dict]:
    """调用剪辑智能体生成这一批素材的剪辑脚本（草稿），做法见 jh/script_agent.py 和 skills/edit_script.md。"""
    from . import script_agent

    return script_agent.generate(batch, transcripts, progress)


# ---------------- 句子里面剪口误（keep） ----------------

_PUNCT_RE = re.compile(r"[\s，。！？、,.!?；;：:…~～\-—\"'“”‘’（）()]")


def _bare(text: str) -> str:
    return _PUNCT_RE.sub("", text or "")


def is_deletion_of(keep: str, src: str) -> bool:
    """keep 是不是只从 src 里删字得来的（不改字、不加字、不换顺序）。"""
    k, s = _bare(keep), _bare(src)
    if not k:
        return False
    it = iter(s)
    return all(ch in it for ch in k)


KEEP_PROMPT = """你是短视频剪辑师。下面是一条口播成片里每一句老板的原话（语音识别结果）。
有些句子里面带着口误：说到一半重来、结巴重复、犹豫拖长的声音。请给每一句写 keep：删掉口误之后要保留的文字。

规则：
- 只能删字，不能改字、加字、换顺序；错别字照原样保留。
- 要删：说到一半重来的前半截（“以前嘅公价咧要去到以前嘅公价咧要去到一百万” → “以前嘅公价咧要去到一百万”）、
  结巴重复（“我哋我哋呢度” → “我哋呢度”）、犹豫拖长的声音（嗯、呃、额、哎、诶，句首没意义的“啊”“嗯”）。
- 不要删正常说话里的语气词（咧、啦、嘅、喎、噶、句中和句尾的“啊”），删了声音会断断续续。
- 没有口误的句子 keep 照抄原话。

只输出 JSON：{"lines": [{"i": 0, "keep": "..."}, ...]}"""


def fill_keep(script: dict) -> bool:
    """给还没有 keep 的旧脚本补上（一次大模型调用）。返回是否有改动。"""
    todo = [i for i, l in enumerate(script["lines"]) if not l.get("keep")]
    if not todo:
        return False
    from . import llm

    body = "\n".join(f"{i}. {script['lines'][i]['src_text']}" for i in todo)
    try:
        text = llm.chat([{"role": "system", "content": KEEP_PROMPT}, {"role": "user", "content": body}],
                        json_mode=True, temperature=0.2, max_tokens=4000)
        got = {int(x["i"]): str(x.get("keep") or "").strip() for x in _extract_json(text)["lines"]}
    except Exception:  # noqa: BLE001  大模型不可用时：整句保留，照旧出片
        got = {}
    for i in todo:
        l = script["lines"][i]
        k = got.get(i, "")
        l["keep"] = k if is_deletion_of(k, l["src_text"]) else l["src_text"]
    return True


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
    for base in (scripts_dir(batch), config.output_root() / batch):
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
    if not dub_mandarin():
        return "original"
    return "tts_all" if any(l["src_lang"] == "zh" for l in script["lines"]) else "original"


def total_duration(script: dict) -> float:
    return sum(l["end"] - l["start"] for l in script["lines"])
