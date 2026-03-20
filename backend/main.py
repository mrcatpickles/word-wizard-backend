import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# 开启所有跨域权限
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Backend is running on Fly.io!"}

# --- 你的业务接口 ---
@app.post("/api/get_words")
async def get_words(data: dict):
    return {"status": "success", "words": ["magic", "wizard", "spell"]}

@app.post("/api/process_turn")
async def process_turn(data: dict):
    return {"status": "success", "check_result": {"is_correct": True, "feedback": "Nice!"}}

# --- 必须这样写才能在云端跑通 ---
if __name__ == "__main__":
    # 获取环境变量 PORT，没有则默认 8080
    port = int(os.environ.get("PORT", 8080))
    # 必须是 0.0.0.0
    uvicorn.run(app, host="0.0.0.0", port=port)
