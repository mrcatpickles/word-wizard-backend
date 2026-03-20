import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# 暴力跨域权限
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "info": "Word Wizard Backend is LIVE"}

@app.post("/api/get_words")
async def get_words(data: dict):
    # 这里是你的核心业务占位
    return {"status": "success", "words": ["magic", "wizard", "spell"]}

@app.post("/api/process_turn")
async def process_turn(data: dict):
    return {"status": "success", "check_result": {"is_correct": True, "feedback": "Nice!"}}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
