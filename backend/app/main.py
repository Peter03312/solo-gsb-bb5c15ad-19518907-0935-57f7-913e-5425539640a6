"""FastAPI application: upload / analyze / transpose / download."""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import storage
from .musicxml import analyze_parts, parse_score
from .theory import MusicTheoryError
from .transposer import (
    OutOfRangeError,
    TransposeParams,
    build_transposed_score,
    serialize,
)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_storage()
    yield


app = FastAPI(title="移调分谱生成器", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _reject(code: str, message: str, status: int = 422, **extra) -> HTTPException:
    detail = {"code": code, "message": message}
    detail.update(extra)
    return HTTPException(status_code=status, detail=detail)


def _load_tree(file_id: str):
    try:
        data = storage.load_source(file_id)
    except FileNotFoundError:
        raise _reject("not_found", "上传记录不存在或已过期，请重新上传文件。", status=404)
    return parse_score(data)


def _suffix(filename: str | None) -> str:
    if filename and filename.lower().endswith(".mxl"):
        return ".mxl"
    if filename and filename.lower().endswith(".xml"):
        return ".xml"
    return ".musicxml"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TransposeForm(BaseModel):
    file_id: str
    part_id: str
    src_letters: int = Field(description="原乐器 记谱->发声 有向字母步数")
    src_semitones: int = Field(description="原乐器 记谱->发声 有向半音数")
    dst_letters: int = Field(description="目标乐器 记谱->发声 有向字母步数")
    dst_semitones: int = Field(description="目标乐器 记谱->发声 有向半音数")
    range_low: str
    range_high: str
    output_label: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/scores")
async def upload_score(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise _reject("empty_file", "上传的文件为空。")
    if len(data) > MAX_UPLOAD_BYTES:
        raise _reject(
            "file_too_large",
            f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB 上限，请压缩或裁剪后再上传。",
        )
    suffix = _suffix(file.filename)
    try:
        root = parse_score(data)
        parts = analyze_parts(root)
    except MusicTheoryError as exc:
        raise _reject("invalid_score", str(exc))
    file_id = storage.save_source(data, suffix)
    return {
        "file_id": file_id,
        "original_filename": file.filename or "score.musicxml",
        "parts": [
            {
                "part_id": p.part_id,
                "name": p.name,
                "abbreviation": p.abbreviation,
                "measures": p.measures,
                "notes": p.note_count,
                "has_unpitched": p.has_unpitched,
                "has_pitched": p.has_pitched,
            }
            for p in parts
        ],
    }


@app.get("/api/scores/{file_id}")
def get_score(file_id: str):
    root = _load_tree(file_id)
    try:
        parts = analyze_parts(root)
    except MusicTheoryError as exc:
        raise _reject("invalid_score", str(exc))
    return {
        "file_id": file_id,
        "parts": [
            {
                "part_id": p.part_id,
                "name": p.name,
                "abbreviation": p.abbreviation,
                "measures": p.measures,
                "notes": p.note_count,
                "has_unpitched": p.has_unpitched,
                "has_pitched": p.has_pitched,
            }
            for p in parts
        ],
    }


@app.post("/api/transpose")
def transpose(form: TransposeForm):
    root = _load_tree(form.file_id)
    try:
        parts = analyze_parts(root)
    except MusicTheoryError as exc:
        raise _reject("invalid_score", str(exc))

    selected = next((p for p in parts if p.part_id == form.part_id), None)
    if selected is None:
        raise _reject("part_not_found", f"总谱中不存在声部 “{form.part_id}”。")
    if selected.has_unpitched:
        raise _reject(
            "unpitched",
            f"声部 “{selected.name}” 含无调打击乐，无法生成移调分谱，已拒绝整份转换。",
        )
    if not selected.has_pitched:
        raise _reject("no_pitch", f"声部 “{selected.name}” 中没有有音高音符，无法移调。")

    params = TransposeParams(
        src_letters=form.src_letters,
        src_semitones=form.src_semitones,
        dst_letters=form.dst_letters,
        dst_semitones=form.dst_semitones,
        range_low=form.range_low,
        range_high=form.range_high,
    )
    try:
        out_tree, meta = build_transposed_score(root, form.part_id, params)
    except OutOfRangeError as exc:
        raise _reject(
            "out_of_range",
            str(exc),
            violations=exc.violations,
        )
    except MusicTheoryError as exc:
        raise _reject("invalid_params", str(exc))

    payload = serialize(out_tree)
    output_id = uuid.uuid4().hex
    path = storage.save_output(output_id, payload)

    label = (form.output_label or "移调分谱").strip()
    download_name = f"{selected.name}_{label}.musicxml"
    return {
        "output_id": output_id,
        "part_name": meta["part_name"],
        "measures": meta["measures"],
        "notes": meta["notes"],
        "interval_label": meta["interval_label"],
        "transpose": {
            "diatonic": meta["diatonic"],
            "chromatic": meta["chromatic"],
            "octave_change": meta["octave_change"],
            "L": meta["L"],
            "S": meta["S"],
        },
        "download_name": download_name,
        "download_url": f"/api/outputs/{output_id}/download?name={download_name}",
        "preview_xml": payload.decode("utf-8"),
    }


@app.get("/api/outputs/{output_id}/download")
def download(output_id: str, name: str = "transposed.musicxml"):
    path = storage.output_path(output_id)
    if path is None:
        raise _reject("not_found", "生成结果不存在或已过期。", status=404)
    safe_name = os.path.basename(name) or "transposed.musicxml"
    return FileResponse(
        path,
        media_type="application/vnd.recordare.musicxml+xml",
        filename=safe_name,
    )


@app.get("/api/outputs/{output_id}")
def view_output(output_id: str):
    path = storage.output_path(output_id)
    if path is None:
        raise _reject("not_found", "生成结果不存在或已过期。", status=404)
    return Response(
        path.read_bytes(),
        media_type="application/vnd.recordare.musicxml+xml",
    )


# Serve the built frontend when present (Docker image).
_STATIC_DIR = Path(os.getenv("STATIC_DIR", "../frontend/dist"))
if _STATIC_DIR.exists():
    from fastapi.staticfiles import StaticFiles

    @app.get("/")
    def root_index():
        return FileResponse(_STATIC_DIR / "index.html")

    app.mount(
        "/assets",
        StaticFiles(directory=_STATIC_DIR / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        # never shadow API routes
        if full_path.startswith("api/"):
            raise _reject("not_found", "接口不存在。", status=404)
        candidate = _STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC_DIR / "index.html")
