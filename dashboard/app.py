"""
FastAPI Dashboard 后端
提供 WebSocket 实时推送 + REST API
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from engine.scheduler import poll_loop, set_broadcast
from data.db import init_db, get_recent_arbs
from config import DONATION_URL, MAX_TRUSTED_ODDS, POLL_INTERVAL, SUSPICIOUS_PROFIT_PCT

app = FastAPI(title="WC2026 套利监控台")

# ── WebSocket 连接管理 ──────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, message: str):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)


manager = ConnectionManager()

# 注入广播函数到调度器
set_broadcast(manager.broadcast)


# ── 路由 ───────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/about", response_class=HTMLResponse)
async def about():
    path = os.path.join(os.path.dirname(__file__), "templates", "about.html")
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # 连接后立即推送最新快照
        snapshot_path = "data/latest_snapshot.json"
        if os.path.exists(snapshot_path):
            with open(snapshot_path, encoding="utf-8") as f:
                await ws.send_text(f.read())
        while True:
            await ws.receive_text()  # 保持连接（客户端不发数据也没关系）
    except WebSocketDisconnect:
        manager.disconnect(ws)


@app.get("/api/history")
async def api_history(limit: int = 50):
    return get_recent_arbs(None if limit <= 0 else limit)


@app.get("/api/history/all")
async def api_history_all():
    return get_recent_arbs(None)


@app.get("/api/snapshot")
async def api_snapshot():
    path = "data/latest_snapshot.json"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"error": "no data yet"}


@app.get("/api/config")
async def api_config():
    return {
        "donation_url": DONATION_URL,
        "poll_interval": POLL_INTERVAL,
        "suspicious_profit_pct": SUSPICIOUS_PROFIT_PCT,
        "max_trusted_odds": MAX_TRUSTED_ODDS,
    }


# ── 启动 ───────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(poll_loop())


if __name__ == "__main__":
    uvicorn.run("dashboard.app:app", host="0.0.0.0", port=8000, reload=False)
