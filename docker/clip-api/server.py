"""clip-api —— 图文嵌入服务（Chinese-CLIP，文本 + 图片同一向量空间）。

OpenAI 兼容端点 + 图片嵌入端点：
  - GET  /health                          → {status, model, dim}
  - POST /v1/embeddings                   → OpenAI 风格 {data:[{embedding}]}（文本）
  - POST /v1/image_embeddings             → {data:[{embedding}]}（body: {images:[base64,...]})

模型：CLIP_MODEL（默认 OFA-Sys/chinese-clip-vit-base-patch16，512 维）。
直接用 transformers 的 ChineseCLIPModel（get_text_features / get_image_features），
输出 L2 归一化，文本与图片共享同一向量空间。
"""

from __future__ import annotations

import base64
import io
import os
import threading

from PIL import Image

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

MODEL_NAME = os.environ.get("CLIP_MODEL", "OFA-Sys/chinese-clip-vit-base-patch16")

app = FastAPI(title="clip-api", version="1.1")

_model = None
_processor = None
_lock = threading.Lock()


def _ensure():
    """懒加载模型与处理器（进程内单例）。"""
    global _model, _processor
    if _model is None:
        with _lock:
            if _model is None:
                from transformers import ChineseCLIPModel, ChineseCLIPProcessor
                _model = ChineseCLIPModel.from_pretrained(MODEL_NAME)
                _processor = ChineseCLIPProcessor.from_pretrained(MODEL_NAME)
                _model.eval()
    return _model, _processor


def _l2(vec):
    import math
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _run_text(model, processor, texts):
    """Chinese-CLIP 文本向量（CLS + text_projection，官方一致口径）。

    统一 pad/截断到 512，规避长序列时文本模型内部 size 不匹配。
    """
    import torch
    with torch.no_grad():
        inputs = processor(
            text=texts, padding="max_length", max_length=512, truncation=True,
            return_tensors="pt",
        )
        out = model.text_model(**inputs)
        cls = out.last_hidden_state[:, 0, :]
        proj = getattr(model, "text_projection", None)
        feats = proj(cls) if proj is not None else cls
        return [_l2([float(x) for x in v]) for v in feats.tolist()]


def _run_image(model, processor, images):
    """Chinese-CLIP 图片向量（CLS + visual_projection，官方一致口径）。"""
    import torch
    with torch.no_grad():
        pix = processor(images=images, return_tensors="pt")
        out = model.vision_model(pixel_values=pix["pixel_values"])
        cls = out.last_hidden_state[:, 0, :]
        proj = getattr(model, "visual_projection", None)
        feats = proj(cls) if proj is not None else cls
        return [_l2([float(x) for x in v]) for v in feats.tolist()]


class EmbedBody(BaseModel):
    input: list[str] | str


class ImageEmbedBody(BaseModel):
    images: list[str]  # base64（可带 data: 前缀）


# 是否预热：默认关（CLIP_WARMUP=0）。开启则**后台线程**预热，不阻塞启动。
_WARMUP = os.environ.get("CLIP_WARMUP", "0").strip().lower() not in ("0", "false", "no", "off")


def _do_warmup() -> None:
    try:
        model, processor = _ensure()
        _run_text(model, processor, ["预热"])
        _run_image(model, processor, [Image.new("RGB", (1, 1), (0, 0, 0))])
        print("[clip-api] 预热完成（模型已加载）", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[clip-api] 预热失败（忽略，首次请求会重试）: {e}", flush=True)


@app.on_event("startup")
def _on_startup():
    if not _WARMUP:
        print("[clip-api] CLIP_WARMUP=0，跳过预热（模型在首次请求时懒加载）", flush=True)
        return
    # 后台线程预热：启动/健康检查不被模型加载阻塞
    threading.Thread(target=_do_warmup, daemon=True).start()


@app.get("/health")
def health():
    # 轻量探活：不触发模型加载（避免把重加载算进启动/就绪耗时）
    return {"status": "ok", "model": MODEL_NAME, "dim": 512, "loaded": _model is not None}


@app.post("/v1/embeddings")
def embeddings(body: EmbedBody):
    model, processor = _ensure()
    texts = body.input if isinstance(body.input, list) else [body.input]
    if not texts:
        raise HTTPException(status_code=400, detail="input 为空")
    try:
        vecs = _run_text(model, processor, texts)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"文本编码失败: {e}")
    return {"object": "list", "data": [{"embedding": v} for v in vecs], "model": MODEL_NAME}


@app.post("/v1/image_embeddings")
def image_embeddings(body: ImageEmbedBody):
    model, processor = _ensure()
    if not body.images:
        raise HTTPException(status_code=400, detail="images 为空")
    images = []
    try:
        for raw in body.images:
            if isinstance(raw, str) and raw.startswith("data:"):
                raw = raw.split(",", 1)[1]
            images.append(Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"图片解码失败: {e}")
    try:
        vecs = _run_image(model, processor, images)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"图片编码失败: {e}")
    return {"object": "list", "data": [{"embedding": v} for v in vecs], "model": MODEL_NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "80")))