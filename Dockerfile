FROM python:3.11-slim

WORKDIR /app

# 先安装依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制整个 backend 文件夹到容器
COPY backend/ ./backend/

# 暴露端口
EXPOSE 8080

# 强制执行启动命令：注意路径是 backend.main:app
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
