# clip-api —— Chinese-CLIP 图文嵌入服务（CPU）
# 文本 + 图片同一向量空间（默认 512 维），OpenAI 兼容。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/data

WORKDIR /app

# CPU 版 PyTorch（避免拉 GPU 依赖）
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir \
        fastapi uvicorn pillow \
        "sentence-transformers>=2.7" \
        "transformers>=4.38"

COPY server.py /app/server.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 80

# 幂等启动：已缓存则离线，未缓存则联网下载一次（见 entrypoint.sh）
CMD ["sh", "/app/entrypoint.sh"]