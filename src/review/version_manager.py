import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class StrategyVersionManager:
    """策略版本管理器。"""

    def create_version(
        self,
        version: str,
        parameters: dict,
        change_reason: str,
        supporting_data: Optional[dict] = None,
        expected_improvement: Optional[str] = None,
    ) -> dict:
        return {
            "version": version,
            "status": "shadow",
            "parameters": parameters,
            "change_reason": change_reason,
            "supporting_data": supporting_data,
            "expected_improvement": expected_improvement,
            "created_at": datetime.utcnow().isoformat(),
        }

    async def rollback(self, target_version: str, reason: str) -> None:
        """
        緊急回滾至指定版本。

        流程：
        1. 將現版本標記 archived
        2. 重新啟用目標版本
        3. 記錄原因
        """
        logger.warning(f"策略版本回滾至 {target_version}，原因：{reason}")
        # TODO: 連接 DB 更新 strategy_versions 表

    async def activate_shadow(self, version: str) -> None:
        """將 shadow 測試版本切換為 active。"""
        logger.info(f"策略版本 {version} 從 shadow 切換為 active")
        # TODO: DB 操作
