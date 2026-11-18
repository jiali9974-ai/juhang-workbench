"""智能体用的大模型调用（OpenAI 兼容接口，默认走 GPT 中转站）。

- 临时错误（502/503/504/429/超时/断线）自动等待重试
- 自动适配参数：新版 GPT 用 max_completion_tokens；不支持 temperature 就去掉
- 主模型一直失败时，依次换 config 里的 fallback_models
"""
from __future__ import annotations

from . import cancellation, config

_TRANSIENT = ("502", "503", "504", "429", "timeout", "timed out", "temporarily", "overloaded",
              "connection", "upstream", "rate limit")


def _client():
    from openai import OpenAI

    cfg = config.load()["llm"]
    key = config.secret(cfg["api_key_env"])
    if not key:
        raise RuntimeError(f"没有设置大模型 API Key：在 secrets.yaml 里填 {cfg['api_key_env']}")
    return OpenAI(base_url=cfg["base_url"], api_key=key, timeout=float(cfg.get("timeout", 180)), max_retries=0)


def models() -> list[str]:
    cfg = config.load()["llm"]
    return [cfg["model"]] + [m for m in cfg.get("fallback_models", []) if m != cfg["model"]]


def chat(messages: list[dict], *, json_mode: bool = False, temperature: float | None = None,
         max_tokens: int | None = 8000, attempts_per_model: int = 4) -> str:
    """发一轮对话，返回模型回复的文字。"""
    client = _client()
    last = None
    for model in models():
        kw: dict = {} if max_tokens is None else {"max_completion_tokens": max_tokens}
        if temperature is not None:
            kw["temperature"] = temperature
        # 有的中转站（如 Codex 中转）不认 response_format，一带就 502；默认不带，靠提示词要求只输出 JSON
        if json_mode and config.load()["llm"].get("json_response_format", False):
            kw["response_format"] = {"type": "json_object"}
        for attempt in range(attempts_per_model):
            cancellation.check()
            try:
                r = client.chat.completions.create(model=model, messages=messages, **kw)
                cancellation.check()
                text = r.choices[0].message.content or ""
                if text.strip():
                    return text
                last = RuntimeError(f"{model} 返回了空内容")
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                low = msg.lower()
                last = e
                # 参数不被支持：调整后立刻重试，不算一次失败
                if "temperature" in low and ("unsupported" in low or "not support" in low or "only the default" in low):
                    kw.pop("temperature", None)
                    continue
                if "max_completion_tokens" in low and ("unsupported" in low or "unrecognized" in low or "not support" in low):
                    kw["max_tokens"] = kw.pop("max_completion_tokens")
                    continue
                if "response_format" in kw and ("response_format" in low or "502" in low):
                    kw.pop("response_format", None)   # 中转不支持 JSON 模式，去掉马上重试
                    continue
                if "model_not_found" in low or "does not exist" in low or "not supported" in low:
                    break                        # 这个模型用不了，直接换下一个
                if not any(t in low for t in _TRANSIENT):
                    raise                        # Key 错误、内容违规等，重试也没用
            cancellation.wait(min(30, 3 * (2 ** attempt)))   # 3、6、12、24 秒
    raise RuntimeError(f"大模型暂时连不上（已重试并换过备用模型）：{last}")
