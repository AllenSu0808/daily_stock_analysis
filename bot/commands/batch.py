# -*- coding: utf-8 -*-
"""
===================================
批量分析命令
===================================

批量分析自選股列表中的所有股票。
"""

import logging
import threading
import uuid
from typing import List

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse

logger = logging.getLogger(__name__)


class BatchCommand(BotCommand):
    """
    批量分析命令
    
    批量分析配置中的自選股列表，生成匯總報告。
    
    用法：
        /batch      - 分析所有自選股
        /batch 3    - 只分析前3隻
    """
    
    @property
    def name(self) -> str:
        return "batch"
    
    @property
    def aliases(self) -> List[str]:
        return ["b", "批量", "全部"]
    
    @property
    def description(self) -> str:
        return "批量分析自選股"
    
    @property
    def usage(self) -> str:
        return "/batch [數量]"
    
    @property
    def admin_only(self) -> bool:
        """批量分析需要管理員權限（防止濫用）"""
        return False  # 可以根據需要設爲 True
    
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """執行批量分析命令"""
        from src.config import get_config
        
        config = get_config()
        config.refresh_stock_list()
        
        stock_list = config.stock_list
        
        if not stock_list:
            return BotResponse.error_response(
                "自選股列表爲空，請先配置 STOCK_LIST"
            )
        
        # 解析數量參數
        limit = None
        if args:
            try:
                limit = int(args[0])
                if limit <= 0:
                    return BotResponse.error_response("數量必須大於0")
            except ValueError:
                return BotResponse.error_response(f"無效的數量: {args[0]}")
        
        # 限制分析數量
        if limit:
            stock_list = stock_list[:limit]
        
        logger.info(f"[BatchCommand] 開始批量分析 {len(stock_list)} 只股票")
        
        # 在後臺線程中執行分析
        thread = threading.Thread(
            target=self._run_batch_analysis,
            args=(stock_list, message),
            daemon=True
        )
        thread.start()
        
        return BotResponse.markdown_response(
            f"✅ **批量分析任務已啓動**\n\n"
            f"• 分析數量: {len(stock_list)} 只\n"
            f"• 股票列表: {', '.join(stock_list[:5])}"
            f"{'...' if len(stock_list) > 5 else ''}\n\n"
            f"分析完成後將自動推送匯總報告。"
        )
    
    def _run_batch_analysis(self, stock_list: List[str], message: BotMessage) -> None:
        """後臺執行批量分析"""
        try:
            from src.config import get_config
            from main import StockAnalysisPipeline
            
            config = get_config()
            
            # 創建分析管道
            pipeline = StockAnalysisPipeline(
                config=config,
                source_message=message,
                query_id=uuid.uuid4().hex,
                query_source="bot"
            )
            
            # 執行分析（會自動推送匯總報告）
            results = pipeline.run(
                stock_codes=stock_list,
                dry_run=False,
                send_notification=True
            )
            
            logger.info(f"[BatchCommand] 批量分析完成，成功 {len(results)} 只")
            
        except Exception as e:
            logger.error(f"[BatchCommand] 批量分析失敗: {e}")
            logger.exception(e)
