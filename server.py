# -*- coding: utf-8 -*-
"""
===================================
Daily Stock Analysis - FastAPI 後端服務入口
===================================

職責：
1. 提供 RESTful API 服務
2. 配置 CORS 跨域支持
3. 健康檢查接口
4. 託管前端靜態文件（生產模式）

啓動方式：
    uvicorn server:app --reload --host 0.0.0.0 --port 8000
    
    或使用 main.py:
    python main.py --serve-only      # 僅啓動 API 服務
    python main.py --serve           # API 服務 + 執行分析
"""

import logging

from src.config import setup_env, get_config
from src.logging_config import setup_logging

# 初始化環境變量與日誌
setup_env()

config = get_config()
level_name = (config.log_level or "INFO").upper()
level = getattr(logging, level_name, logging.INFO)

setup_logging(
    log_prefix="api_server",
    console_level=level,
    extra_quiet_loggers=['uvicorn', 'fastapi'],
)

# 從 api.app 導入應用實例
from api.app import app  # noqa: E402

# 導出 app 供 uvicorn 使用
__all__ = ['app']


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
