import logging
import os

from app.core.config import load_env_file


def configure_logging():
    """配置控制台日志；默认输出 INFO 级别的重要业务信息。"""
    load_env_file()
    level_name = os.getenv("AUDIT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
