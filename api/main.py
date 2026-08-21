"""
api.main
~~~~~~~~
FastAPI 应用入口。

启动方式::

    python run_server.py
    # 或
    uvicorn api.main:app --host 0.0.0.0 --port 8000

职责:
- lifespan:  注册 LlamaIndex 全局 Settings / 自动建表 / 创建上传目录;
- 挂载路由:  知识库 / 文档 / 对话;
- CORS:      放行前端开发服务器(默认 http://localhost:5173)。
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.api_config import API_HOST, API_PORT, CORS_ORIGINS, UPLOAD_DIR
from api.database import Base, engine
from api.routers import chat as chat_router
from api.routers import documents as documents_router
from api.routers import kb as kb_router
from api.routers import prompt as prompt_router
from api.user.routers import router as user_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期:启动时初始化,关闭时释放后台线程池。"""
    from api.services import ingest_executor

    # 1) 上传目录
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # 2) 老库表结构增量升级:create_all 只建新表不改旧表,
    #    需先补齐 chat_session/chat_message 缺失的字段
    from api.database import ensure_schema_upgrades

    ensure_schema_upgrades()
    logger.info("MySQL 表结构增量升级完成")

    # 4) 自动建表(库需已存在,见 sql/init.sql;表结构变更以脚本为准)
    Base.metadata.create_all(bind=engine)
    logger.info("MySQL 元数据表已就绪")

    # 5) 初始化内置角色/权限与超级管理员(幂等)
    from api.user.services import ensure_default_admin
    try:
        ensure_default_admin()
    except Exception as e:  # noqa: BLE001 - 初始化失败不阻断启动
        logger.warning("默认管理员初始化失败: %s", e)

    # 6) 注册 LlamaIndex 全局 Settings(Embedding + LLM)
    from vectorStore.milvus_store import configure_settings
    configure_settings()
    logger.info("LlamaIndex 全局 Settings(Embedding / LLM)已注册")

    yield

    ingest_executor.shutdown(wait=False)
    logger.info("后台解析线程池已关闭")


app = FastAPI(
    title="知识库 RAG 平台 API",
    description=(
        "多知识库管理 / 文档上传解析切分入库(Milvus) / 带记忆的 RAG 对话。"
        "<br>底层复用项目 dataLoader / spliter / vectorStore 模块。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(kb_router.router)
app.include_router(documents_router.router)
app.include_router(chat_router.router)
app.include_router(prompt_router.router)
app.include_router(user_router)


@app.get("/", tags=["默认"])
def root():
    return {"name": "知识库 RAG 平台 API", "docs": "/docs"}


@app.get("/api/health", tags=["默认"])
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host=API_HOST, port=API_PORT, reload=False)
