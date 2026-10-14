#!/bin/sh
# clip-api 幂等启动入口：
#   - 模型已缓存（$HF_HOME/hub/models--<org>--<model> 存在）→ 设 HF_HUB_OFFLINE=1
#     完全离线启动：跳过向 HuggingFace Hub 的校验/下载（离线环境不再刷 "Network is unreachable"）；
#   - 未缓存 → 保持在线，联网下载一次（首次部署）。
# 之后每次启动都是"离线直读缓存"，无需人工改配置。
set -e

MODEL="${CLIP_MODEL:-OFA-Sys/chinese-clip-vit-base-patch16}"
MODEL_SLUG="$(echo "$MODEL" | sed 's#/#--#g')"
MODEL_DIR="${HF_HOME:-/data}/hub/models--${MODEL_SLUG}"

if [ -d "$MODEL_DIR" ]; then
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
  echo "[clip-api] 模型已缓存，离线启动: ${MODEL_DIR}"
else
  echo "[clip-api] 首次启动，联网下载模型: ${MODEL}"
fi

exec python -m uvicorn server:app --host 0.0.0.0 --port 80
