# ---------- builder：只负责把包装好 ----------
FROM python:3.12-slim AS builder

WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY app/requirements.txt .
# 装到独立前缀，方便后面整目录搬走
RUN pip install --prefix=/install -r requirements.txt

# ---------- runtime：只留运行需要的东西 ----------
FROM python:3.12-slim

# 容器里跑非 root 是硬要求：一旦 Agent 被注入，攻击者拿到的只是 nobody 权限
RUN useradd -m -u 10001 app
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/usr/local/bin:$PATH"

COPY --from=builder /install /usr/local
COPY --chown=app:app app/ /app/

USER app
EXPOSE 8000

# healthcheck 写在 Dockerfile 里，compose 和 k8s 都能直接复用
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"

# exec 形式（不是 shell 形式）：这样 SIGTERM 直接发给 uvicorn，而不是发给 /bin/sh
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "20"]
