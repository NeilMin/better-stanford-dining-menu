"""Generate dish images through a local ComfyUI's HTTP API.

The server is treated as a long-lived shared resource: this module never starts
or stops it, and it renders through PreviewImage (ComfyUI's temp output) so a
bulk run leaves nothing behind in a ComfyUI install other projects also use.
"""

from __future__ import annotations

import io
import json
import logging
import time
import urllib.parse
import uuid

import requests
from PIL import Image

log = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:8189"

MODELS = {
    # RealVisXL V5.0: an SDXL photoreal finetune. Heavier step count but a much
    # smaller model than Flux, which is what makes it viable on Apple silicon.
    "sdxl": {
        "checkpoint": "realvisxlV50.safetensors",
        # 768px/20 steps renders ~3.5x faster than 1024/28 on Apple silicon with
        # no visible quality loss once the result is downscaled to a 640px card.
        "steps": 20,
        "cfg": 5.0,
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        # 1344x768 is an SDXL training bucket, and near enough to the 16:9 the
        # cards display that nothing meaningful is cropped away.
        "width": 1344,
        "height": 768,
        "negative": True,
    },
    # Flux.1-schnell, 4-step distilled. Follows long ingredient lists far more
    # closely; runs CFG 1.0, so it has no use for a negative prompt.
    "flux": {
        "unet": "flux1-schnell-Q8_0.gguf",
        "clip1": "clip_l.safetensors",
        "clip2": "t5xxl_fp8_e4m3fn.safetensors",
        "vae": "ae.safetensors",
        "steps": 4,
        "cfg": 1.0,
        "guidance": 3.5,
        "sampler": "euler",
        "scheduler": "simple",
        "width": 1344,
        "height": 768,
        "negative": False,
    },
}


class ComfyError(RuntimeError):
    pass


def build_workflow(model: str, positive: str, negative: str, seed: int,
                   size: tuple[int, int] | None = None, steps: int | None = None) -> dict:
    cfg = MODELS[model]
    width, height = size or (cfg["width"], cfg["height"])
    n_steps = steps or cfg["steps"]

    if model == "sdxl":
        return {
            "1": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": cfg["checkpoint"]}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
            "4": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": width, "height": height, "batch_size": 1}},
            "5": {"class_type": "KSampler",
                  "inputs": {"seed": seed, "steps": n_steps, "cfg": cfg["cfg"],
                             "sampler_name": cfg["sampler"], "scheduler": cfg["scheduler"],
                             "denoise": 1.0, "model": ["1", 0], "positive": ["2", 0],
                             "negative": ["3", 0], "latent_image": ["4", 0]}},
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "PreviewImage", "inputs": {"images": ["6", 0]}},
        }

    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": cfg["unet"]}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": cfg["clip1"], "clip_name2": cfg["clip2"], "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": cfg["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
        "5": {"class_type": "FluxGuidance",
              "inputs": {"conditioning": ["4", 0], "guidance": cfg["guidance"]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "7": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "8": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": n_steps, "cfg": cfg["cfg"],
                         "sampler_name": cfg["sampler"], "scheduler": cfg["scheduler"],
                         "denoise": 1.0, "model": ["1", 0], "positive": ["5", 0],
                         "negative": ["6", 0], "latent_image": ["7", 0]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "PreviewImage", "inputs": {"images": ["9", 0]}},
    }


class ComfyClient:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())
        self.session = requests.Session()

    def health(self) -> dict:
        r = self.session.get(f"{self.base_url}/system_stats", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def available(self) -> bool:
        try:
            self.health()
            return True
        except Exception:
            return False

    def validate(self, model: str) -> None:
        """Fail fast with a clear message if the server lacks the model or nodes."""
        r = self.session.get(f"{self.base_url}/object_info", timeout=60)
        r.raise_for_status()
        info = r.json()
        cfg = MODELS[model]

        needed = (["CheckpointLoaderSimple"] if model == "sdxl"
                  else ["UnetLoaderGGUF", "DualCLIPLoader", "VAELoader"])
        if missing := [n for n in needed if n not in info]:
            raise ComfyError(f"ComfyUI at {self.base_url} is missing nodes: {', '.join(missing)}")

        def options(node: str, field: str) -> list:
            return info[node]["input"]["required"][field][0]

        if model == "sdxl":
            if cfg["checkpoint"] not in options("CheckpointLoaderSimple", "ckpt_name"):
                raise ComfyError(f"checkpoint {cfg['checkpoint']} not found on the server")
        elif cfg["unet"] not in options("UnetLoaderGGUF", "unet_name"):
            raise ComfyError(f"unet {cfg['unet']} not found on the server")

        if cfg["sampler"] not in options("KSampler", "sampler_name"):
            raise ComfyError(f"sampler {cfg['sampler']} unavailable")

    def free(self, unload_models: bool = True) -> None:
        """Ask ComfyUI to drop cached models and release memory.

        Metal allocations are not reflected in RSS, and over a long batch this
        server accumulates several GB that macOS will eventually kill the run
        over. Freeing periodically costs one model reload and prevents that.
        """
        try:
            self.session.post(
                f"{self.base_url}/free",
                json={"unload_models": unload_models, "free_memory": True},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            log.warning("could not free ComfyUI memory: %s", exc)

    def submit(self, workflow: dict) -> str:
        r = self.session.post(
            f"{self.base_url}/prompt",
            json={"prompt": workflow, "client_id": self.client_id},
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise ComfyError(f"/prompt rejected the workflow: {r.status_code} {r.text[:400]}")
        return r.json()["prompt_id"]

    def wait(self, prompt_id: str, poll: float = 1.0, max_wait: float = 600) -> dict:
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            r = self.session.get(f"{self.base_url}/history/{prompt_id}", timeout=self.timeout)
            r.raise_for_status()
            entry = r.json().get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error" or status.get("completed") is False:
                    messages = status.get("messages", [])
                    raise ComfyError(f"generation failed: {json.dumps(messages)[:500]}")
                if entry.get("outputs"):
                    return entry["outputs"]
            time.sleep(poll)
        raise ComfyError(f"timed out after {max_wait}s waiting for {prompt_id}")

    def fetch_image(self, outputs: dict) -> Image.Image:
        for node in outputs.values():
            for ref in node.get("images", []):
                query = urllib.parse.urlencode({
                    "filename": ref["filename"],
                    "subfolder": ref.get("subfolder", ""),
                    "type": ref.get("type", "temp"),
                })
                r = self.session.get(f"{self.base_url}/view?{query}", timeout=60)
                r.raise_for_status()
                return Image.open(io.BytesIO(r.content)).convert("RGB")
        raise ComfyError("workflow produced no image")

    def generate(self, model: str, positive: str, negative: str, seed: int,
                 size: tuple[int, int] | None = None,
                 steps: int | None = None) -> tuple[Image.Image, float]:
        started = time.monotonic()
        workflow = build_workflow(model, positive, negative, seed, size, steps)
        outputs = self.wait(self.submit(workflow))
        return self.fetch_image(outputs), time.monotonic() - started


def to_webp(image: Image.Image, width: int = 1024, ratio: float = 16 / 9,
            quality: int = 80) -> bytes:
    """Crop to the card's aspect ratio and compress for the web."""
    w, h = image.size
    if abs(w / h - ratio) > 0.01:
        if w / h > ratio:                      # too wide: trim the sides
            new_w = round(h * ratio)
            left = (w - new_w) // 2
            image = image.crop((left, 0, left + new_w, h))
        else:                                  # too tall: trim top and bottom
            new_h = round(w / ratio)
            top = (h - new_h) // 2
            image = image.crop((0, top, w, top + new_h))
    if image.width != width:
        image = image.resize((width, round(width / ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()
