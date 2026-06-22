import hashlib
import random
import secrets
import threading
import time
import requests
import json
import uuid
import logging
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)

original_request = requests.Session.request

ua = UserAgent()


class AuthCache:
    def __init__(self):
        self.data = None
        self.expire_at = 0
        self.lock = threading.Lock()
        self.ttl = 20


_cache = AuthCache()


class PatchSign:
    def __init__(self):
        self.patched = False

    def set_patch(self, patched):
        self.patched = patched

    def is_patched(self):
        return self.patched


_patch_sign = PatchSign()


def _get_nid(user_agent):
    """
    獲取東方財富的 NID 授權令牌

    Args:
        user_agent (str): 用戶代理字符串，用於模擬不同的瀏覽器訪問

    Returns:
        str: 返回獲取到的 NID 授權令牌，如果獲取失敗則返回 None

    功能說明:
        該函數通過向東方財富的授權接口發送請求來獲取 NID 令牌，
        用於後續的數據訪問授權。函數實現了緩存機制來避免頻繁請求。
    """
    now = time.time()
    # 檢查緩存是否有效，避免重複請求
    if _cache.data and now < _cache.expire_at:
        return _cache.data
    # 使用線程鎖確保並發安全
    with _cache.lock:
        try:
            def generate_uuid_md5():
                """
                生成 UUID 並對其進行 MD5 哈希處理
                :return: MD5 哈希值（32位十六進制字符串）
                """
                # 生成 UUID
                unique_id = str(uuid.uuid4())
                # 對 UUID 進行 MD5 哈希
                md5_hash = hashlib.md5(unique_id.encode('utf-8')).hexdigest()
                return md5_hash

            def generate_st_nvi():
                """
                生成 st_nvi 值的方法
                :return: 返回生成的 st_nvi 值
                """
                HASH_LENGTH = 4  # 截取哈希值的前幾位

                def generate_random_string(length=21):
                    """
                    生成指定長度的隨機字符串
                    :param length: 字符串長度，默認爲 21
                    :return: 隨機字符串
                    """
                    charset = "useandom-26T198340PX75pxJACKVERYMINDBUSHWOLF_GQZbfghjklqvwyzrict"
                    return ''.join(secrets.choice(charset) for _ in range(length))

                def sha256(input_str):
                    """
                    計算 SHA-256 哈希值
                    :param input_str: 輸入字符串
                    :return: 哈希值（十六進制）
                    """
                    return hashlib.sha256(input_str.encode('utf-8')).hexdigest()

                random_str = generate_random_string()
                hash_prefix = sha256(random_str)[:HASH_LENGTH]
                return random_str + hash_prefix

            url = "https://anonflow2.eastmoney.com/backend/api/webreport"
            # 隨機選擇屏幕分辨率，增加請求的真實性
            screen_resolution = random.choice(['1920X1080', '2560X1440', '3840X2160'])
            payload = json.dumps({
                "osPlatform": "Windows",
                "sourceType": "WEB",
                "osversion": "Windows 10.0",
                "language": "zh-CN",
                "timezone": "Asia/Shanghai",
                "webDeviceInfo": {
                    "screenResolution": screen_resolution,
                    "userAgent": user_agent,
                    "canvasKey": generate_uuid_md5(),
                    "webglKey": generate_uuid_md5(),
                    "fontKey": generate_uuid_md5(),
                    "audioKey": generate_uuid_md5()
                }
            })
            headers = {
                'Cookie': f'st_nvi={generate_st_nvi()}',
                'Content-Type': 'application/json'
            }
            # 增加超時，防止無限等待
            response = requests.request("POST", url, headers=headers, data=payload, timeout=30)
            response.raise_for_status()  # 對 4xx/5xx 響應拋出 HTTPError

            data = response.json()
            nid = data['data']['nid']

            _cache.data = nid
            _cache.expire_at = now + _cache.ttl
            return nid
        except requests.exceptions.RequestException as e:
            logger.warning(f"請求東方財富授權接口失敗: {e}")
            _cache.data = None
            # 該接口請求失敗時，方案可能已失效，後續大概率會繼續失敗，因無法成功獲取，下次會繼續請求，設置較長過期時間，可避免頻繁請求
            _cache.expire_at = now + 5 * 60
            return None
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"解析東方財富授權接口響應失敗: {e}")
            _cache.data = None
            # 該接口請求失敗時，方案可能已失效，後續大概率會繼續失敗，因無法成功獲取，下次會繼續請求，設置較長過期時間，可避免頻繁請求
            _cache.expire_at = now + 5 * 60
            return None


def eastmoney_patch():
    if _patch_sign.is_patched():
        return

    def patched_request(self, method, url, **kwargs):
        # 排除非目標域名
        is_target = any(
            d in (url or "")
            for d in [
                "fund.eastmoney.com",
                "push2.eastmoney.com",
                "push2his.eastmoney.com",
            ]
        )
        if not is_target:
            return original_request(self, method, url, **kwargs)
        # 獲取一個隨機的 User-Agent
        user_agent = ua.random
        # 處理 Headers：確保不破壞業務代碼傳入的 headers
        headers = kwargs.get("headers", {})
        headers["User-Agent"] = user_agent
        nid = _get_nid(user_agent)
        if nid:
            headers["Cookie"] = f"nid18={nid}"
        kwargs["headers"] = headers
        # 隨機休眠，降低被封風險
        sleep_time = random.uniform(1, 4)
        time.sleep(sleep_time)
        return original_request(self, method, url, **kwargs)

    # 全局替換 Session 的 request 入口
    requests.Session.request = patched_request
    _patch_sign.set_patch(True)
