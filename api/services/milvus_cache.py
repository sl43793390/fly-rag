"""
api.services.milvus_cache
~~~~~~~~~~~~~~~~~~~~~~~~~
MilvusVectorStore 实例缓存(按 collection 隔离,多知识库共用一条 Milvus 连接池)。

为什么需要缓存:
    - 每个知识库对应一个 collection(kb_{id}),API 层所有读写必须显式指定;
    - milvus-lite 嵌入式模式对同一 db 文件的并发连接有限制,复用实例最稳;
    - 避免每次请求重建客户端(握手 / load_collection 开销)。

注意:
    本层构建 store 时**强制 overwrite=False**,与 config.MILVUS.overwrite 无关,
    防止 API 误操作清空知识库数据。
"""
import logging
import sys
import threading
from typing import Dict

from llama_index.vector_stores.milvus import MilvusVectorStore

from vectorStore.milvus_store import build_milvus_store

logger = logging.getLogger(__name__)

# collection_name -> MilvusVectorStore
_stores: Dict[str, MilvusVectorStore] = {}
_lock = threading.Lock()


def _patch_milvus_lite_manifest_save() -> None:
    """
    修复 milvus-lite 在 Windows 上"删除知识库/二次 flush"崩溃的问题。

    背景:
        milvus-lite 的 ``Manifest.save`` 原子提交时使用
        ``os.rename(tmp, manifest.json)``;Windows 的 ``os.rename`` 在目标
        文件已存在时会抛 ``FileExistsError [WinError 183]``。因此一旦集合的
        ``manifest.json`` 已存在(经历过一次以上 flush),删除知识库触发
        最后一次 flush 时必然报错(DELETE /api/kb/{id} -> 500)。

    处理:
        仅把 ``milvus_lite.storage.manifest`` 模块命名空间里的 ``os`` 换成代理,
        把 ``rename`` 映射为 ``os.replace``(跨平台"覆盖式原子改名"),
        其余操作原样委托。改动只落在该模块内,不影响全局 os。

    Note:
        仅 win32 生效;未安装 milvus-lite(远程 Milvus)时自动跳过。
    """
    if sys.platform != "win32":
        return
    try:
        from milvus_lite.storage import manifest as _manifest
    except ImportError:  # pragma: no cover - 远程 Milvus 场景无需补丁
        return
    if getattr(_manifest, "_os_proxy_applied", False):
        return

    class _OsProxy:
        """把 rename 映射为 replace 的 os 代理(仅 manifest 模块内生效)。"""

        def __init__(self, real_os):
            self._real = real_os

        def __getattr__(self, name):
            if name == "rename":
                return self._real.replace
            return getattr(self._real, name)

    _manifest.os = _OsProxy(_manifest.os)
    _manifest._os_proxy_applied = True


_patch_milvus_lite_manifest_save()


def collection_name_for(kb_id: int) -> str:
    """知识库 id -> Milvus collection 名。"""
    return f"kb_{kb_id}"


def get_kb_retrieval_config(kb_id: int) -> dict:
    """
    查询知识库的检索配置(retrieval_mode / hybrid_ranker / hybrid_ranker_params)。

    知识库不存在或字段为空时返回空 dict,由调用方回落默认值(dense + 全局配置)。
    """
    from api.database import SessionLocal
    from api.models import KnowledgeBase

    db = SessionLocal()
    try:
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            return {}
        return {
            "retrieval_mode": kb.retrieval_mode,
            "hybrid_ranker": kb.hybrid_ranker,
            "hybrid_ranker_params": kb.hybrid_ranker_params,
        }
    finally:
        db.close()


def get_store(kb_id: int) -> MilvusVectorStore:
    """
    获取(或创建)某个知识库对应的 MilvusVectorStore。

    store 按知识库配置的检索方式(retrieval_mode)构建:
        - ``dense``  : 纯稠密向量 schema;
        - ``sparse`` / ``hybrid`` : schema 附带 BM25 稀疏字段(两者 schema 相同,
          仅查询路径不同,故建 store 时统一开启 enable_sparse)。

    Args:
        kb_id: 知识库 id。

    Returns:
        该知识库的 MilvusVectorStore(线程安全,进程内复用)。
    """
    cname = collection_name_for(kb_id)
    with _lock:
        store = _stores.get(cname)
        if store is None:
            cfg = get_kb_retrieval_config(kb_id)
            mode = cfg.get("retrieval_mode") or "dense"
            # overwrite=False:collection 不存在时首次写入自动创建,存在时绝不覆盖
            store = build_milvus_store(
                collection_name=cname,
                overwrite=False,
                enable_hybrid=mode in ("sparse", "hybrid"),
                hybrid_ranker=cfg.get("hybrid_ranker"),
                hybrid_ranker_params=cfg.get("hybrid_ranker_params"),
            )
            _stores[cname] = store
        return store


def invalidate_store(kb_id: int) -> None:
    """
    丢弃某知识库缓存的 MilvusVectorStore(检索配置变更后调用)。

    下次 :func:`get_store` 会按新的检索配置重建 store。

    Note:
        Milvus 不支持对已有 collection 增删字段:检索方式变更只对"新建的
        collection"生效。已有数据的知识库从 dense 切到 sparse/hybrid 时,
        需要删除重建知识库(或清空文档重新上传)后,新 schema 才会带上
        BM25 稀疏字段。
    """
    cname = collection_name_for(kb_id)
    with _lock:
        store = _stores.pop(cname, None)
    if store is not None:
        try:
            store.client.close()
        except Exception:  # noqa: BLE001 - 关闭失败不阻断流程
            pass


def ensure_loaded(kb_id: int) -> None:
    """
    确保该知识库的 Milvus collection 处于已加载(Loaded)状态。

    远程 Milvus(standalone / cluster,走 gRPC)在服务器重启或内存压力自动释放后,
    collection 会处于 ``released`` 状态,此时 search/query 会报
    ``code=101 "Collection 'kb_x' is in state 'released'; call load() before search"``。
    llama-index 的 MilvusVectorStore 只对新建 collection 自动 load,
    对已存在的 collection 不会主动 load,因此需要在检索前显式加载。

    在每次检索请求前调用(已加载时 ``load_collection`` 是幂等空操作,开销很小)。

    Args:
        kb_id: 知识库 id。

    Raises:
        pymilvus.exceptions.MilvusException: collection 存在但加载失败时向上抛出。
    """
    store = get_store(kb_id)
    cname = store.collection_name
    # collection 尚不存在(如新建知识库还没上传文档)时跳过,避免误报
    if store.client.has_collection(cname):
        store.client.load_collection(cname)


def drop_kb_collection(kb_id: int) -> bool:
    """
    删除知识库的 Milvus collection(随知识库删除调用)。

    已通过 :func:`_patch_milvus_lite_manifest_save` 修复 Windows 上
    ``os.rename`` 不覆盖导致的 WinError 183;此处再留一层兜底:若
    ``drop_collection`` 仍失败(如历史残留 manifest 文件等),退化为
    直接删除集合目录(milvus-lite 本地模式的 collection 即一个目录)。

    Args:
        kb_id: 知识库 id。

    Returns:
        collection 是否真的被删除。
    """
    cname = collection_name_for(kb_id)
    with _lock:
        store = _stores.pop(cname, None)
        if store is not None:
            try:
                store.client.close()
            except Exception:  # noqa: BLE001 - 关闭失败不阻断删除流程
                pass
        from pymilvus import MilvusClient
        from config import MILVUS
        client = MilvusClient(uri=MILVUS.uri)
        try:
            if client.has_collection(cname):
                try:
                    client.drop_collection(cname)
                except Exception as exc:  # noqa: BLE001 - 见函数 docstring 兜底说明
                    logger.warning(
                        "drop_collection(%s) 失败:%s;退化为直接删除集合目录", cname, exc
                    )
                    _force_drop_collection_dir(MILVUS.uri, cname)
                return True
            return False
        finally:
            client.close()


def _force_drop_collection_dir(uri: str, cname: str) -> None:
    """直接删除 milvus-lite 集合目录(本地模式 collection 即目录)。"""
    if "://" in str(uri):  # 远程 Milvus,无本地目录可删,交给上层异常处理
        return
    import shutil
    from pathlib import Path

    coll_dir = Path(uri) / "collections" / cname
    if coll_dir.exists():
        shutil.rmtree(coll_dir, ignore_errors=True)
        logger.info("已直接删除集合目录: %s", coll_dir)
