# DSH Local GPU

Optional MIT plugin for the public [dsh-image-gen](https://github.com/shanliuling/dsh-image-gen) ComfyUI provider. It runs FLUX.2 klein 4B FP8 image generation/editing in a separate GPU-only ComfyUI process per job. Gemma is released before an image job and automatically reloads on the next Ollama request. The image process exits before its completed history is returned, so its weights do not remain on GPU or in an inference RAM offload cache.

The lightweight loopback bridge is 8188; its private inference child uses 8189 temporarily. DSH still uses its normal 3080. No official package, launcher or ComfyUI source is modified. The bridge refuses during active classroom jobs and does not unload unrelated Ollama models. Other programs can still consume GPU memory; available-memory checks cannot guarantee a machine-wide cap.

## Setup

Install official ComfyUI v0.39.0 in `~/.local-ai-tools/comfyui/ComfyUI-0.39.0`, with Python 3.12 in `~/.local-ai-tools/comfyui/venv`. Install its requirements and GPU PyTorch. Download upstream weights separately:

- BFL `FLUX.2-klein-4b-fp8`, revision `5b4408e59397a4a37ccb46afe426d8ed86379441`: `flux-2-klein-4b-fp8.safetensors` to `models/diffusion_models`.
- Comfy-Org `flux2-klein-4B`, revision `5f526678002e43af5551dadb73ce2e8c91b43afe`: `qwen_3_4b.safetensors` to `models/text_encoders`, and `flux2-vae.safetensors` to `models/vae`.

Add a fixed GitHub source archive through `dsh plugin --profile web add <archive-url>`. Configure dsh-image-gen provider `comfyui`, base URL `http://127.0.0.1:8188`, and import the API JSON workflows in `workflows/`. It supports one image, four distilled steps and 256–1024 pixel dimensions. Use `local_image_runtime start/status` to inspect or retry the lightweight runtime. Missing runtime/occupied ports return errors without preventing DSH startup.

Reference uploads and generated images stay in `~/.local-ai-tools/local-images`; deleting the plugin does not delete outputs. Dependencies/models retain upstream licenses. A 16 GB GPU is the target, but only measured resolutions are verified; inference never silently falls back to CPU/RAM. Parallel classroom processing and image generation are intentionally refused.
