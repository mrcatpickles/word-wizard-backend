FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝代码
COPY backend/ ./backend/

# 暴露端口
EXPOSE 8080

# 强制启动指令
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
