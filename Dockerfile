# syntax=docker/dockerfile:1

# ---------- 阶段 1：构建前端 ----------
FROM node:20-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：后端 + 前端产物 ----------
FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STATIC_DIR=/app/static

# 仅安装运行 lxml 所需的最小系统库（slim 通常已含 libxml2，保留以防缺失）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
# 前端静态产物交给 FastAPI 托管
COPY --from=frontend /build/frontend/dist ./static

# 非 root 用户运行
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 容器内健康检查：API 存活即视为可用
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

# 初始化与服务在同一条命令中：uvicorn 直接启动（依赖已在镜像构建期安装完毕）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
