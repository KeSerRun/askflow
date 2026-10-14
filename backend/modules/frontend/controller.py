"""modules.frontend.controller —— 前端托管：首页 HTML 与静态资源挂载。

前端由本后端托管（`frontend/dist`）：`GET /` 返回 index.html；`/assets` 与根路径
挂载构建产物。不属于业务域，故独立成模块，入口只需 `include_router` + `mount_static`。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import conf
from infra.util.logger import logger

router = APIRouter(tags=["frontend"])

_DIST = conf.web_dist_dir
_ASSETS = conf.web_assets_dir
_INDEX = conf.web_index_file


def _load_index() -> str | None:
    """读取前端首页 HTML；未构建返回 None（每次请求实时读，构建后无需重启）。"""
    if os.path.exists(_INDEX):
        with open(_INDEX, encoding="utf-8") as f:
            return f.read()
    return None


@router.get("/")
def index():
    """返回前端首页 HTML。

    Raises:
        HTTPException 404: 前端未构建。
    """
    html = _load_index()
    if html is None:
        raise HTTPException(status_code=404, detail="frontend not built; run `cd frontend && npm run build`")
    return HTMLResponse(content=html, status_code=200)


def mount_static(app) -> None:
    """挂载 `/assets` 与前端根目录（仅当前端已构建）。"""
    if _load_index() is None:
        return
    if os.path.isdir(_ASSETS):
        app.mount("/assets", StaticFiles(directory=_ASSETS), name="assets")
        app.mount("/", StaticFiles(directory=_DIST, html=False), name="frontend_root")
        logger.debug(f"已挂载前端构建产物: {_DIST}")
    else:
        logger.warning(
            f"未找到前端构建产物 {_DIST} 下的 assets 目录,静态资源将不可用。"
            "运行 `cd frontend && npm run build` 后重启即可启用。"
        )
