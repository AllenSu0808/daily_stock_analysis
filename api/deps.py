# -*- coding: utf-8 -*-
"""
===================================
API 依賴注入模塊
===================================

職責：
1. 提供數據庫 Session 依賴
2. 提供配置依賴
3. 提供服務層依賴
"""

from typing import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from src.storage import DatabaseManager
from src.config import get_config, Config
from src.services.system_config_service import SystemConfigService
from src.services.runtime_scheduler import RuntimeSchedulerService


def get_db() -> Generator[Session, None, None]:
    """
    獲取數據庫 Session 依賴
    
    使用 FastAPI 依賴注入機制，確保請求結束後自動關閉 Session
    
    Yields:
        Session: SQLAlchemy Session 對象
        
    Example:
        @router.get("/items")
        async def get_items(db: Session = Depends(get_db)):
            ...
    """
    db_manager = DatabaseManager.get_instance()
    session = db_manager.get_session()
    try:
        yield session
    finally:
        session.close()


def get_config_dep() -> Config:
    """
    獲取配置依賴
    
    Returns:
        Config: 配置單例對象
    """
    return get_config()


def get_database_manager() -> DatabaseManager:
    """
    獲取數據庫管理器依賴
    
    Returns:
        DatabaseManager: 數據庫管理器單例對象
    """
    return DatabaseManager.get_instance()


def get_system_config_service(request: Request) -> SystemConfigService:
    """Get app-lifecycle shared SystemConfigService instance."""
    service = getattr(request.app.state, "system_config_service", None)
    if service is None:
        service = SystemConfigService()
        request.app.state.system_config_service = service
    return service


def get_runtime_scheduler_service(request: Request) -> RuntimeSchedulerService:
    """Get app-lifecycle shared RuntimeSchedulerService instance."""
    service = getattr(request.app.state, "runtime_scheduler_service", None)
    if service is None:
        service = RuntimeSchedulerService()
        request.app.state.runtime_scheduler_service = service
    return service
