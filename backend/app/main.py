"""FastAPI 入口：/api/inspect（解析声部列表）与 /api/transpose（生成移调分谱）。

生产环境下前端构建产物位于 /app/static，由本服务直接托管，实现单容器部署。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service
from .mx import ScoreError, ValidationError, RangeExceeded

MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
STATIC_DIR = Path(os.getenv("STATIC_DIR", "/app/static"))

app = FastAPI(title="移调分谱生成器", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ApiError(BaseModel):
    error: str
    code: str
    detail: dict | None = None


def _read_upload(upload: UploadFile) -> tuple[bytes, str]:
    data = upload.file.read()
    if not data:
        raise HTTPException(status_code=400, detail={"error": "上传文件为空。", "code": "empty_file"})
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=400, detail={"error": "文件超过 20MB 上限。", "code": "file_too_large"})
    return data, upload.filename or "score.musicxml"


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/inspect")
async def inspect(file: UploadFile = File(...)):
    data, filename = _read_upload(file)
    try:
        return service.inspect(data, filename)
    except ScoreError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc), "code": "score_error"})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "validation_error"})


@app.post("/api/transpose")
async def transpose(
    file: UploadFile = File(...),
    part_id: str = Form(...),
    src_diatonic: int = Form(...),
    src_chromatic: int = Form(...),
    dst_diatonic: int = Form(...),
    dst_chromatic: int = Form(...),
    range_low: str = Form(...),
    range_high: str = Form(...),
):
    data, filename = _read_upload(file)
    try:
        xml, download_name, meta = service.transpose(
            data, filename, part_id,
            src_diatonic, src_chromatic, dst_diatonic, dst_chromatic,
            range_low, range_high,
        )
    except RangeExceeded as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": "部分音符超出目标书写音域，未生成任何输出（不会擅自移动八度）。",
                "code": "range_exceeded",
                "detail": {"items": exc.items, "count": len(exc.items)},
            },
        )
    except ScoreError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc), "code": "score_error"})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "validation_error"})

    # JSON 信封：XML 以 base64 承载，前端可直接预览（OSMD）并触发下载，
    # 同时将结果存入浏览器本地存储，无需后端落盘。
    import base64
    return {
        "filename": download_name,
        "meta": meta,
        "musicxml_base64": base64.b64encode(xml).decode("ascii"),
    }


# ---------------------------------------------------------------- 前端静态资源
# 必须放在所有 /api 路由之后挂载，避免遮蔽 API。
if STATIC_DIR.is_dir():
    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        # 不拦截 API；其余路径找不到文件时回退到 index.html（SPA 习惯）
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
