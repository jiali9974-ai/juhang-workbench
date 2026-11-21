"""按实际原话衔接处的重复字过滤最终短镜头；不调用大模型，不修改音画边界。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import cancellation, config

if TYPE_CHECKING:
    from .render import Segment

THRESHOLD = .7


def describe(seg: Segment, index: int) -> dict:
    """用原素材绝对时间找字；定格补尾不计作原话，显示字幕不参与判断。"""
    start = seg.v_start
    end = start + (seg.v_content_dur if seg.v_content_dur is not None else seg.v_dur)
    parts, lines, partial, missing = [], [], False, False
    for line in seg.source_lines:
        if min(end, line["end"]) <= max(start, line["start"]) + 1e-6:
            continue
        words = line["words"]
        if words is None:
            missing = True
        selected = [(w, a, b) for w, a, b in words or [] if min(end, b) > max(start, a) + 1e-6]
        if selected or words is None:
            lines.append({k: line[k] for k in ("id", "ref", "text", "lang")})
        parts.extend(w for w, _, _ in selected)
        partial |= any(a < start - .001 or b > end + .001 for _, a, b in selected)
    return {"id": index, "clip": str(seg.clip), "start": start, "duration": seg.v_dur,
            "text": "".join(parts), "alignment": "unknown" if missing else "partial" if partial else "aligned",
            "source_lines": lines}


def _normalize(text: str) -> str:
    # 中文、粤语用字、数字和英文字母参与比较；空白、标点不计，英文不区分大小写。
    return "".join(char for char in text.casefold() if char.isalnum())


def _overlap(left: str, right: str) -> str:
    """只匹配左段结尾与右段开头的连续重复内容，保留字序。"""
    for size in range(min(len(left), len(right)), 0, -1):
        if left[-size:] == right[:size]:
            return right[:size]
    return ""


def filter_segments(segs: list[Segment], progress=None) -> tuple[list[Segment], dict]:
    """在同一份过滤前的时间线上统一判断，避免先删一个镜头改变其他镜头的上下文。"""
    enabled = (config.load()["render"].get("short_segment_filter") or {}).get("enabled", True)
    rows = [describe(seg, i) for i, seg in enumerate(segs)]
    texts = [_normalize(row["text"]) for row in rows]
    short = [i for i, seg in enumerate(segs) if seg.v_dur < THRESHOLD]
    decisions = {}
    for i in short:
        cancellation.check()
        own = texts[i]
        previous = _overlap(texts[i - 1], own) if i else ""
        following = _overlap(own, texts[i + 1]) if i + 1 < len(rows) else ""
        decision = {"action": "keep", "method": "boundary_overlap",
                    "previous_overlap": previous, "next_overlap": following}
        if not enabled:
            decision.update(action="delete", reason="已关闭首尾重复判断，按原时长规则删除")
        elif not own:
            decision["reason"] = "缺少可比较的实际字词，优先保留"
        elif previous or following:
            details = ([f"前段结尾与本段开头重复“{previous}”"] if previous else [])
            details += [f"本段结尾与后段开头重复“{following}”"] if following else []
            decision.update(action="delete", reason="；".join(details))
        else:
            decision["reason"] = "与前后相邻镜头的首尾衔接处没有重复字，保留"
        decisions[i] = decision
    cancellation.check()
    kept = [seg for i, seg in enumerate(segs) if decisions.get(i, {}).get("action") != "delete"]
    report = {"version": 1, "threshold": THRESHOLD, "enabled": enabled, "comparison": "boundary_overlap",
              "kept": sum(d["action"] != "delete" for d in decisions.values()),
              "deleted": sum(d["action"] == "delete" for d in decisions.values()),
              "candidates": [{**rows[i], **decisions[i], "retained": decisions[i]["action"] != "delete",
                              "before": rows[i - 1:i] if i else [], "after": rows[i + 1:i + 2]} for i in short]}
    if short and progress:
        progress(1, 1, f"短片段首尾重复检查：保留 {report['kept']} 段，删除 {report['deleted']} 段")
    return kept, report
