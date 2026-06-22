# -*- coding: utf-8 -*-
"""
===================================
API 中間件模塊初始化
===================================

職責：
1. 導出所有中間件
"""

from api.middlewares.error_handler import ErrorHandlerMiddleware

__all__ = ["ErrorHandlerMiddleware"]
