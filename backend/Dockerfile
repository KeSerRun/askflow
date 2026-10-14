# ════════════════════════════════════════════════════════════════
# RAG Simple 后端镜像
# 构建上下文 = 项目根（docker-compose 中 context: ..）
# 布局与本地一致：
#   /workspace/backend/         后端代码（WORKDIR，= _project_root）
#   /workspace/frontend/dist/   前端构建产物（FastAPI 静态托管）
#
# ⚠️ 前置要求：先在宿主执行 `cd frontend && npm run build` 生成 frontend/dist，
#    再构建镜像（下面 COPY 依赖它）。前端更新后需重新 build + 重打镜像。
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

# 生产配置：把 .env.prod 作为镜像内的 .env（容器读取它；后台“系统设置”保存也写它）。
# 需保证构建上下文存在 backend/.env.prod（生产部署前从 .env.prod 维护）。
COPY backend/.env.prod /workspace/backend/.env

EXPOSE 11000

# app.py 内 uvicorn 监听 0.0.0.0:11000
CMD ["python", "app.py"]
