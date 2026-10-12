# ════════════════════════════════════════════════════════════════
# MinerU 4.x CPU 版镜像（无需 NVIDIA / AMD GPU）
#
# 依据官方 4.0 说明：基础包小模型走 ONNX/CPU，VLM 走 llama.cpp，
# `basic` 档纯 CPU 可跑（约 0.8GB 模型、最低 2GB 内存）。
# 适用于 Windows(Docker Desktop)/Linux 等无可用 GPU 加速的环境。
#
# 构建（一般由 compose 自动调用，无需手动执行）:
#   docker build -t askflow/mineru-cpu:4 docker/mineru
# ════════════════════════════════════════════════════════════════
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # 模型源：modelscope（国内）/ huggingface（国际）/ local（仅用本地已下载模型）
    MINERU_MODEL_SOURCE=modelscope \
    MINERU_HOME=/root/.mineru

# 运行期系统依赖：OpenCV 运行库、ONNX/OpenMP、CJK 字体、健康检查用 curl
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        fonts-noto-cjk \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 MinerU 基础包（ONNX 小模型 + llama.cpp VLM，均可在 CPU 运行）
RUN pip install --upgrade pip && pip install "mineru>=4.0,<5"

# 可选：构建期预下载模型，运行时即无需联网（约 0.8GB，构建变慢）
# 取消下面两行注释即可启用，并按需把 --tier 换成 standard。
# RUN mineru-kit models download --tier basic && \
#     mineru-kit models verify --tier basic

EXPOSE 8000
ENTRYPOINT ["mineru-kit"]
# 默认以 basic 档启动（CPU 友好）；可被 compose 的 command 覆盖
CMD ["api-server", "--host", "0.0.0.0", "--port", "8000", "--tier", "basic"]
