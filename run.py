#!/usr/bin/env python3
"""启动入口"""
import uvicorn

if __name__ == "__main__":
    print("=" * 50)
    print("  WC2026 套利监控台")
    print("  http://localhost:8000")
    print("=" * 50)
    uvicorn.run("dashboard.app:app", host="0.0.0.0", port=8000, reload=False)
