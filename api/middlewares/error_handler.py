# -*- coding: utf-8 -*-
"""
===================================
全局異常處理中間件
===================================

職責：
1. 捕獲未處理的異常
2. 統一錯誤響應格式
3. 記錄錯誤日誌
"""

import logging
import traceback
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    全局異常處理中間件
    
    捕獲所有未處理的異常，返回統一格式的錯誤響應
    """
    
    async def dispatch(
        self, 
        request: Request, 
        call_next: Callable
    ) -> Response:
        """
        處理請求，捕獲異常
        
        Args:
            request: 請求對象
            call_next: 下一個處理器
            
        Returns:
            Response: 響應對象
        """
        try:
            response = await call_next(request)
            return response
            
        except Exception as e:
            # 記錄錯誤日誌
            logger.error(
                f"未處理的異常: {e}\n"
                f"請求路徑: {request.url.path}\n"
                f"請求方法: {request.method}\n"
                f"堆棧: {traceback.format_exc()}"
            )
            
            # 返回統一格式的錯誤響應
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "message": "服務器內部錯誤，請稍後重試",
                    "detail": str(e) if logger.isEnabledFor(logging.DEBUG) else None
                }
            )


def add_error_handlers(app) -> None:
    """
    添加全局異常處理器
    
    爲 FastAPI 應用添加各類異常的處理器
    
    Args:
        app: FastAPI 應用實例
    """
    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """處理 HTTP 異常"""
        # 如果 detail 已經是 ErrorResponse 格式的 dict，直接使用
        if isinstance(exc.detail, dict) and "error" in exc.detail and "message" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail
            )
        # 否則將 detail 包裝成 ErrorResponse 格式
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "message": str(exc.detail) if exc.detail else "HTTP Error",
                "detail": None
            }
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """處理請求驗證異常"""
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "message": "請求參數驗證失敗",
                "detail": exc.errors()
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """處理通用異常"""
        logger.error(
            f"未處理的異常: {exc}\n"
            f"請求路徑: {request.url.path}\n"
            f"堆棧: {traceback.format_exc()}"
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "服務器內部錯誤",
                "detail": None
            }
        )
