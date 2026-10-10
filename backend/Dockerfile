# ════════════════════════════════════════════════════════════════
# RAG Simple 后端镜像
# 构建上下文 = 项目根（docker-compose 中 context: ..）
# 布局与本地一致：
#   /workspace/backend/         后端代码（WORKDIR，= _project_root）
#   /workspace/frontend/dist/   前端构建产物（FastAPI 静态托管）
# ════════════════════════════════════════════════════════════════
FROM python:3.11-slim

# lxml 运行时依赖（readability-lxml）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/backend

# 先装 Python 依赖（利用镜像层缓存；用清华源加速）
COPY backend/pyproject.toml ./pyproject.toml
RUN pip install --no-cache-dir --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --no-cache-dir -e . -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制后端代码与前端构建产物
COPY backend/ /workspace/backend/
COPY frontend/dist /workspace/frontend/dist

EXPOSE 11000

# app.py 内 uvicorn 监听 0.0.0.0:11000
CMD ["python", "app.py"]
