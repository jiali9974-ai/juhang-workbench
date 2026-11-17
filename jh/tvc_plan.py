"""产品贴字 TVC 方案：把视觉识别结果 + 用户需求交给大模型，按 skills/product_tvc.md 输出结构化方案。"""
from __future__ import annotations

import json
from pathlib import Path

from . import config, llm, script as scriptmod

SPEC = Path(__file__).resolve().parent.parent / "skills" / "product_tvc.md"


def _validate(plan: dict, segments: int) -> list[str]:
    errs = []
    kfs, segs = plan.get("keyframes", []), plan.get("segments", [])
    if len(kfs) != segments + 1:
        errs.append(f"关键帧应为 {segments + 1} 张，实际 {len(kfs)} 张")
    if len(segs) != segments:
        errs.append(f"视频段应为 {segments} 段，实际 {len(segs)} 段")
    for i, k in enumerate(kfs, 1):
        if "<image1>" not in k.get("image_prompt", ""):
            errs.append(f"关键帧 {i} 没有用 <image1> 引用产品图")
    for i, s in enumerate(segs, 1):
        if (s.get("from"), s.get("to")) != (i, i + 1):
            errs.append(f"第 {i} 段的首尾帧应为 {i}→{i + 1}")
        if "no background music" not in s.get("video_prompt", "").lower():
            errs.append(f"第 {i} 段视频提示词缺少 No background music")
    return errs


def generate(brief: dict, caption: str) -> dict:
    """brief：产品名、品牌、卖点、风格要求等（用户填写）；caption：Qwen3-VL 看图的识别结果。"""
    c = config.load()["tvc"]
    segments, seconds = int(c["segments"]), float(c["seconds_per_segment"])
    user = f"""## 用户填写（以此为准，和识别结果冲突时听用户的）
产品名称：{brief.get('product') or '（未填）'}
品牌名：{brief.get('brand') or '（未填，不要编造品牌名）'}
核心卖点：{brief.get('selling_points') or '（未填，从识别结果中提炼通用卖点）'}
风格/其他要求：{brief.get('notes') or '（无）'}

## 产品图视觉识别结果（Qwen3-VL，型号判断可能不准，仅作外观参考）
{caption}

## 规格
竖屏 9:16，共 {segments} 段 × {seconds:g} 秒 = {segments * seconds:g} 秒，关键帧 {segments + 1} 张。"""
    last_err = ""
    for _ in range(3):
        msgs = [{"role": "system", "content": SPEC.read_text(encoding="utf-8")}, {"role": "user", "content": user}]
        if last_err:
            msgs.append({"role": "user", "content": f"上一次的输出有问题：{last_err}。请修正后重新输出完整 JSON。"})
        text = llm.chat(msgs, json_mode=True, temperature=0.6, max_tokens=8000)
        try:
            plan = scriptmod._extract_json(text)
        except json.JSONDecodeError as e:
            last_err = f"JSON 格式错误：{e}"
            continue
        errs = _validate(plan, segments)
        if not errs:
            return plan
        last_err = "；".join(errs)
    raise RuntimeError(f"大模型出的方案不合格：{last_err}")


# ---------------- 口播带货（照参考作品：主播出镜 + 手持特写 + 粤语配音字幕） ----------------

PRESENTER_SPEC = Path(__file__).resolve().parent.parent / "skills" / "product_presenter.md"
SHOT_TYPES = ("presenter", "closeup")
# 这些动作/光效会让 H3 把手表画变形、表盘发白（实测穿帮），视频提示词里不允许出现
BANNED_MOTION = ("glint", "glare", "reflection", "sparkle", "catches the light", "flip", "turn over", "turns over",
                 "rotate the watch", "rotates the watch", "rotating the watch", "swap hands", "switches hands")


def _validate_presenter(plan: dict, shots: int) -> list[str]:
    errs = []
    ss = plan.get("shots") or []
    if not (max(5, shots - 1) <= len(ss) <= shots + 1):
        errs.append(f"镜头数应为 {shots} 个左右，实际 {len(ss)} 个")
    if ss and (ss[0].get("type") != "presenter" or ss[-1].get("type") != "presenter"):
        errs.append("第一个和最后一个镜头必须是 presenter（主播出镜）")
    total = 0
    for i, s in enumerate(ss, 1):
        t, ip, vp = s.get("type"), s.get("image_prompt", ""), s.get("video_prompt", "")
        lines = [str(x).strip() for x in (s.get("lines") or []) if str(x).strip()]
        if t not in SHOT_TYPES:
            errs.append(f"镜头 {i} 的 type 只能是 presenter 或 closeup")
        if "<image1>" not in ip:
            errs.append(f"镜头 {i} 的关键帧提示词没有用 <image1> 引用手表")
        if t == "presenter" and "<image2>" not in ip:
            errs.append(f"镜头 {i} 是主播出镜，关键帧提示词要用 <image2> 引用主播照片")
        if t == "closeup" and "<image2>" in ip:
            errs.append(f"镜头 {i} 是手持特写，不要引用 <image2>")
        if not lines:
            errs.append(f"镜头 {i} 没有配音文案")
        n = sum(len(x) for x in lines)
        total += n
        if n > 28:
            errs.append(f"镜头 {i} 的配音有 {n} 个字，太长（每个镜头最多 24 字左右），拆短或挪到别的镜头")
        if any(len(x) > 18 for x in lines):
            errs.append(f"镜头 {i} 有一句超过 16 个字，拆成两句")
        if "no background music" not in vp.lower():
            errs.append(f"镜头 {i} 的视频提示词缺少 No background music")
        low = vp.lower().replace("no strong glare", "")
        bad = [w for w in BANNED_MOTION if w in low]
        if bad:
            errs.append(f"镜头 {i} 的视频提示词有容易穿帮的词 {bad}：手表要基本不动，不要反光、翻转、转动")
        if not any(k in ip for k in ("真实尺寸", "40 毫米", "40毫米", "两指", "两根手指")):
            errs.append(f"镜头 {i} 的关键帧提示词没写手表的真实比例（约两指宽、比手掌小）")
        s["lines"] = lines
    if ss and not (50 <= total <= 170):
        errs.append(f"全片配音 {total} 个字，应在 70–140 字之间（约 20–35 秒）")
    return errs


def generate_presenter(brief: dict, caption: str) -> dict:
    """口播带货方案：镜头列表（每个镜头：类型、粤语配音、关键帧提示词、视频提示词）。"""
    c = config.load()["tvc"]["presenter"]
    shots = int(c["shots"])
    user = f"""## 用户填写（以此为准，和识别结果冲突时听用户的）
产品名称：{brief.get('product') or '（未填）'}
品牌：{brief.get('brand') or '（未填，看图认不准就不要说品牌）'}
卖点/信息（型号、年份、成色、配件、价格等，只有这里写了的才能说）：{brief.get('selling_points') or '（未填，只讲看图能确定的外观）'}
其他要求（场景、语气、结尾引导等）：{brief.get('notes') or '（无）'}

## 产品图视觉识别结果（Qwen3-VL，型号判断可能不准，仅作外观参考）
{caption}

## 规格
竖屏 9:16，{shots} 个镜头，全片配音约 20–35 秒。"""
    last_err = ""
    for _ in range(3):
        msgs = [{"role": "system", "content": PRESENTER_SPEC.read_text(encoding="utf-8")}, {"role": "user", "content": user}]
        if last_err:
            msgs.append({"role": "user", "content": f"上一次的输出有问题：{last_err}。请修正后重新输出完整 JSON。"})
        text = llm.chat(msgs, json_mode=True, temperature=0.7, max_tokens=8000)
        try:
            plan = scriptmod._extract_json(text)
        except json.JSONDecodeError as e:
            last_err = f"JSON 格式错误：{e}"
            continue
        errs = _validate_presenter(plan, shots)
        if not errs:
            for i, s in enumerate(plan["shots"], 1):
                s["id"] = i
            plan["style"] = "presenter"
            return plan
        last_err = "；".join(errs)
    raise RuntimeError(f"大模型出的方案不合格：{last_err}")
