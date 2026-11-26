# 证研 · 股票投资顾问 Agent：一个镜像同时包含 FastAPI 后端与构建好的 React 前端。
#   docker compose up -d --build      → http://localhost:8000
# 国内网络可在 .env 里设置 PIP_INDEX_URL / NPM_REGISTRY 使用镜像源（见 .env.example）。

# ---------- 1. 构建前端 ----------
FROM node:22-alpine AS web
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --registry="$NPM_REGISTRY" --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------- 2. 运行时 ----------
FROM python:3.12-slim AS app
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    TZ=Asia/Shanghai
WORKDIR /app

# 依赖由 uv.lock 导出（带哈希，镜像源下载的文件同样会校验）
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
# 以可编辑方式安装：代码仍在 /app/src，settings.ROOT 才能定位到 /app/config、/app/evals、/app/web/dist
RUN pip install --no-deps -e .

COPY config ./config
COPY evals ./evals
COPY --from=web /web/dist ./web/dist
RUN mkdir -p /app/reports

EXPOSE 8000
CMD ["advisor", "serve", "--host", "0.0.0.0", "--port", "8000"]

# ---------- 3. 测试（docker compose --profile test run --rm test） ----------
FROM app AS test
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY tests ./tests
CMD ["python", "-m", "pytest", "-q"]
