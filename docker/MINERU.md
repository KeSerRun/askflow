# MinerU 本地化部署（纯 CPU，已并入 docker/docker-compose.yml）

用 Docker Compose 把 MinerU 4.x 的自托管文档解析服务跑在本机 / 内网，替代对
`https://mineru.net` 云 API 的依赖。**纯 CPU 运行，无需任何 GPU**，适用于
Windows(Docker Desktop) / Linux 等环境（含无 ROCm 支持的 AMD 显卡，如 RX 6700 XT
gfx1031）。

服务已并入主编排 `docker/docker-compose.yml`，`docker compose up -d` **默认即会启动**
（无需 profile）；与 backend 同处 `askflow` 网络，可被 `http://mineru-api:8000` 直接访问。

- API：`http://localhost:8000`（健康检查 `GET /v1/health`，接口文档 `/docs`）
- WebUI：`http://localhost:7860`（Gradio 上传界面）

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| `mineru-api` | `http://localhost:8000/v1/health` | 文档解析 API（默认启动） |
| `mineru-webui` | `http://localhost:7860` | WebUI，复用上面的 API（默认启动） |

---

## 1. 为什么是 CPU

- MinerU 4.0 **基础包天然支持 CPU**：布局/OCR/公式小模型走 ONNX/CPU，VLM 走
  llama.cpp，`basic` 档最低仅需 ~2GB 内存。
- **MinerU 官方 Docker 只支持 NVIDIA**；AMD 属于旧版（`mineru<4`）适配，且需要
  Linux + ROCm。
- **Docker Desktop for Windows 不支持把 AMD GPU 直通给容器**（只支持 N 卡）。
- RX 6700 XT 为 RDNA2（gfx1031），**不在 ROCm 官方支持列表**内。

综合下来，CPU 是最省事、最稳的路径。构建 CPU 镜像的 Dockerfile 见
`docker/mineru/Dockerfile`。

---

## 2. 前置条件

| 项 | 要求 |
| --- | --- |
| Docker | Docker Desktop（Windows 需 WSL2 后端）或 Linux 上的 Docker Engine，Compose v2 |
| 内存 | `basic` ≥ 2GB；`standard`（含 VLM）建议 ≥ 8GB，推荐 16GB |
| 磁盘 | 镜像 + 模型约 3–5GB（首次运行会下载模型到数据卷） |
| 网络 | 首次运行需能访问 ModelScope（默认）或 HuggingFace 下载模型 |

无需安装显卡驱动或 `nvidia-container-toolkit`。

---

## 3. 启动

镜像由 compose 自动构建（首次约数分钟）：

```bash
cd docker

# 默认全部启动（基础设施 + MinerU API + WebUI），首次会构建 CPU 镜像
docker compose up -d --build

# 若还要生产后端容器
docker compose --profile prod up -d --build

# 首次运行会下载模型，观察日志直到 health 通过
docker compose logs -f mineru-api
```

就绪判定：

```bash
curl http://localhost:8000/v1/health          # 返回 200 即正常
curl http://localhost:8000/v1/tiers           # 查看当前支持的解析档位
```

WebUI 打开 <http://localhost:7860>，上传 PDF 即可可视化核对解析质量。

> WebUI 已配置 `--api-url http://mineru-api:8000` **复用同一个解析服务**，不会另起
> 一个 api-server、也不会重复下载模型；它 `depends_on` 等待 API 健康后再启动。

> 端到端解析测试（CLI / API）见下方「7. 验证 MinerU 是否可用」。

---

## 4. 可配置项（环境变量）

在 `docker/` 下创建 `.env`（Docker Compose 会自动读取）覆盖默认值：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MINERU_IMAGE` | `askflow/mineru-cpu:4` | 镜像名 |
| `MINERU_API_PORT` | `8000` | 宿主 API 端口 |
| `MINERU_WEBUI_PORT` | `7860` | 宿主 WebUI 端口 |
| `MINERU_TIER` | `basic` | CPU 档位：`basic`（快）/ `standard`（加 VLM，质量更高但慢） |
| `MINERU_MODEL_SOURCE` | `modelscope` | 模型源：`modelscope`（国内）/ `huggingface`（国际）/ `local`（仅用已下载模型） |
| `MINERU_API_KEY` | 空 | 启用 API 鉴权时使用（见 compose 注释） |

**CPU 档位选择**：

| 档位 | 引擎 | 模型 | 内存 | 说明 |
| --- | --- | --- | --- | --- |
| `basic` | ONNX / CPU | ~0.8GB | ≥2GB | 只跑小模型（OCR/公式/表格），快，推荐默认 |
| `standard` | ONNX + llama.cpp | ~2GB | ≥8GB | 额外用 VLM 处理复杂版面，质量更高但 CPU 上明显更慢 |

想提升质量可把 `MINERU_TIER=standard`；嫌慢就留在 `basic`。
若只想解析 Office/HTML/CSV 等原生格式，走 `flash` 档（无需模型，最快）。

### 模型下载与持久化

模型缓存在 `MINERU_HOME`（compose 已挂载到 `docker/data/mineru-home`），重启不丢。
默认首次调用时按需下载；若想构建期就预置好、运行时完全离线，取消
`docker/mineru/Dockerfile` 中 `mineru-kit models download` 两行的注释后重新构建。

---

## 5. 与 AskFlow 对接（已实现）

AskFlow 的本地 MinerU 适配器已就绪：`backend/infra/adapters/pdf/mineru_impl.py`
现在直接走 **MinerU 4.0 本地 V1 协议**（单文件：创建上传 `POST /v1/uploads` →
传字节 → `complete` → 提交 `POST /v1/parse/jobs`（tier=basic, 单文件）→ 轮询 →
下载 markdown / middle_json），云端 v4 的 `file-urls/batch` 批量链路已全部移除。

对接配置（`backend/.env`）：

1. 启动本地 MinerU（`docker compose up -d`，默认已包含 API + WebUI）；
2. 后端本机运行：
   - `MINERU_BASE_URL=http://127.0.0.1:8000`
   - `MINERU_API_KEY=sk-local`（本地无鉴权；服务端启用 `--api-key` 时填同一个 Key）
   - `MINERU_TIER=basic`（CPU 档位；质量要求高改 `standard`）
3. 后端为容器（同网络）：compose 已让 backend 走服务名，或用
   `MINERU_BASE_URL=http://mineru-api:8000`。

产物解析：本地 4.0 middle_json（`pages.blocks`）→ 新的 `chunk_pages` 标准化分块；
缺失时回退 Markdown 分段；旧版 `content_list.json` 仍兼容。

---

## 6. 常见问题

- **health 一直不通过 / 首次很慢**：首次启动会下载模型（~0.8GB）；`docker compose logs -f mineru-api` 观察进度。
- **内存不足**：`basic` 只需 ~2GB；用 `standard` 建议 ≥8GB。可临时降回 `basic`。
- **下载模型失败**：确认容器可访问外网；国内默认 `modelscope`，若网络受限可试 `huggingface`，或改用镜像内预置（见第 4 节）。
- **解析很慢**：CPU 正常现象。优先用 `basic`；只解析原生文档可传 `tier=flash`。
- **端口被占用**：用 `MINERU_API_PORT` / `MINERU_WEBUI_PORT` 覆盖，并同步调整 `MINERU_BASE_URL`。
- **Windows 下 I/O 慢**：把项目放在 WSL2 文件系统内（而非 `/mnt/c/...`）可显著提速。
- **只想跑基础设施**：MinerU 现默认启动；如需临时排除可 `docker compose up -d --scale mineru-api=0 --scale mineru-webui=0`，或注释掉这两个服务。

---

## 7. 验证 MinerU 是否可用

> 前提：**Docker Desktop 已启动**。以下命令在 `docker/` 目录下执行。

### 7.1 容器与健康检查

```powershell
cd docker
docker compose up -d --build          # 默认即包含 MinerU
docker compose ps                     # 等 mineru-api 的 STATUS 变为 healthy
docker compose logs --tail=50 mineru-api

# 存活探测（PowerShell 用 curl.exe，避免被别名成 Invoke-WebRequest）
curl.exe http://localhost:8000/v1/health
curl.exe http://localhost:8000/v1/tiers
```

- `/v1/health` 返回 JSON（含 `features`）即服务正常。
- `/v1/tiers` 应包含 `flash`、`basic`（因为默认以 `--tier basic` 启动）。

### 7.2 模型是否就绪

```powershell
docker compose exec mineru-api mineru-kit models download --tier basic
docker compose exec mineru-api mineru-kit models verify --tier basic
```

首次会下载约 0.8GB 模型到数据卷（`docker/data/mineru-home`），之后复用。

### 7.3 端到端解析（最直接）

随便找一个 PDF，放到数据卷目录，然后在容器内解析：

```powershell
# 把测试 PDF 放进被挂载的数据卷
Copy-Item C:\path\to\test.pdf docker\data\mineru-home\test.pdf

# 容器内解析（输出会写回宿主同一目录）
docker compose exec mineru-api `
  mineru-kit parse /root/.mineru/test.pdf -o /root/.mineru/test.md --tier basic

# 查看结果
Get-Content docker\data\mineru-home\test.md
```

`test.md` 有内容 = 解析成功。

### 7.4 走 V1 API（对齐后端对接路径）

用镜像内自带的 Python SDK 从 API 拉一次结果（HTTP 200 不代表成功，SDK 会做
上传→任务→轮询→下载的完整闭环）：

```powershell
docker cp C:\path\to\test.pdf askflow-mineru-api:/tmp/test.pdf
docker exec askflow-mineru-api python -c "from mineru.parser import MinerUApiParser; p = MinerUApiParser(api_url='http://127.0.0.1:8000', tier='basic'); r = p.parse('/tmp/test.pdf'); print(r.markdown()[:800])"
```

能打印出 Markdown 片段 = API 链路正常（这也是后端「本地适配器」将采用的调用方式）。

> 官方还提供经过测试的 HTTP 闭环脚本
> `scripts/http_api_example.sh`（见仓库），可用 curl 校验原始请求周期。

### 7.5 网页验证

WebUI 已随 `docker compose up -d` 启动：打开 <http://localhost:7860>，上传 PDF，看右侧
Markdown 输出。

### 7.6 结果判读速查

| 现象 | 含义 |
| --- | --- |
| `ps` 长时间 `starting`/`unhealthy` | 首次下载模型，或内存不足；看 `logs` |
| `/v1/health` 连不上 | 端口未映射 / 容器未起；确认 Docker 引擎在运行 |
| `parse` 报模型缺失 | 执行 7.2 的 download/verify |
| 解析很慢 | CPU 正常现象；用 `basic`，原生文档可传 `tier=flash` |

---

## 8. 附：有 GPU 时（非 CPU 场景）

若之后换到受支持的硬件，可改用 GPU 加速（需相应修改 compose：NVIDIA 用
`deploy.resources.reservations.devices`，AMD 用 `devices: [/dev/kfd, /dev/dri]`）：

- **NVIDIA**：用官方 4.0 Dockerfile（`docker/china/Dockerfile` / `docker/global/Dockerfile`）构建 `mineru:4`，运行 `mineru-kit api-server`，GPU 预留。≥8GB 显存可上 `standard`。
- **AMD（RX 7000/MI 等受支持型号）**：仅 Linux + ROCm，且 MinerU 需 **3.x（`mineru<4`）**；compose 用 `devices` 直通 `/dev/kfd`、`/dev/dri`（`driver: nvidia` 不适用），可能需 `HSA_OVERRIDE_GFX_VERSION`。
- 官方文档：<https://opendatalab.github.io/MinerU/quick_start/docker_deployment/>；旧平台：<https://opendatalab.github.io/MinerU/usage/compatibility/>
