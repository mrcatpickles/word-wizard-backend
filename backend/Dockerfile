FROM python:3.13.5 AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app


RUN python -m venv .venv
COPY requirements.txt ./
RUN .venv/bin/pip install -r requirements.txt
FROM python:3.13.5-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY . .
# Fly.io 需要容器监听内部端口；同时需要显式指定应用与端口
CMD ["/app/.venv/bin/uvicorn", "main:app", "--host=0.0.0.0", "--port=8000"]
