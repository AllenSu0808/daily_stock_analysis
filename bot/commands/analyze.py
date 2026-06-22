# -*- coding: utf-8 -*-
"""
===================================
股票分析命令
===================================

分析指定股票，調用 AI 生成分析報告。
"""

import re
import logging
from typing import List, Optional

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse
from src.services.stock_code_utils import resolve_index_stock_code_for_analysis

logger = logging.getLogger(__name__)


class AnalyzeCommand(BotCommand):
    """
    股票分析命令
    
    分析指定股票代碼，生成 AI 分析報告並推送。
    
    用法：
        /analyze 600519       - 分析貴州茅臺（精簡報告）
        /analyze 600519 full  - 分析並生成完整報告
    """
    
    @property
    def name(self) -> str:
        return "analyze"
    
    @property
    def aliases(self) -> List[str]:
        return ["a", "分析", "查"]
    
    @property
    def description(self) -> str:
        return "分析指定股票"
    
    @property
    def usage(self) -> str:
        return "/analyze <股票代碼> [full]"
    
    def validate_args(self, args: List[str]) -> Optional[str]:
        """驗證參數"""
        if not args:
            return "請輸入股票代碼"
        
        code = args[0].upper()

        # 驗證股票代碼格式
        # A股：6位數字
        # 港股：HK+5位數字
        # 美股：1-5個大寫字母+.+2個後綴字母
        is_a_stock = re.match(r'^\d{6}$', code)
        is_hk_stock = re.match(r'^HK\d{5}$', code)
        is_us_stock = re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$', code)

        if not (is_a_stock or is_hk_stock or is_us_stock):
            return f"無效的股票代碼: {code}（A股6位數字 / 港股HK+5位數字 / 美股1-5個字母）"
        
        return None
    
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """執行分析命令"""
        code = resolve_index_stock_code_for_analysis(args[0])
        
        # 檢查是否需要完整報告（默認精簡，傳 full/完整/詳細 切換）
        report_type = "simple"
        if len(args) > 1 and args[1].lower() in ["full", "完整", "詳細"]:
            report_type = "full"
        logger.info(f"[AnalyzeCommand] 分析股票: {code}, 報告類型: {report_type}")
        
        try:
            # 調用分析服務
            from src.services.task_service import get_task_service
            from src.enums import ReportType
            
            service = get_task_service()
            
            # 提交異步分析任務
            result = service.submit_analysis(
                code=code,
                report_type=ReportType.from_str(report_type),
                source_message=message
            )
            
            if result.get("success"):
                task_id = result.get("task_id", "")
                return BotResponse.markdown_response(
                    f"✅ **分析任務已提交**\n\n"
                    f"• 股票代碼: `{code}`\n"
                    f"• 報告類型: {ReportType.from_str(report_type).display_name}\n"
                    f"• 任務 ID: `{task_id[:20]}...`\n\n"
                    f"分析完成後將自動推送結果。"
                )
            else:
                error = result.get("error", "未知錯誤")
                return BotResponse.error_response(f"提交分析任務失敗: {error}")
                
        except Exception as e:
            logger.error(f"[AnalyzeCommand] 執行失敗: {e}")
            return BotResponse.error_response(f"分析失敗: {str(e)[:100]}")
