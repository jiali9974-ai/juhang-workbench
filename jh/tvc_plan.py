"""产品贴字 TVC 方案：把视觉识别结果 + 用户需求交给大模型，按 skills/product_tvc.md 输出结构化方案。"""
from __future__ import annotations

import json
from pathlib import Path

from . import config, script as scriptmod

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
    client, model = scriptmod._client()
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
        resp = client.chat.completions.create(model=model, temperature=0.6, max_tokens=8000,
                                              response_format={"type": "json_object"}, messages=msgs)
        try:
            plan = scriptmod._extract_json(resp.choices[0].message.content)
        except json.JSONDecodeError as e:
            last_err = f"JSON 格式错误：{e}"
            continue
        errs = _validate(plan, segments)
        if not errs:
            return plan
        last_err = "；".join(errs)
    raise RuntimeError(f"大模型出的方案不合格：{last_err}")
