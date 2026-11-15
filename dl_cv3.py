"""只下载 CosyVoice3 运行必需的文件，断点续传，最多重试 100 次。"""
import time
from huggingface_hub import snapshot_download

PATTERNS = ["cosyvoice3.yaml", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx", "speech_tokenizer_v3.onnx",
            "spk2info.pt", "configuration.json", "README.md", "CosyVoice-BlankEN/*", "asset/*"]
for attempt in range(100):
    try:
        snapshot_download("FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
                          local_dir="third_party/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B",
                          max_workers=4, etag_timeout=30, allow_patterns=PATTERNS)
        print("DONE cosyvoice3", flush=True)
        break
    except Exception as e:
        print("RETRY", attempt, repr(e)[:160], flush=True)
        time.sleep(5)
