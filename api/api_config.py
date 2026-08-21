"""
api.api_config
~~~~~~~~~~~~~~
API 层专属配置(MySQL / 上传目录 / 线程池),全部支持环境变量覆盖。
与项目根目录的 ``config.py``(Embedding / LLM / Milvus / Chat)互补。
"""
import os

# ------------------------------------------------------------
# MySQL 连接(元数据:知识库 / 文档 / 会话 / 消息)
# ------------------------------------------------------------
MYSQL_HOST: str = os.environ.get("MYSQL_HOST", "192.168.80.151")
MYSQL_PORT: int = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER: str = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD: str = os.environ.get("MYSQL_PASSWORD", "test")
MYSQL_DB: str = os.environ.get("MYSQL_DB", "kb_rag")

# ------------------------------------------------------------
# 文件上传
# ------------------------------------------------------------
#: 上传文件落盘根目录(按知识库分子目录: uploads/kb_{id}/xxx)
UPLOAD_DIR: str = os.environ.get("UPLOAD_DIR", "./uploads")

#: 单文件大小上限(字节),默认 200MB
MAX_UPLOAD_SIZE: int = int(os.environ.get("MAX_UPLOAD_SIZE", str(200 * 1024 * 1024)))

# ------------------------------------------------------------
# 后台任务
# ------------------------------------------------------------
#: 文档解析/嵌入线程池大小。
#: milvus-lite 嵌入式模式对同一 db 文件的并发写有限制,保持 1 串行最稳。
INGEST_WORKERS: int = int(os.environ.get("INGEST_WORKERS", "1"))

# ------------------------------------------------------------
# 服务
# ------------------------------------------------------------
API_HOST: str = os.environ.get("API_HOST", "0.0.0.0")
API_PORT: int = int(os.environ.get("API_PORT", "8000"))

#: 允许的前端来源(CORS),逗号分隔;* 表示全部放行
CORS_ORIGINS: list = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()
]


def mysql_url() -> str:
    """构造 SQLAlchemy 连接串(pymysql 驱动)。"""
    return (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
        f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
    )
