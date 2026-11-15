"""用自托管 ComfyUI 运行 MiniMax H3 首帧图生视频。"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests

SIZE = (576, 1024)
FPS = 24
UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VAES = ("minimax_h3_video_vae_int8_convrot.safetensors", "minimax_h3_video_vae_fp16.safetensors")
LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"


class ComfyRequestError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def workflow(image: str, prompt: str, prefix: str, seconds: float, seed: int,
             vae: str = VAES[0], turbo: bool = False, lock_view: bool = False) -> dict:
    length = 5 + 17 * math.ceil((max(5, seconds) * FPS - 5) / 17)
    graph = {}

    def add(name: str, **inputs: Any) -> list:
        node_id = str(len(graph) + 1)
        graph[node_id] = {"class_type": name, "inputs": inputs}
        return [node_id, 0]

    frame = add("LoadImage", image=image)
    model = add("UNETLoader", unet_name=UNET, weight_dtype="default")
    if turbo:
        model = add("LoraLoaderModelOnly", model=model, lora_name=LORA, strength_model=1.0)
    clip = add("CLIPLoader", clip_name=CLIP, type="minimax", device="default")
    video_vae = add("VAELoader", vae_name=vae)
    last_frame = {"last_frame": frame} if lock_view else {}
    positive = add("MiniMaxH3ImageToVideo", first_frame=frame, prompt=prompt, clip=clip,
                   vae=video_vae, width=SIZE[0], height=SIZE[1], length=length, **last_frame)
    noise = add("RandomNoise", noise_seed=seed)
    guider = add("BasicGuider", model=model, conditioning=positive)
    sampler = add("KSamplerSelect", sampler_name="res_multistep")
    sigmas = add("BasicScheduler", model=model, scheduler="simple", steps=8 if turbo else 20, denoise=1.0)
    latent = add("SamplerCustomAdvanced", noise=noise, guider=guider, sampler=sampler,
                 sigmas=sigmas, latent_image=[positive[0], 1])
    frames = add("VAEDecode", samples=latent, vae=video_vae)
    video = add("CreateVideo", images=frames, fps=FPS)
    add("SaveVideo", video=video, filename_prefix=prefix, format="mp4", codec="h264")
    return graph


class ComfyH3:
    def __init__(self, url: str):
        address = urlsplit(url)
        if address.scheme not in {"http", "https"} or not address.hostname or address.username:
            raise ValueError("ComfyUI 地址应是 HTTP(S) 服务地址，例如 http://127.0.0.1:18188")
        self.url = url.rstrip("/")

    def _request(self, method: str, route: str, **kwargs):
        response = requests.request(method, self.url + route, timeout=(10, 60), **kwargs)
        if not response.ok:
            body = response.text[:700]
            response.close()
            raise ComfyRequestError(response.status_code, f"ComfyUI {route} 返回 HTTP {response.status_code}：{body}")
        return response

    def preflight(self, turbo: bool) -> str:
        graph = workflow("probe.png", "probe", "probe", 5, 1, turbo=turbo)
        with self._request("GET", "/object_info") as response:
            nodes = response.json()
        missing = sorted({node["class_type"] for node in graph.values()} - nodes.keys())
        if missing:
            raise RuntimeError(f"云端 ComfyUI 缺少原生节点：{', '.join(missing)}")

        def choices(node: str, field: str) -> list:
            inputs = nodes[node]["input"]
            spec = {**inputs.get("required", {}), **inputs.get("optional", {})}.get(field, [])
            if spec and isinstance(spec[0], list):
                return spec[0]
            if len(spec) > 1:
                return spec[1].get("options", [])
            return []

        required = [("UNETLoader", "unet_name", UNET), ("CLIPLoader", "clip_name", CLIP)]
        if turbo:
            required.append(("LoraLoaderModelOnly", "lora_name", LORA))
        absent = [filename for loader, field, filename in required if filename not in choices(loader, field)]
        available_vaes = choices("VAELoader", "vae_name")
        vae = next((filename for filename in VAES if filename in available_vaes), None)
        if vae is None:
            absent.append(" 或 ".join(VAES))
        if absent:
            raise RuntimeError("云端 H3 模型文件未就绪：" + "；".join(absent))
        return vae

    def upload(self, image: Path, folder: str) -> str:
        with image.open("rb") as handle:
            with self._request("POST", "/upload/image", data={"subfolder": folder},
                               files={"image": (image.name, handle, "image/png")}) as response:
                saved = response.json()
        return "/".join(filter(None, (saved.get("subfolder"), saved["name"])))

    def submit(self, graph: dict) -> str:
        with self._request("POST", "/prompt", json={"prompt": graph}) as response:
            return response.json()["prompt_id"]

    def wait(self, task_id: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        print(f"等待 ComfyUI 任务 {task_id}", flush=True)
        while time.monotonic() < deadline:
            with self._request("GET", f"/history/{quote(task_id, safe='')}") as response:
                entry = response.json().get(task_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    errors = [data.get("exception_message", "") for event, data in status.get("messages", [])
                              if event == "execution_error"]
                    raise RuntimeError(f"H3 任务 {task_id} 失败：{'；'.join(errors) or '请查看云端日志'}")
                for output in entry.get("outputs", {}).values():
                    for files in output.values():
                        if isinstance(files, list):
                            for file in files:
                                if isinstance(file, dict) and file.get("filename", "").lower().endswith(".mp4"):
                                    return file
                if status.get("completed"):
                    raise RuntimeError(f"H3 任务 {task_id} 已结束，ComfyUI 没有返回 MP4")
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        raise TimeoutError(f"H3 任务 {task_id} 仍在等待，重新运行可继续查询")

    def download(self, file: dict, target: Path) -> None:
        query = {key: file[key] for key in ("filename", "subfolder", "type") if key in file}
        with self._request("GET", "/view", params=query, stream=True) as response:
            with target.open("wb") as handle:
                for block in response.iter_content(chunk_size=1024 * 1024):
                    handle.write(block)
