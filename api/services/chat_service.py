"""
api.services.chat_service
~~~~~~~~~~~~~~~~~~~~~~~~~
对话服务:为每个会话(session)维护一个对话引擎,并让对话历史
同时落 MySQL(重启后自动从数据库恢复上下文)。

支持两种会话模式:
- ``mode=rag`` (kb_id 必填):CustomRAGChatEngine,带 Milvus 检索;
- ``mode=chat`` (kb_id 可空):SimpleChatEngine,纯 LLM 对话,不检索。

历史自动压缩:
- 每个会话默认保留最近 ``MAX_KEEP_ROUNDS`` 轮(= 30 轮 = 60 条消息);
- 超过阈值时,把最旧的若干条(按整数轮对齐)送 LLM 总结,
  写入一条 ``is_summary=1`` 的 assistant 消息占位,并删除原消息;
- 压缩后丢弃内存中的 engine 缓存,下次对话时从 DB 重新加载压缩后的历史。

设计要点:
- 引擎缓存: {session_id: engine},进程内复用;知识库被删时批量失效;
- 每个会话一把锁:防止同一会话并发 chat 导致 memory 乱序。
"""
import logging
import threading
from typing import Dict, List, Optional

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.base.llms.types import ChatMessage, ChatResponse, MessageRole
from llama_index.core.chat_engine.types import AgentChatResponse
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.schema import NodeWithScore

from api.database import SessionLocal
from api.services.milvus_cache import ensure_loaded, get_store
from config import CHAT
from vectorStore.custom_engine import (
    CustomRAGChatEngine,
    SimpleStreamChatResponse,
    _format_chat_history,
    _log_block,
)

logger = logging.getLogger("api.chat")

#: 默认保留最近 30 轮对话(= 60 条消息)
MAX_KEEP_ROUNDS: int = int(__import__("os").environ.get("CHAT_MAX_KEEP_ROUNDS", "30"))
#: 触发压缩后,把超出 MAX_KEEP_ROUNDS 的最旧对话整体送 LLM 总结
COMPRESSION_SUMMARY_PROMPT = (
    "请把以下对话内容用中文总结成一段简洁的要点摘要,"
    "保留关键事实、用户意图和结论,不要列对话原文,不要添加新信息。\n\n"
    "对话内容:\n{history}\n\n摘要:"
)

#: 知识库会话(RAG)专属系统提示词:
#: 严格限定 AI 只基于检索到的参考资料回答,并在回复末尾标注引用文档,
#: 防止大模型脱离知识库自由发挥(幻觉)。
KB_RAG_SYSTEM_PROMPT = (
    "你是知识库「{kb_name}」的专属问答助手,必须严格遵守以下规则:\n"
    "1. 只依据用户消息中提供的参考资料回答问题,"
    "严禁编造、猜测或引入参考资料之外的信息;\n"
    "2. 参考资料中每个片段都标注了【来源: 文档名 | 章节: 章节路径】,"
    "回答末尾请以「引用文档:」单独一行列出所参考的文档名称"
    "(可附上具体章节,如「引用文档: 安装指南(第二章 安装 > 2.2 安装步骤)」;"
    "没有引用时不要输出该行);\n"
    "3. 若参考资料中没有相关内容或不足以回答问题,请直接回答"
    "「抱歉,当前知识库中没有找到与您问题相关的内容,我无法回答该问题。」"
    "并建议用户调整提问或补充知识库文档,严禁凭自身常识或外部知识强行作答;\n"
    "4. 使用中文回答,条理清晰,必要时分点阐述。"
)

#: 纯 LLM 会话(未挂知识库)系统提示词:无主题限制,自由作答。
PLAIN_CHAT_SYSTEM_PROMPT = (
    "你是一个专业的中文 AI 助手,可以回答任何领域的任何问题,"
    "不受特定知识范围限制。请基于对话上下文与自身知识作答,"
    "条理清晰、内容详实。如果确实不确定,请如实告知用户。"
)

#: 知识库会话(RAG)专属 user 消息模板:
#: 与 KB_RAG_SYSTEM_PROMPT 配套,同样严格限定"只能用参考资料回答"。
#: 注意:不能复用 vectorStore.chat.CONTEXT_USER_TEMPLATE_STR ——
#: 该模板末尾"如果参考资料不足,请明确告知用户并给出建议"是弱限制,
#: 会被 LLM 理解为"可以用自身知识给建议",导致脱离知识库自由发挥,
#: 与 KB_RAG_SYSTEM_PROMPT 的"严禁凭自身常识作答"直接冲突。
#: 占位符 {context_str} / {message} 与 CustomRAGChatEngine 约定一致。
KB_RAG_CONTEXT_TEMPLATE = (
    "以下是知识库检索到的参考资料:\n"
    "---------------------\n"
    "{context_str}\n"
    "---------------------\n"
    "请仅依据上述参考资料回答用户的问题,"
    "严禁使用你自身的知识、常识或猜测进行补充或发挥。\n"
    "如果上述参考资料与问题无关或不足以回答,"
    "请直接回答"
    "「抱歉,当前知识库中没有找到与您问题相关的内容,我无法回答该问题。」,"
    "并建议用户调整提问或补充知识库文档。\n"
    "问题: {message}\n"
    "回答:"
)


# ============================================================
# 纯 LLM 对话引擎(无检索)
# ============================================================
class SimpleChatEngine:
    """
    纯 LLM 对话引擎(不挂知识库,不检索)。

    用法与 CustomRAGChatEngine 对齐:
    - ``chat(message)`` 返回带 ``response`` / ``source_nodes`` 的对象;
    - ``stream_chat(message)`` 返回 token 级流式响应;
    - ``reset()`` 清空内存。
    """

    def __init__(
        self,
        llm,
        memory: ChatMemoryBuffer,
        system_prompt: str,
        log_detail: Optional[bool] = None,
    ) -> None:
        self._llm = llm
        self._memory = memory
        self._system_prompt = system_prompt
        #: 全链路明细日志开关(None 时回落到 config.CHAT.log_chat_detail)
        self._log_detail = CHAT.log_chat_detail if log_detail is None else log_detail

    @property
    def chat_history(self) -> List[ChatMessage]:
        return self._memory.get() if self._memory else []

    def reset(self) -> None:
        if self._memory:
            self._memory.reset()

    def _build_messages(self, message: str) -> List[ChatMessage]:
        """system(提示词 + 历史) + user。"""
        system_content = self._system_prompt
        hist_str = _format_chat_history(self.chat_history)
        if hist_str:
            system_content = system_content + hist_str
        if self._log_detail:
            _log_block("① 前端发送的用户消息", message)
            _log_block("② 系统提示词(纯 LLM 对话)", self._system_prompt)
            _log_block(
                "③ 最终发送给大模型的完整消息",
                f"[system]\n{system_content}\n\n[user]\n{message}",
            )
        return [
            ChatMessage(role=MessageRole.SYSTEM, content=system_content),
            ChatMessage(role=MessageRole.USER, content=message),
        ]

    def chat(self, message: str) -> AgentChatResponse:
        messages = self._build_messages(message)
        chat_response: ChatResponse = self._llm.chat(messages)
        assistant_text = chat_response.message.content or ""
        if self._log_detail:
            _log_block("④ 大模型回复", assistant_text or "(空)")
        if self._memory is not None:
            self._memory.put(ChatMessage(role=MessageRole.USER, content=message))
            self._memory.put(
                ChatMessage(role=MessageRole.ASSISTANT, content=assistant_text)
            )
        return AgentChatResponse(response=assistant_text, source_nodes=[])

    def stream_chat(self, message: str) -> SimpleStreamChatResponse:
        """真正的 token 级流式(不检索,无 source_nodes)。"""
        messages = self._build_messages(message)
        chat_iter = self._llm.stream_chat(messages)

        def _on_finish(assistant_text: str) -> None:
            """流正常结束:把完整回复写回 memory。"""
            if self._log_detail:
                _log_block("④ 大模型回复(流式)", assistant_text or "(空)")
            if self._memory is not None:
                self._memory.put(
                    ChatMessage(role=MessageRole.USER, content=message)
                )
                self._memory.put(
                    ChatMessage(role=MessageRole.ASSISTANT, content=assistant_text)
                )

        return SimpleStreamChatResponse(
            chat_stream=chat_iter,
            source_nodes=[],
            on_finish=_on_finish,
        )


# ============================================================
# 服务
# ============================================================
class ChatService:
    """会话级对话引擎管理器。"""

    def __init__(self) -> None:
        self._engines: Dict[int, object] = {}
        self._locks: Dict[int, threading.Lock] = {}
        self._guard = threading.Lock()

    # ---------------- 引擎生命周期 ----------------
    def _session_lock(self, session_id: int) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[session_id] = lock
            return lock

    def _build_rag_engine(
        self, session_id: int, kb_id: int, history: List[ChatMessage], kb_name: str = ""
    ) -> CustomRAGChatEngine:
        """构建 RAG 引擎:Milvus 检索器 + 历史记忆 + 知识库限定提示词。

        - system / user 双层严格提示词,限定只基于检索内容回答;
        - ``min_score`` 过滤低相关节点:知识库外的问题检索不到有效资料,
          LLM 只能看到"(无参考资料)"并按模板拒绝作答,而不是自由发挥。
        """
        retriever = VectorStoreIndex.from_vector_store(
            vector_store=get_store(kb_id)
        ).as_retriever(similarity_top_k=CHAT.similarity_top_k)
        memory = ChatMemoryBuffer.from_defaults(
            chat_history=history, token_limit=CHAT.memory_token_limit
        )
        return CustomRAGChatEngine(
            retriever=retriever,
            llm=Settings.llm,
            memory=memory,
            system_prompt=KB_RAG_SYSTEM_PROMPT.format(
                kb_name=kb_name or f"#{kb_id}"
            ),
            context_template=KB_RAG_CONTEXT_TEMPLATE,
            min_score=CHAT.min_score or None,
        )

    def _build_simple_engine(
        self, history: List[ChatMessage]
    ) -> SimpleChatEngine:
        """构建纯 LLM 引擎:无检索、无主题限制。"""
        memory = ChatMemoryBuffer.from_defaults(
            chat_history=history, token_limit=CHAT.memory_token_limit
        )
        return SimpleChatEngine(
            llm=Settings.llm,
            memory=memory,
            system_prompt=PLAIN_CHAT_SYSTEM_PROMPT,
        )

    def _load_history_from_db(self, session_id: int) -> List[ChatMessage]:
        """从 MySQL 拉取会话历史并转成 LlamaIndex ChatMessage。"""
        from api.models import ChatMessage as DbChatMessage

        db = SessionLocal()
        try:
            history_rows = (
                db.query(DbChatMessage)
                .filter(DbChatMessage.session_id == session_id)
                .order_by(DbChatMessage.id.asc())
                .all()
            )
        finally:
            db.close()
        return [
            ChatMessage(
                role=MessageRole.USER if r.role == "user" else MessageRole.ASSISTANT,
                content=r.content or "",
            )
            for r in history_rows
        ]

    def _get_kb_name(self, kb_id: int) -> str:
        """查询知识库名称(用于系统提示词;不存在时返回空串)。"""
        from api.models import KnowledgeBase

        db = SessionLocal()
        try:
            kb = db.get(KnowledgeBase, kb_id)
            return kb.name if kb else ""
        finally:
            db.close()

    def get_engine(
        self, session_id: int, mode: str, kb_id: Optional[int]
    ) -> object:
        """获取会话引擎(带缓存)。

        每次请求都会调用(引擎命中缓存也走这里),因此把 collection 加载
        放在此处:远程 Milvus 下 collection 可能处于 released(服务器重启/
        自动释放),检索前必须先 load,否则 search 报 code=101。
        """
        # 检索前确保 collection 已加载(幂等;知识库还没文档时自动跳过)
        if mode == "rag" and kb_id is not None:
            ensure_loaded(kb_id)
        with self._guard:
            engine = self._engines.get(session_id)
        if engine is None:
            history = self._load_history_from_db(session_id)
            if mode == "chat":
                engine = self._build_simple_engine(history)
            else:
                if kb_id is None:
                    raise ValueError("RAG 模式下 kb_id 不能为空")
                engine = self._build_rag_engine(
                    session_id, kb_id, history, kb_name=self._get_kb_name(kb_id)
                )
            with self._guard:
                existed = self._engines.get(session_id)
                if existed is not None:
                    engine = existed
                else:
                    self._engines[session_id] = engine
        return engine

    def invalidate_session(self, session_id: int) -> None:
        """丢弃某个会话的引擎缓存(清空对话 / 删除会话 / 压缩后均调用)。"""
        with self._guard:
            self._engines.pop(session_id, None)
            self._locks.pop(session_id, None)

    def invalidate_kb(self, kb_id: int) -> None:
        """删除知识库时,使其所有会话引擎失效。"""
        from api.models import ChatSession

        db = SessionLocal()
        try:
            session_ids = [
                row[0]
                for row in db.query(ChatSession.id).filter(ChatSession.kb_id == kb_id).all()
            ]
        finally:
            db.close()
        with self._guard:
            for sid in session_ids:
                self._engines.pop(sid, None)
                self._locks.pop(sid, None)

    # ---------------- 对话 ----------------
    def chat(
        self,
        session_id: int,
        mode: str,
        kb_id: Optional[int],
        message: str,
    ) -> dict:
        """
        执行一轮对话并落库(RAG 或纯 LLM)。

        Returns:
            ``{"answer", "sources", "message_id", "compressed"}``
        """
        from api.models import ChatMessage as DbChatMessage

        lock = self._session_lock(session_id)
        with lock:  # 同一会话串行,保证记忆顺序正确
            if CHAT.log_chat_detail:
                print(f"\n>>>>>> 会话 {session_id} | 模式 {mode} | 知识库 {kb_id or '无'} <<<<<<")
            engine = self.get_engine(session_id, mode, kb_id)
            response = engine.chat(message)

        sources = []
        if mode == "rag":
            sources = [_node_to_source(n) for n in (response.source_nodes or [])]

        # 落库:user + assistant 两条消息
        db = SessionLocal()
        compressed = False
        try:
            user_msg = DbChatMessage(session_id=session_id, role="user", content=message)
            assistant_msg = DbChatMessage(
                session_id=session_id,
                role="assistant",
                content=response.response or "",
                sources=sources if sources else None,
            )
            db.add(user_msg)
            db.add(assistant_msg)
            db.commit()
            db.refresh(assistant_msg)
            assistant_id = assistant_msg.id

            # 触发自动压缩(基于已落库的全部消息)
            compressed = self._maybe_compress_history(session_id, db)
            if compressed:
                # 缓存失效,下次会重建引擎加载压缩后的历史
                self.invalidate_session(session_id)
            return {
                "answer": response.response or "",
                "sources": sources,
                "message_id": assistant_id,
                "compressed": compressed,
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ---------------- 流式对话 ----------------
    def stream_chat(
        self,
        session_id: int,
        mode: str,
        kb_id: Optional[int],
        message: str,
    ):
        """
        流式对话:生成器,逐段 yield 事件 dict,前端按事件渲染。

        事件协议(均形如 ``{"event": ..., ...}``):
        - ``{"event": "sources", "sources": [...]}``
          检索完成后立即推送(RAG 模式),前端可先渲染引用;
        - ``{"event": "delta", "text": "..."}`` 增量文本;
        - ``{"event": "done", "message_id": int, "compressed": bool, "sources": [...]}``
          生成结束:返回消息 id / 压缩标记 / 完整引用(含元数据);
        - ``{"event": "error", "detail": "..."}`` 出错。

        落库时机:LLM 生成完毕后一次性写 user + assistant 两条消息
        (与 chat() 一致,保证流式 / 非流式落库行为相同)。
        """
        from api.models import ChatMessage as DbChatMessage

        lock = self._session_lock(session_id)
        # 引擎构建与检索在锁内完成(与 chat() 一致,防并发乱序);
        # LLM 流式生成放到锁外,避免长生成阻塞同会话其他请求拿锁
        with lock:
            if CHAT.log_chat_detail:
                print(f"\n>>>>>> 会话 {session_id} | 模式 {mode} | 知识库 {kb_id or '无'} <<<<<<")
            engine = self.get_engine(session_id, mode, kb_id)
            if mode == "rag":
                # 检索先行:拿到节点即可推送 sources
                nodes = engine._retrieve_nodes(message)
                sources = [_node_to_source(n) for n in nodes]
                yield {"event": "sources", "sources": sources}
                response = engine._stream_from_nodes(message, nodes)
            else:
                sources = []
                response = engine.stream_chat(message)
        try:
            full_text = ""
            # 迭代 response_gen:流结束时会通过 on_finish 把完整回复写回 engine memory
            for delta in response.response_gen:
                full_text += delta
                yield {"event": "delta", "text": delta}
        except Exception as e:  # noqa: BLE001
            logger.exception("会话 %s 流式对话异常", session_id)
            yield {"event": "error", "detail": str(e)}
            return

        # 落库(与 chat() 相同逻辑)
        db = SessionLocal()
        compressed = False
        try:
            user_msg = DbChatMessage(session_id=session_id, role="user", content=message)
            assistant_msg = DbChatMessage(
                session_id=session_id,
                role="assistant",
                content=full_text,
                sources=sources if sources else None,
            )
            db.add(user_msg)
            db.add(assistant_msg)
            db.commit()
            db.refresh(assistant_msg)
            assistant_id = assistant_msg.id
            compressed = self._maybe_compress_history(session_id, db)
            if compressed:
                self.invalidate_session(session_id)
            yield {
                "event": "done",
                "message_id": assistant_id,
                "compressed": compressed,
                "sources": sources,
            }
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.exception("会话 %s 流式落库异常", session_id)
            yield {"event": "error", "detail": str(e)}
        finally:
            db.close()

    # ---------------- 历史自动压缩 ----------------
    def _maybe_compress_history(self, session_id: int, db) -> bool:
        """
        如果会话消息数超过 ``MAX_KEEP_ROUNDS * 2``,则把最旧的若干条
        (按整数轮对齐,即 user+assistant 成对)压缩为一条摘要消息。

        Returns:
            是否触发了压缩。
        """
        from api.models import ChatMessage as DbChatMessage

        msgs: List[DbChatMessage] = (
            db.query(DbChatMessage)
            .filter(DbChatMessage.session_id == session_id)
            .order_by(DbChatMessage.id.asc())
            .all()
        )
        keep_count = MAX_KEEP_ROUNDS * 2  # 30 轮 = 60 条
        if len(msgs) <= keep_count:
            return False

        # 把待压缩消息按整数轮对齐(从开头截到偶数位置,避免拆开 user/assistant)
        overflow = len(msgs) - keep_count
        if overflow % 2 != 0:
            overflow += 1  # 多压一条,保证保留下来的开头是 user
        # 至少保留两轮(避免压缩把内容全吃掉)
        overflow = min(overflow, len(msgs) - 4)
        if overflow < 2:
            return False

        to_compress = msgs[:overflow]
        to_delete_ids = [m.id for m in to_compress]

        # 用 LLM 总结(只放正文,不放 sources/元信息)
        history_text = "\n\n".join(
            ("用户: " if m.role == "user" else "助手: ") + (m.content or "")
            for m in to_compress
        )
        prompt = COMPRESSION_SUMMARY_PROMPT.format(history=history_text)

        try:
            summary = Settings.llm.complete(prompt).text or "前序对话已总结。"
            summary = summary.strip()
        except Exception as e:  # noqa: BLE001 - 压缩失败不阻断主对话
            logger.warning("会话 %s 历史压缩失败: %s", session_id, e)
            return False

        # 1) 写入一条摘要占位消息(created_at 用被压缩消息的最早时间,保持时序)
        earliest_created = to_compress[0].created_at
        summary_msg = DbChatMessage(
            session_id=session_id,
            role="assistant",
            content=(
                f"[历史摘要 {len(to_compress)} 条已压缩]\n{summary}"
            ),
            sources=None,
            is_summary=True,
            created_at=earliest_created,
        )
        # 2) 删除被压缩的原始消息
        db.query(DbChatMessage).filter(
            DbChatMessage.id.in_(to_delete_ids)
        ).delete(synchronize_session=False)
        db.add(summary_msg)
        db.commit()
        logger.info(
            "会话 %s 触发压缩:删除 %d 条旧消息,生成 1 条摘要",
            session_id, len(to_delete_ids),
        )
        return True

    def clear_session(self, session_id: int) -> None:
        """清空会话:删除 DB 消息 + 重置引擎记忆。"""
        from api.models import ChatMessage as DbChatMessage

        lock = self._session_lock(session_id)
        with lock:
            db = SessionLocal()
            try:
                db.query(DbChatMessage).filter(
                    DbChatMessage.session_id == session_id
                ).delete(synchronize_session=False)
                db.commit()
            finally:
                db.close()
            with self._guard:
                engine = self._engines.get(session_id)
            if engine is not None:
                engine.reset()

    def rename_session(self, session_id: int, title: str) -> None:
        """重命名会话(供 chat router 调用)。"""
        from api.models import ChatSession

        db = SessionLocal()
        try:
            s = db.get(ChatSession, session_id)
            if s is not None:
                s.title = title
                db.commit()
        finally:
            db.close()


def _node_to_source(node: NodeWithScore) -> dict:
    """把检索节点转成前端可展示的引用结构(含文档名 + 章节)。"""
    text = node.get_content() or ""
    file_name = ""
    section = ""
    if node.node is not None and getattr(node.node, "metadata", None):
        meta = node.node.metadata
        file_name = (
            meta.get("file_name") or meta.get("file") or ""
        )
        section = (
            meta.get("section") or meta.get("header_path") or ""
        )
    return {
        "text": text[:500],
        "score": float(node.score) if node.score is not None else None,
        "file_name": str(file_name),
        "section": str(section),
    }


#: 进程级单例
chat_service = ChatService()
