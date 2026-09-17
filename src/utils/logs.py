from loguru import logger

# 按天轮转日志并保留最近 7 天，供 Streamlit 和回测流程统一记录。
logger.add(
    "./logs/{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="7 days",
    level="INFO",
    encoding="utf-8",
)
