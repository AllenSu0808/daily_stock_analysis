# -*- coding: utf-8 -*-
"""
===================================
實時行情統一類型定義 & 熔斷機制
===================================

設計目標：
1. 統一各數據源的實時行情返回結構
2. 實現熔斷/冷卻機制，避免連續失敗時反覆請求
3. 支持多數據源故障切換

使用方式：
- 所有 Fetcher 的 get_realtime_quote() 統一返回 UnifiedRealtimeQuote
- CircuitBreaker 管理各數據源的熔斷狀態
"""

import logging
import time
from threading import RLock
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Union
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================
# 通用類型轉換工具函數
# ============================================
# 設計說明：
# 各數據源返回的原始數據類型不一致（str/float/int/NaN），
# 使用這些函數統一轉換，避免在各 Fetcher 中重複定義。

def safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """
    安全轉換爲浮點數
    
    處理場景：
    - None / 空字符串 → default
    - pandas NaN / numpy NaN → default
    - 數值字符串 → float
    - 已是數值 → float
    
    Args:
        val: 待轉換的值
        default: 轉換失敗時的默認值
        
    Returns:
        轉換後的浮點數，或默認值
    """
    try:
        if val is None:
            return default
        
        # 處理字符串
        if isinstance(val, str):
            val = val.strip()
            if val == "" or val == "-" or val == "--":
                return default
        
        # 處理 pandas/numpy NaN
        # 使用 math.isnan 而不是 pd.isna，避免強制依賴 pandas
        import math
        try:
            if math.isnan(float(val)):
                return default
        except (ValueError, TypeError):
            pass
        
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    """
    安全轉換爲整數
    
    先轉換爲 float，再取整，處理 "123.0" 這類情況
    
    Args:
        val: 待轉換的值
        default: 轉換失敗時的默認值
        
    Returns:
        轉換後的整數，或默認值
    """
    f_val = safe_float(val, default=None)
    if f_val is not None:
        return int(f_val)
    return default


class RealtimeSource(Enum):
    """實時行情數據源"""
    EFINANCE = "efinance"           # 東方財富（efinance庫）
    AKSHARE_EM = "akshare_em"       # 東方財富（akshare庫）
    AKSHARE_SINA = "akshare_sina"   # 新浪財經
    AKSHARE_QQ = "akshare_qq"       # 騰訊財經
    TUSHARE = "tushare"             # Tushare Pro
    TENCENT = "tencent"             # 騰訊直連
    SINA = "sina"                   # 新浪直連
    STOOQ = "stooq"                 # Stooq 美股兜底
    LONGBRIDGE = "longbridge"       # 長橋（美股/港股兜底）
    FALLBACK = "fallback"           # 降級兜底


@dataclass
class UnifiedRealtimeQuote:
    """
    統一實時行情數據結構
    
    設計原則：
    - 各數據源返回的字段可能不同，缺失字段用 None 表示
    - 主流程使用 getattr(quote, field, None) 獲取，保證兼容性
    - source 字段標記數據來源，便於調試
    """
    code: str
    name: str = ""
    source: RealtimeSource = RealtimeSource.FALLBACK

    # === 數據質量元數據（由 DataFetcherManager 統一補齊）===
    fetched_at: Optional[str] = None             # 本系統獲取時間（ISO 8601 datetime）
    provider_timestamp: Optional[str] = None     # Provider 真實行情時間（ISO 8601 datetime）
    is_stale: Optional[bool] = None              # provider_timestamp 超過最小 TTL 閾值時爲 True
    stale_seconds: Optional[int] = None          # provider_timestamp 距 fetched_at 的秒數
    fallback_from: Optional[str] = None          # 整源 fallback 的失敗首選源 token
    
    # === 核心價格數據（幾乎所有源都有）===
    price: Optional[float] = None           # 最新價
    change_pct: Optional[float] = None      # 漲跌幅(%)
    change_amount: Optional[float] = None   # 漲跌額
    
    # === 量價指標（部分源可能缺失）===
    volume: Optional[int] = None            # 成交量（股，與歷史日線口徑一致）
    amount: Optional[float] = None          # 成交額（元）
    volume_ratio: Optional[float] = None    # 量比
    turnover_rate: Optional[float] = None   # 換手率(%)
    amplitude: Optional[float] = None       # 振幅(%)
    
    # === 價格區間 ===
    open_price: Optional[float] = None      # 開盤價
    high: Optional[float] = None            # 最高價
    low: Optional[float] = None             # 最低價
    pre_close: Optional[float] = None       # 昨收價
    
    # === 估值指標（僅東財等全量接口有）===
    pe_ratio: Optional[float] = None        # 市盈率(動態)
    pb_ratio: Optional[float] = None        # 市淨率
    total_mv: Optional[float] = None        # 總市值(元)
    circ_mv: Optional[float] = None         # 流通市值(元)
    
    # === 其他指標 ===
    change_60d: Optional[float] = None      # 60日漲跌幅(%)
    high_52w: Optional[float] = None        # 52周最高
    low_52w: Optional[float] = None         # 52周最低
    
    def to_dict(self) -> Dict[str, Any]:
        """轉換爲字典（過濾 None 值）"""
        result = {
            'code': self.code,
            'name': self.name,
            'source': self.source.value,
        }
        # 只添加非 None 的字段
        optional_fields = [
            'fetched_at', 'provider_timestamp', 'is_stale', 'stale_seconds',
            'fallback_from',
            'price', 'change_pct', 'change_amount', 'volume', 'amount',
            'volume_ratio', 'turnover_rate', 'amplitude',
            'open_price', 'high', 'low', 'pre_close',
            'pe_ratio', 'pb_ratio', 'total_mv', 'circ_mv',
            'change_60d', 'high_52w', 'low_52w'
        ]
        for f in optional_fields:
            val = getattr(self, f, None)
            if val is not None:
                result[f] = val
        return result
    
    def has_basic_data(self) -> bool:
        """檢查是否有基本的價格數據"""
        return self.price is not None and self.price > 0
    
    def has_volume_data(self) -> bool:
        """檢查是否有量價數據"""
        return self.volume_ratio is not None or self.turnover_rate is not None


@dataclass
class ChipDistribution:
    """
    籌碼分布數據
    
    反映持倉成本分布和獲利情況
    """
    code: str
    date: str = ""
    source: str = "akshare"
    
    # 獲利情況
    profit_ratio: float = 0.0     # 獲利比例(0-1)
    avg_cost: float = 0.0         # 平均成本
    
    # 籌碼集中度
    cost_90_low: float = 0.0      # 90%籌碼成本下限
    cost_90_high: float = 0.0     # 90%籌碼成本上限
    concentration_90: float = 0.0  # 90%籌碼集中度（越小越集中）
    
    cost_70_low: float = 0.0      # 70%籌碼成本下限
    cost_70_high: float = 0.0     # 70%籌碼成本上限
    concentration_70: float = 0.0  # 70%籌碼集中度
    
    def to_dict(self) -> Dict[str, Any]:
        """轉換爲字典"""
        return {
            'code': self.code,
            'date': self.date,
            'source': self.source,
            'profit_ratio': self.profit_ratio,
            'avg_cost': self.avg_cost,
            'cost_90_low': self.cost_90_low,
            'cost_90_high': self.cost_90_high,
            'concentration_90': self.concentration_90,
            'concentration_70': self.concentration_70,
        }
    
    def get_chip_status(self, current_price: float) -> str:
        """
        獲取籌碼狀態描述
        
        Args:
            current_price: 當前股價
            
        Returns:
            籌碼狀態描述
        """
        status_parts = []
        
        # 獲利比例分析
        if self.profit_ratio >= 0.9:
            status_parts.append("獲利盤極高(獲利盤>90%)")
        elif self.profit_ratio >= 0.7:
            status_parts.append("獲利盤較高(獲利盤70-90%)")
        elif self.profit_ratio >= 0.5:
            status_parts.append("獲利盤中等(獲利盤50-70%)")
        elif self.profit_ratio >= 0.3:
            status_parts.append("套牢盤中等(套牢盤50-70%)")
        elif self.profit_ratio >= 0.1:
            status_parts.append("套牢盤較高(套牢盤70-90%)")
        else:
            status_parts.append("套牢盤極高(套牢盤>90%)")
        
        # 籌碼集中度分析 (90%集中度 < 10% 表示集中)
        if self.concentration_90 < 0.08:
            status_parts.append("籌碼高度集中")
        elif self.concentration_90 < 0.15:
            status_parts.append("籌碼較集中")
        elif self.concentration_90 < 0.25:
            status_parts.append("籌碼分散度中等")
        else:
            status_parts.append("籌碼較分散")
        
        # 成本與現價關係
        if current_price > 0 and self.avg_cost > 0:
            cost_diff = (current_price - self.avg_cost) / self.avg_cost * 100
            if cost_diff > 20:
                status_parts.append(f"現價高於平均成本{cost_diff:.1f}%")
            elif cost_diff > 5:
                status_parts.append(f"現價略高於成本{cost_diff:.1f}%")
            elif cost_diff > -5:
                status_parts.append("現價接近平均成本")
            else:
                status_parts.append(f"現價低於平均成本{abs(cost_diff):.1f}%")
        
        return "，".join(status_parts)


class CircuitBreaker:
    """
    熔斷器 - 管理數據源的熔斷/冷卻狀態
    
    策略：
    - 連續失敗 N 次後進入熔斷狀態
    - 熔斷期間跳過該數據源
    - 冷卻時間後自動恢復半開狀態
    - 半開狀態下單次成功則完全恢復，失敗則繼續熔斷
    
    狀態機：
    CLOSED（正常） --失敗N次--> OPEN（熔斷）--冷卻時間到--> HALF_OPEN（半開）
    HALF_OPEN --成功--> CLOSED
    HALF_OPEN --失敗--> OPEN
    """
    
    # 狀態常量
    CLOSED = "closed"      # 正常狀態
    OPEN = "open"          # 熔斷狀態（不可用）
    HALF_OPEN = "half_open"  # 半開狀態（試探性請求）
    
    def __init__(
        self,
        failure_threshold: int = 3,       # 連續失敗次數閾值
        cooldown_seconds: float = 300.0,  # 冷卻時間（秒），默認5分鐘
        half_open_max_calls: int = 1      # 半開狀態最大嘗試次數
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_calls = half_open_max_calls
        
        # 各數據源狀態 {source_name: {state, failures, last_failure_time, half_open_calls}}
        self._states: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock()
    
    def _get_state_locked(self, source: str) -> Dict[str, Any]:
        """獲取或初始化數據源狀態（調用方需持有鎖）。"""
        if source not in self._states:
            self._states[source] = {
                'state': self.CLOSED,
                'failures': 0,
                'last_failure_time': 0.0,
                'half_open_calls': 0
            }
        return self._states[source]
    
    def is_available(self, source: str) -> bool:
        """
        檢查數據源是否可用
        
        返回 True 表示可以嘗試請求
        返回 False 表示應跳過該數據源
        """
        with self._lock:
            state = self._get_state_locked(source)
            current_time = time.time()

            if state['state'] == self.CLOSED:
                return True

            if state['state'] == self.OPEN:
                # 檢查冷卻時間
                time_since_failure = current_time - state['last_failure_time']
                if time_since_failure >= self.cooldown_seconds:
                    # 冷卻完成，進入半開狀態（不預佔名額，由 HALF_OPEN 分支統一管理）
                    state['state'] = self.HALF_OPEN
                    state['half_open_calls'] = 0
                    state['last_failure_time'] = current_time
                    logger.info(f"[熔斷器] {source} 冷卻完成，進入半開狀態")
                    # Fall through to HALF_OPEN check below
                else:
                    remaining = self.cooldown_seconds - time_since_failure
                    logger.debug(f"[熔斷器] {source} 處於熔斷狀態，剩餘冷卻時間: {remaining:.0f}s")
                    return False

            if state['state'] == self.HALF_OPEN:
                if state['half_open_calls'] < self.half_open_max_calls:
                    state['half_open_calls'] += 1
                    return True
                # 所有探測名額已用完；若冷卻時間再次到期仍未收到
                # record_success/record_failure 回調，重置名額允許重新探測，
                # 避免永久卡在 HALF_OPEN。
                time_since_failure = current_time - state['last_failure_time']
                if time_since_failure >= self.cooldown_seconds:
                    state['half_open_calls'] = 1
                    state['last_failure_time'] = current_time
                    logger.info(f"[熔斷器] {source} 半開狀態探測超時，重新探測")
                    return True
                return False

            return True
    
    def record_inconclusive(self, source: str) -> None:
        """記錄不確定的探測結果（如返回 None）。

        僅影響 HALF_OPEN 狀態：將其轉回 OPEN 以便冷卻後重新探測。
        CLOSED 狀態下爲空操作，不影響失敗計數。
        """
        with self._lock:
            state = self._get_state_locked(source)
            if state['state'] == self.HALF_OPEN:
                state['state'] = self.OPEN
                state['half_open_calls'] = 0
                state['last_failure_time'] = time.time()
                logger.info(f"[熔斷器] {source} 半開探測結果不確定，重新進入冷卻")

    def record_success(self, source: str) -> None:
        """記錄成功請求"""
        with self._lock:
            state = self._get_state_locked(source)

            if state['state'] == self.HALF_OPEN:
                # 半開狀態下成功，完全恢復
                logger.info(f"[熔斷器] {source} 半開狀態請求成功，恢復正常")

            # 重置狀態
            state['state'] = self.CLOSED
            state['failures'] = 0
            state['half_open_calls'] = 0
    
    def record_failure(self, source: str, error: Optional[str] = None) -> None:
        """記錄失敗請求"""
        with self._lock:
            state = self._get_state_locked(source)
            current_time = time.time()

            state['failures'] += 1
            state['last_failure_time'] = current_time

            if state['state'] == self.HALF_OPEN:
                # 半開狀態下失敗，繼續熔斷
                state['state'] = self.OPEN
                state['half_open_calls'] = 0
                logger.warning(f"[熔斷器] {source} 半開狀態請求失敗，繼續熔斷 {self.cooldown_seconds}s")
            elif state['failures'] >= self.failure_threshold:
                # 達到閾值，進入熔斷
                state['state'] = self.OPEN
                logger.warning(f"[熔斷器] {source} 連續失敗 {state['failures']} 次，進入熔斷狀態 "
                              f"(冷卻 {self.cooldown_seconds}s)")
                if error:
                    logger.warning(f"[熔斷器] 最後錯誤: {error}")
    
    def get_status(self) -> Dict[str, str]:
        """獲取所有數據源狀態"""
        with self._lock:
            return {source: info['state'] for source, info in self._states.items()}
    
    def reset(self, source: Optional[str] = None) -> None:
        """重置熔斷器狀態"""
        with self._lock:
            if source:
                if source in self._states:
                    del self._states[source]
            else:
                self._states.clear()


# 全局熔斷器實例（實時行情專用）
_realtime_circuit_breaker = CircuitBreaker(
    failure_threshold=3,      # 連續失敗3次熔斷
    cooldown_seconds=300.0,   # 冷卻5分鐘
    half_open_max_calls=1
)

# 籌碼接口熔斷器（更保守的策略，因爲該接口更不穩定）
_chip_circuit_breaker = CircuitBreaker(
    failure_threshold=2,      # 連續失敗2次熔斷
    cooldown_seconds=600.0,   # 冷卻10分鐘
    half_open_max_calls=1
)


def get_realtime_circuit_breaker() -> CircuitBreaker:
    """獲取實時行情熔斷器"""
    return _realtime_circuit_breaker


def get_chip_circuit_breaker() -> CircuitBreaker:
    """獲取籌碼接口熔斷器"""
    return _chip_circuit_breaker
