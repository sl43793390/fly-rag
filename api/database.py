"""
api.database
~~~~~~~~~~~~
SQLAlchemy 引擎 / 会话工厂(MySQL,元数据持久层)。
"""
import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from api.api_config import mysql_url

logger = logging.getLogger("api.database")

engine = create_engine(
    mysql_url(),
    pool_pre_ping=True,   # 取连接前 ping,自动重连
    pool_recycle=3600,    # 1 小时回收,避免 MySQL wait_timeout 断连
    pool_size=10,
    max_overflow=20,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

Base = declarative_base()


def get_db():
    """FastAPI 依赖:每个请求一个 Session,请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# 表结构增量升级
#   Base.metadata.create_all 只建新表,不会修改已存在的表。
#   当老库的 chat_session / chat_message 缺少新字段(owner_id、
#   mode、is_summary)时,查询会因 "Unknown column" 失败。
#   本函数在启动时自动 ALTER 补齐缺失字段(幂等)。
# ============================================================
#: 表名 -> [(列名, DDL 片段)] 新增列(若不存在)
_SCHEMA_PATCHES = {
    "chat_session": [
        ("owner_id", "owner_id BIGINT NULL COMMENT '会话所有者(用户 id,可空为匿名会话)'"),
        ("mode", "mode VARCHAR(16) NOT NULL DEFAULT 'rag' COMMENT '会话模式: rag/chat'"),
    ],
    "chat_message": [
        ("is_summary", "is_summary TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为压缩摘要消息'"),
    ],
}

#: 需要把"NOT NULL"改成"NULL"的列(老库的约束与新版不兼容)
#:
#: chat_session.kb_id 在新版设计里允许为空(纯 LLM 对话不挂知识库),
#: 但老库建表时是 NOT NULL + 外键,插入 NULL 会报 1048。
#: 这里把列改成可空(外键约束本身允许 NULL,无需删除)。
_SCHEMA_NULLABLE_FIXES = [
    ("chat_session", "kb_id", "BIGINT NULL"),
]


def ensure_schema_upgrades() -> None:
    """检查并补齐老表缺失的列 / 把不应 NOT NULL 的列改为可空(幂等,启动时调用)。"""
    insp = inspect(engine)
    with engine.begin() as conn:
        # 1) 补齐缺失的新列
        for table, columns in _SCHEMA_PATCHES.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for col_name, col_ddl in columns:
                if col_name in existing:
                    continue
                # ADD COLUMN 时尽量放在末尾,避免 MySQL 8 的 FIRST/AFTER 兼容问题
                sql = f"ALTER TABLE `{table}` ADD COLUMN {col_ddl}"
                # 若是 NOT NULL 但表里已有数据,需要给默认值;上面 DDL 已带 DEFAULT
                try:
                    conn.execute(text(sql))
                    logger.info("已补齐字段:%s.%s", table, col_name)
                except Exception as e:  # noqa: BLE001 - 字段已存在或其它,跳过
                    logger.warning("补齐字段失败 %s.%s: %s", table, col_name, e)

        # 2) 把不应 NOT NULL 的列改为可空
        for table, col_name, col_type in _SCHEMA_NULLABLE_FIXES:
            if not insp.has_table(table):
                continue
            existing = {c["name"]: c for c in insp.get_columns(table)}
            col = existing.get(col_name)
            if col is None:
                continue
            # nullable=False 表示当前是 NOT NULL,需要改
            if col.get("nullable", True):
                continue
            sql = f"ALTER TABLE `{table}` MODIFY COLUMN `{col_name}` {col_type}"
            try:
                conn.execute(text(sql))
                logger.info("已将 %s.%s 改为可空", table, col_name)
            except Exception as e:  # noqa: BLE001
                logger.warning("改可空失败 %s.%s: %s", table, col_name, e)

        # 3) 给 owner_id / mode 建索引(若不存在则创建,失败忽略)
        existing_idx_chat = {i["name"] for i in insp.get_indexes("chat_session")} if insp.has_table("chat_session") else set()
        for idx_sql in (
            "CREATE INDEX idx_chat_session_owner ON chat_session(owner_id)",
            "CREATE INDEX idx_chat_session_mode ON chat_session(mode)",
        ):
            try:
                conn.execute(text(idx_sql))
            except Exception:
                # 索引已存在或权限不足,忽略
                pass
