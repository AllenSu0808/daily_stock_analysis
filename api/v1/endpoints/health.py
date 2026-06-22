# -*- coding: utf-8 -*-
"""
===================================
健康檢查接口
===================================

職責：
1. 提供 /api/v1/health 健康檢查接口
2. 用於負載均衡器和監控系統
"""

from datetime import datetime

from fastapi import APIRouter

from api.v1.schemas.common import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    健康檢查接口
    
    用於負載均衡器或監控系統檢查服務狀態
    
    Returns:
        HealthResponse: 包含服務狀態和時間戳
    """
    return HealthResponse(
        status="ok",
        timestamp=datetime.now().isoformat()
    )
