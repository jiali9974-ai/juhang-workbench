"""剪辑智能体：按 skills/edit_script.md 出剪辑脚本，一组素材只调用一次大模型。

三个阶段（分析句子 → 逐句质检 → 组合并整体检查，不合格就重选）由大模型在这一次调用里自己做完，只输出最后的脚本。
程序只做两件不调接口的事：
- 调用前：量好每句的时长、语速、句中停顿、和上一句首尾重复的字、句内重复、和前几句很像（重说），用“⚠”附在句子后面；
- 调用后：兜底——去掉不存在的编号和重复的句子、keep 不是“只删字”就退回原话、内容几乎一样的两句只留一句、时长明显不够的整条不要。
"""
from __future__ import annotations

import difflib
import json
import re

from . import config, llm, script as scriptmod

SKILL = config.ROOT / "skills" / "edit_script.md"
GROUP_SECONDS = 1200         # 素材按人声时长分组交给大模型，每组最多约 20 分钟



# ---------------- 提示词（skills/edit_script.md） ----------------

def system_prompt() -> str:
    raw = dict(re.findall(r"<!--\s*prompt:(\w+)\s*-->\s*(.*?)\s*<!--\s*/prompt\s*-->",
                          SKILL.read_text(encoding="utf-8"), re.S))
    missing = [k for k in ("system", "subtitle_original") if k not in raw]
    if missing:
        raise RuntimeError(f"{SKILL.name} 里缺少提示词：{'、'.join(missing)}")
    sc = config.load().get("script", {})
    text = raw["system"].replace("{subtitle_rules}", raw["subtitle_original"])
    vals = {"min_s": str(sc.get("min_seconds", 25)), "max_s": str(sc.get("max_seconds", 45)),
            "glossary": "\n".join(f"  - {g}" for g in sc.get("glossary", [])) or "  （无）",
            "keep_as_is": "、".join(sc.get("keep_as_is", [])) or "（无）"}
    for k, v in vals.items():
        text = text.replace("{" + k + "}", v)
    return text


# ---------------- 调用前：每句的提示 ----------------

def _bare(text: str) -> str:
    return scriptmod._bare(text)


def edge_overlap(a: str, b: str, max_n: int = 12, slack: int = 3) -> str:
    """a 的结尾在 b 的开头（b 开头允许先有 slack 个字的语气词）又说了一遍：返回重复的字，没有返回空。"""
    for k in range(min(len(a), max_n), 1, -1):
        if a[-k:] in b[: k + slack]:
            return a[-k:]
    return ""


def inner_repeat(s: str) -> str:
    """句子里重复说的一段：紧挨着的（结巴，“我哋我哋”→“我哋”），
    或者隔几个字又从头说一遍的（“这只表现在是非常值得入这只表现在非常值得入手”→“这只表现在”）。"""
    for n in range(min(12, len(s) // 2), 1, -1):
        for i in range(len(s) - 2 * n + 1):
            if s[i:i + n] == s[i + n:i + 2 * n]:
                return s[i:i + n]
    for n in range(min(10, len(s) // 2), 3, -1):
        for i in range(len(s) - 2 * n + 1):
            if s[i:i + n] in s[i + n:]:
                return s[i:i + n]
    return ""


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _same_content(a: str, b: str) -> bool:
    """两段（去掉标点的）文字是不是在讲同一句话：很像，或者短的整段包含在长的里面。"""
    if min(len(a), len(b)) < 4:
        return False
    short, long_ = sorted((a, b), key=len)
    return _similar(a, b) >= 0.75 or (len(short) >= 5 and short in long_)


def _longest_pause(words) -> tuple[float, str]:
    real = [w for w in words or [] if _bare(w[0])]
    best = (0.0, "")
    for p, q in zip(real, real[1:]):
        if q[1] - p[2] > best[0]:
            best = (q[1] - p[2], p[0])
    return best


def sentence_hints(sentences: list[dict]) -> list[list[str]]:
    """一条素材里每句的程序提示：时长、语速、句中停顿、和上一句首尾重复、句内重复、和前几句很像。"""
    out = []
    for i, s in enumerate(sentences):
        b, dur = _bare(s["text"]), max(0.0, s["end"] - s["start"])
        f = []
        rate = len(b) / dur if dur > 0 else 0.0
        if dur < 0.8 or len(b) <= 3:
            f.append(f"很短（{dur:.1f}秒{len(b)}字）")
        elif rate < 2.5:
            f.append(f"语速慢（{rate:.1f}字/秒，可能有停顿或拖音）")
        gap, after = _longest_pause(s.get("words"))
        if gap >= 0.6:
            f.append(f"句中停顿{gap:.1f}秒（“{after}”后面）")
        rep = inner_repeat(b)
        if rep:
            f.append(f"句内“{rep}”说了两遍")
        if i > 0:
            p = sentences[i - 1]
            ov = edge_overlap(_bare(p["text"]), b) if s["start"] - p["end"] < 3 else ""
            if ov:
                f.append(f"上一句结尾“{ov}”在这句开头又说了一遍")
            for j in range(i - 1, max(-1, i - 5), -1):
                yb = _bare(sentences[j]["text"])
                if min(len(yb), len(b)) >= 4 and (_similar(yb, b) >= 0.6 or (len(yb) >= 5 and yb in b) or (len(b) >= 5 and b in yb)):
                    f.append(f"和 S{j + 1} 很像（可能是重说）")
                    break
        out.append(f)
    return out


def _groups(transcripts: list[dict]) -> list[list[dict]]:
    """按拍摄顺序把素材分组，每组人声不超过 GROUP_SECONDS。"""
    groups, cur, acc = [], [], 0.0
    for t in transcripts:
        sp = sum(s["end"] - s["start"] for s in t["sentences"])
        if cur and acc + sp > GROUP_SECONDS:
            groups.append(cur)
            cur, acc = [], 0.0
        cur.append(t)
        acc += sp
    if cur:
        groups.append(cur)
    return groups


# ---------------- 调用 ----------------

def _ask(batch: str, body: str, done_titles: list[str]) -> dict:
    done = ("\n\n前面几组素材已经出过这些成片，同一组内容不要再出：\n" + "\n".join(f"- {t}" for t in done_titles)) if done_titles else ""
    last_err = None
    for _ in range(3):
        text = llm.chat([
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": f"以下是拍摄批次 {batch} 的一组素材识别结果：\n{body}{done}"},
        ], json_mode=True, temperature=0.3, max_tokens=16000)
        try:
            return scriptmod._extract_json(text)
        except ValueError as e:             # 偶尔输出不完整，重试
            last_err = e
    raise RuntimeError(f"大模型返回的脚本格式不对：{last_err}")


# ---------------- 调用后：兜底 ----------------

def _lines(video: dict, index: dict) -> list[dict]:
    """模型选的句子 → 剪辑脚本的句子。不存在的编号、重复的句子、和前面内容几乎一样的句子去掉（短的那句让给长的）。"""
    lines: list[dict] = []
    for item in video.get("lines") or []:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or "").strip()
        if ref not in index or any(l["ref"] == ref for l in lines):
            continue
        t, s = index[ref]
        keep = str(item.get("keep") or "").strip()
        keep = keep if scriptmod.is_deletion_of(keep, s["text"]) else s["text"]
        kb = _bare(keep)
        dup = next((l for l in lines if _same_content(_bare(l["keep"]), kb)), None)
        if dup is not None:
            if len(kb) <= len(_bare(dup["keep"])):
                continue                     # 这句是前面说过的话，不要
            lines.remove(dup)                # 前面那句是这句的一部分：留信息全的这句
        role = item.get("role") if item.get("role") in ("hook", "product", "cta") else "product"
        lines.append({"ref": ref, "clip": t["clip"], "start": s["start"], "end": s["end"], "src_lang": s["lang"],
                      "src_text": s["text"], "keep": keep, "words": s.get("words"),
                      "subtitle": str(item.get("subtitle") or "").strip(), "role": role, "zoom": None})
    return lines


def generate(batch: str, transcripts: list[dict], progress=None) -> list[dict]:
    """生成这一批素材的剪辑脚本（草稿）。素材多时分组，每组调用一次大模型。"""
    index, numbered = {}, {}
    for ci, t in enumerate(transcripts, 1):                    # 全批统一编号
        numbered[t["clip"]] = ci
        for si, s in enumerate(t["sentences"], 1):
            index[f"C{ci}-S{si}"] = (t, s)
    videos: list[dict] = []
    groups = _groups(transcripts)                               # 怎么分组（每组表、门店介绍）由 skill 在阶段一按内容自己分

    def clip_rows(ts: list[dict]) -> list[str]:
        rows = []
        for t in ts:
            ci = numbered[t["clip"]]
            rows.append(f"\n### 素材 C{ci}：{t['clip']}（{t['duration']:.0f} 秒）")
            for si, (s, hint) in enumerate(zip(t["sentences"], sentence_hints(t["sentences"])), 1):
                h = "；".join(x.replace("和 S", f"和 C{ci}-S") for x in hint)
                rows.append(f"C{ci}-S{si} [{s['start']:.1f}-{s['end']:.1f}] {s['end'] - s['start']:.1f}秒 ({s['lang']}) {s['text']}"
                            + (f"  ⚠{h}" if h else ""))
        return rows

    for gi, g in enumerate(groups):
        if progress:
            progress(gi, len(groups), f"大模型出脚本 {gi + 1}/{len(groups)} 组")
        videos += _ask(batch, "\n".join(clip_rows(g)), [v.get("title", "") for v in videos]).get("videos", [])

    min_s = config.load().get("script", {}).get("min_seconds", 25)
    scripts = []
    for v in videos:
        lines = _lines(v, index)
        if not lines or sum(l["end"] - l["start"] for l in lines) < min_s * 0.7:   # 时长明显不够的不要
            continue
        scripts.append({
            "id": "", "batch": batch, "title": v.get("title") or batch,
            "cover": [str(x).strip() for x in (v.get("cover") or []) if str(x).strip()][:2],
            "status": "draft", "lines": lines,
        })
    for i, s in enumerate(scripts, 1):
        s["id"] = f"{batch}_{i:02d}"
    return scripts
