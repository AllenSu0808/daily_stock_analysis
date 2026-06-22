# -*- coding: utf-8 -*-
"""
===================================
API v1 模塊初始化
===================================

職責：
1. 導出 v1 版本 API 的路由
"""

from api.v1.router import router as api_v1_router

__all__ = ["api_v1_router"]
