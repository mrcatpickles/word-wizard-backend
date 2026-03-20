from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import uvicorn

app = FastAPI()

# 1. 暴力开启跨域，确保你本地和云端都能通
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 暂时允许所有来源，先跑通再说
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Word Wizard Backend is running!"}

@app.post("/api/get_words")
async def get_words(data: dict):
    # 这里放你原来的 get_words 逻辑
    return {"status": "success", "words": ["Magic", "Wizard", "Power"]}

@app.post("/api/process_turn")
async def process_turn(data: dict):
    # 这里放你原来的 process_turn 逻辑
    return {"status": "success", "check_result": {"is_correct": True, "feedback": "Good job!"}}

# 2. 关键：必须监听 0.0.0.0 和环境变量中的 PORT
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)