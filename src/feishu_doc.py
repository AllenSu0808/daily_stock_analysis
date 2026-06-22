# feishu_doc.py
# -*- coding: utf-8 -*-
import logging
import json
import lark_oapi as lark
from lark_oapi.api.docx.v1 import *
from typing import List, Dict, Any, Optional
from src.config import get_config

logger = logging.getLogger(__name__)


class FeishuDocManager:
    """飛書雲文檔管理器 (基於官方 SDK lark-oapi)"""

    def __init__(self):
        self.config = get_config()
        self.app_id = self.config.feishu_app_id
        self.app_secret = self.config.feishu_app_secret
        self.folder_token = self.config.feishu_folder_token

        # 初始化 SDK 客戶端
        # SDK 會自動處理 tenant_access_token 的獲取和刷新，無需人工幹預
        if self.is_configured():
            self.client = lark.Client.builder() \
                .app_id(self.app_id) \
                .app_secret(self.app_secret) \
                .log_level(lark.LogLevel.INFO) \
                .build()
        else:
            self.client = None

    def is_configured(self) -> bool:
        """檢查配置是否完整"""
        return bool(self.app_id and self.app_secret and self.folder_token)

    def create_daily_doc(self, title: str, content_md: str) -> Optional[str]:
        """
        創建日報文檔
        """
        if not self.client or not self.is_configured():
            logger.warning("飛書 SDK 未初始化或配置缺失，跳過創建")
            return None

        try:
            # 1. 創建文檔
            # 使用官方 SDK 的 Builder 模式構造請求
            create_request = CreateDocumentRequest.builder() \
                .request_body(CreateDocumentRequestBody.builder()
                              .folder_token(self.folder_token)
                              .title(title)
                              .build()) \
                .build()

            response = self.client.docx.v1.document.create(create_request)

            if not response.success():
                logger.error(f"創建文檔失敗: {response.code} - {response.msg} - {response.error}")
                return None

            doc_id = response.data.document.document_id
            # 這裡的 domain 只是爲了生成鏈接，實際訪問會重定向
            doc_url = f"https://feishu.cn/docx/{doc_id}"
            logger.info(f"飛書文檔創建成功: {title} (ID: {doc_id})")

            # 2. 解析 Markdown 並寫入內容
            # 將 Markdown 轉換爲 SDK 需要的 Block 對象列表
            blocks = self._markdown_to_sdk_blocks(content_md)

            # 飛書 API 限制每次寫入 Block 數量（建議 50 個左右），分批寫入
            batch_size = 50
            doc_block_id = doc_id  # 文檔本身也是一個 block

            for i in range(0, len(blocks), batch_size):
                batch_blocks = blocks[i:i + batch_size]

                # 構造批量添加塊的請求
                batch_add_request = CreateDocumentBlockChildrenRequest.builder() \
                    .document_id(doc_id) \
                    .block_id(doc_block_id) \
                    .request_body(CreateDocumentBlockChildrenRequestBody.builder()
                                  .children(batch_blocks)  # SDK 需要 Block 對象列表
                                  .index(-1)  # 追加到末尾
                                  .build()) \
                    .build()

                write_resp = self.client.docx.v1.document_block_children.create(batch_add_request)

                if not write_resp.success():
                    logger.error(f"寫入文檔內容失敗(批次{i}): {write_resp.code} - {write_resp.msg}")

            logger.info(f"文檔內容寫入完成")
            return doc_url

        except Exception as e:
            logger.error(f"飛書文檔操作異常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _markdown_to_sdk_blocks(self, md_text: str) -> List[Block]:
        """
        將簡單的 Markdown 轉換爲飛書 SDK 的 Block 對象
        """
        blocks = []
        lines = md_text.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 默認普通文本 (Text = 2)
            block_type = 2
            text_content = line

            # 識別標題
            if line.startswith('# '):
                block_type = 3  # H1
                text_content = line[2:]
            elif line.startswith('## '):
                block_type = 4  # H2
                text_content = line[3:]
            elif line.startswith('### '):
                block_type = 5  # H3
                text_content = line[4:]
            elif line.startswith('---'):
                # 分割線
                blocks.append(Block.builder()
                              .block_type(22)
                              .divider(Divider.builder().build())
                              .build())
                continue

            # 構造 Text 類型的 Block
            # SDK 的結構嵌套比較深: Block -> Text -> elements -> TextElement -> TextRun -> content
            text_run = TextRun.builder() \
                .content(text_content) \
                .text_element_style(TextElementStyle.builder().build()) \
                .build()

            text_element = TextElement.builder() \
                .text_run(text_run) \
                .build()

            text_obj = Text.builder() \
                .elements([text_element]) \
                .style(TextStyle.builder().build()) \
                .build()

            # 根據 block_type 放入正確的屬性容器
            block_builder = Block.builder().block_type(block_type)

            if block_type == 2:
                block_builder.text(text_obj)
            elif block_type == 3:
                block_builder.heading1(text_obj)
            elif block_type == 4:
                block_builder.heading2(text_obj)
            elif block_type == 5:
                block_builder.heading3(text_obj)

            blocks.append(block_builder.build())

        return blocks