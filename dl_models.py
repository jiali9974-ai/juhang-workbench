"""下载工作台需要的模型（HuggingFace，断点续传，失败自动重试）。只下运行必需的文件。"""
import time
from huggingface_hub import snapshot_download

REPOS = [
    ("FunAudioLLM/SenseVoiceSmall", "models/SenseVoiceSmall", ["*.pt", "*.yaml", "*.json", "*.mvn", "*.model", "*.py"]),
    ("funasr/fsmn-vad", "models/fsmn-vad", None),
]
for repo, d, patterns in REPOS:
    for attempt in range(10):
        try:
            snapshot_download(repo, local_dir=d, max_workers=4, etag_timeout=30, allow_patterns=patterns)
            print("DONE", repo, flush=True)
            break
        except Exception as e:
            print("RETRY", repo, attempt, repr(e)[:200], flush=True)
            time.sleep(5)
