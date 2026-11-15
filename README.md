# 巨航剪辑工作台

把门店口播原始素材自动剪成参考风格的抖音竖屏短视频（1440×2560 / 60fps）：
粤语字幕、左上角「先鉴定后入手 / 只做正品」、底部免责声明、特写自动放大；
素材里有普通话时，用 CosyVoice3 换成粤语配音。

## 使用

1. 第一次用：复制 `secrets.example.yaml` 为 `secrets.yaml`，填大模型 API Key（默认走 GPT 中转站，地址和模型在 `config.yaml` 的 `llm`）。
2. 双击 `start.bat`，浏览器打开 http://127.0.0.1:8765
3. 左边选拍摄批次（素材目录下按日期分的文件夹）→「一键识别并出脚本」。
4. 脚本出来后逐条「审核」：改字幕、删句子、调顺序、试听配音、选配音模式 →「确认并出片」。
5. 成片在 `data/outputs/<批次>/`，网页里也能直接播放和下载。

## 流程

| 步骤 | 模块 | 说明 |
|---|---|---|
| 识别 | `jh/asr.py` | VAD 切段 + SenseVoice，标出每句是粤语还是普通话，带逐字时间戳 |
| 出脚本 | `jh/script.py` + `jh/llm.py` | 大模型（GPT）按「开头钩子 → 逐只表讲解 → 结尾引导」选句，写粤语口语字幕 |
| 审核 | `web/index.html` | 人工确认，未确认的脚本不会出片 |
| 配音 | `jh/tts.py` | `config.yaml` 里 `tts.engine` 切换 cosyvoice3 / azure |
| 出片 | `jh/render.py` | 逐段裁切放大 → 拼接 → 烧字幕角标 → 响度统一 → 背景音乐闪避 |

配音模式（每条脚本单独选）：
- **自动**：素材全是粤语就保留原声；只要有一句普通话，整条都用配音，保证同一个声音。
- **保留原声** / **全部用粤语配音**：手动指定。

## 粤语配音引擎

| 引擎 | 说明 |
|---|---|
| **Ming-3.0（默认）** | inclusionAI 官方 Ming-3.0-tts-0.5B（GGUF，SHA256 已和 HuggingFace 官方核对）+ audio.cpp 官方 Windows CUDA 版引擎。工作台需要配音时自动在后台启动，闲置 10 分钟释放显存，工作台关闭时一起退出。约占 2–3GB 显存 |
| CosyVoice3 | 本地模型，需要一段参考音频定音色 |
| Azure 粤语 | 微软官方付费服务，需要在 secrets.yaml 填 Key |

审核页「配音」选「全部配音」或「自动」（有普通话时）后，可以按条选引擎；默认引擎在 `config.yaml` 的 `tts.engine`。
Ming 用固定种子先生成一段粤语音色样本，之后每句都参考它，整条视频同一个声音；想用自己录的声音，填 `tts.ming.ref_wav`。
型号数字会自动逐位读（126334 → 一二六三三四），表径等小数字读中文（41 → 四十一）。

## 一键直接出片

批次页「一键直接出片」：识别 → 大模型出脚本 → 全部出片，中间不停下来审核。出完的片子仍然可以进「审核」改字幕、删句后重新出片。

## 产品图生视频（AutoDL 云端）

侧边栏「产品图生视频」：上传一张产品图 + 填产品名（品牌、卖点选填）→ 出 15 秒竖屏 3D 空间贴字广告。

| 步骤 | 在哪跑 | 说明 |
|---|---|---|
| 识别产品 | 云端 Qwen3-VL 8B | 看图写材质、颜色、结构、可见文字（型号可能认错，以你填的产品名为准） |
| 写方案 | GPT（中转站） | 按 `skills/product_tvc.md`（由 typography-product-tvc 改写）输出 4 张关键帧提示词 + 3 段 H3 视频提示词 |
| 出分镜 | 云端 Qwen-Image 2.1 | 每张都参考产品原图，9:16，约 10–17 秒一张 |
| 出视频段 | 云端 MiniMax H3（fl2va_pruned_int8 + 8 步加速） | 第 k 段 = 关键帧 k → k+1，5 秒，自带音效，约 2–3 分钟一段 |
| 合成 | 本机 ffmpeg | 去掉段间重复帧，拼接为 1080×1920 / 24fps；配置了 `tvc.bgm_file` 就混背景音乐 |

- 两个按钮：「生成分镜（先审核）」出完关键帧停下，可改提示词、单张重画，确认后再生成视频；「一键直接出片」全自动。
- 任何一张关键帧或一段视频都能单独重做，改过的会自动标记"需重做"。
- 连接：本机用专用 SSH 密钥（`~/.ssh/jh_autodl`，ssh 配置别名 `jh-autodl`）自动建隧道到云端 ComfyUI，不需要密码。
  AutoDL 实例重开后 SSH 端口会变，改 `~/.ssh/config` 里 `Host jh-autodl` 的 `Port`。
- 项目文件在 `data/tvc/<项目号>/`：产品图、方案 `project.json`、关键帧、视频段、成片。

## 智能体（大模型）

写剪辑脚本和产品广告方案都走 `jh/llm.py`：OpenAI 兼容接口，默认 GPT 中转站（`config.yaml` → `llm`）。
- 主模型 `gpt-6.1-sol`，失败时依次换 `fallback_models`（gpt-6、gpt-5.6）；502/429/超时自动重试。
- 这个中转站不支持 `response_format` 参数（带了会 502），所以 `json_response_format: false`，靠提示词要求只输出 JSON。
- 换回 DeepSeek：`base_url` 改 `https://api.deepseek.com`，`model` 改 `deepseek-chat`，`api_key_env` 改 `JH_DEEPSEEK_API_KEY`。

## 配置

都在 `config.yaml`：素材路径、字幕字号位置、角标文字、放大倍数、背景音乐、配音音色等。
配音音色换成自己录的：把 5–10 秒干净的粤语录音放进来，改 `tts.cosyvoice3.prompt_wav`。

## 前端

React + Vite + Tailwind + shadcn/ui（Radix 版，和 21st.dev 的组件兼容），源码在 `frontend/`。
`start.bat` 用的是打包好的 `frontend/dist`，改了前端要重新打包：

```
cd frontend
npm run build      # 打包，工作台刷新即可看到
npm run dev        # 开发模式，http://localhost:5173，接口自动转发到 8765
```

加 21st 组件：在 21st.dev 登录后点组件的「Copy prompt」，把提示词交给 Claude Code 装进 `frontend/`。

## 目录

```
config.yaml        配置
secrets.yaml       API Key（只放本机）
app.py             工作台服务
jh/                识别、脚本、配音、渲染
frontend/          工作台页面（React + shadcn/ui）
web/               旧版单文件页面（没打包前端时的备用）
fonts/             思源黑体 Heavy（SIL OFL，可商用）
models/            识别模型、Ming 模型（models/ming）
engines/           audio.cpp 官方引擎（Ming 用）
third_party/       CosyVoice 代码和模型
data/              识别结果、脚本、配音缓存、成片
```
