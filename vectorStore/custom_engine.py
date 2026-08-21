"""
vectorStore.custom_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~
完全自控的 RAG Chat Engine —— 显式控制"参考资料 + 用户问题"在 user 消息里
送给 LLM,避免 LlamaIndex 内置 ContextChatEngine 在不同版本下行为不一致的问题。

消息拼装规则
------------
system: {system_prompt}\\n\\n{chat_history}
user  : {context_template.format(context_str=<joined nodes>, message=<user query>)}
"""
from typing import List, Optional

from llama_index.core.base.llms.types import (
    ChatMessage,
    ChatResponse,
    MessageRole,
)
from llama_index.core.chat_engine.types import (
    AgentChatResponse,
    BaseChatEngine,
)
from llama_index.core.llms import LLM
from llama_index.core.memory import BaseMemory
from llama_index.core.schema import NodeWithScore

from config import CHAT


class SimpleStreamChatResponse:
    """
    轻量流式响应包装(不依赖 LlamaIndex 版本细节)。

    仅暴露本项目消费的两个能力:
    - ``response_gen``: 迭代产出增量文本,流正常结束时回调 ``on_finish``
      把完整回复写回 memory;
    - ``source_nodes``: 检索节点(RAG 模式)。

    避免 ``StreamingAgentChatResponse`` 在不同 llama-index 版本下
    构造签名 / 写记忆机制不一致的问题(其 response_gen 依赖后台线程)。
    """

    def __init__(self, chat_stream, source_nodes=None, on_finish=None) -> None:
        self._chat_stream = chat_stream
        self.source_nodes = list(source_nodes or [])
        self._on_finish = on_finish

    @property
    def response_gen(self):
        final_text = ""
        try:
            for chat in self._chat_stream:
                delta = chat.delta or ""
                final_text += delta
                yield delta
        except Exception:
            # 流异常:不写记忆,直接向上抛(由服务层转为 error 事件)
            raise
        else:
            # 正常结束:写回 memory
            if self._on_finish is not None:
                self._on_finish(final_text)


def _format_chat_history(chat_history: List[ChatMessage]) -> str:
    """
    把对话历史格式化成纯文本,追加到 system 消息尾部。

    Args:
        chat_history: ChatMessage 列表。

    Returns:
        追加到 system 末尾的格式化文本;若历史为空,返回空串。
    """
    if not chat_history:
        return ""
    lines = ["\n\n【对话历史】"]
    for msg in chat_history:
        role = "用户" if msg.role == MessageRole.USER else "助手"
        lines.append(f"{role}: {msg.content}")
    return "\n".join(lines)


# ============================================================
# 对话明细日志(config.CHAT.log_chat_detail 控制)
# ============================================================
#: 明细日志中单个检索节点的文本预览截断长度(字符数)
_NODE_PREVIEW_LIMIT: int = 500


def _log_block(title: str, content) -> None:
    """
    按统一格式打印一个阶段的明细日志(上下横线分隔,便于区分各阶段)。

    Args:
        title: 阶段标题。
        content: 阶段内容。
    """
    print("\n" + "=" * 70)
    print(f"【{title}】")
    print("=" * 70)
    print(content)


def _format_retrieved_nodes(nodes: List[NodeWithScore], total: int) -> str:
    """
    把检索节点格式化为可读文本(相似度分数 / 文件名 / 内容预览)。

    Args:
        nodes: 过滤后的命中节点。
        total: 过滤前的检索总数(用于展示相似度过滤效果)。

    Returns:
        格式化后的多行文本。
    """
    lines = []
    if total != len(nodes):
        lines.append(f"共检索 {total} 个节点,过滤低相关后保留 {len(nodes)} 个")
    else:
        lines.append(f"共检索 {len(nodes)} 个节点")
    if not nodes:
        lines.append("(无符合条件的节点)")
    for i, n in enumerate(nodes, 1):
        score = "?" if n.score is None else f"{n.score:.4f}"
        file_name = ""
        if n.node is not None and getattr(n.node, "metadata", None):
            file_name = (
                n.node.metadata.get("file_name")
                or n.node.metadata.get("file")
                or ""
            )
        text = (n.get_content() or "").strip()
        if len(text) > _NODE_PREVIEW_LIMIT:
            text = text[:_NODE_PREVIEW_LIMIT] + "...(截断)"
        lines.append(f"\n[{i}] score={score}  file={file_name or '-'}\n{text}")
    return "\n".join(lines)


def _node_source_label(node: NodeWithScore) -> str:
    """
    提取节点的来源信息(文件名 + 章节),拼成一行引用标签。

    用于:
    - 构造发给 LLM 的参考资料(带出处,便于回答末尾引用);
    - 调试日志展示。

    Args:
        node: 检索节点(含元数据)。

    Returns:
        形如 ``"【来源: oracle.md | 章节: 第二章 安装 > 2.2 安装步骤】"``
        的标签;没有元数据时返回空串。
    """
    if node.node is None:
        return ""
    meta = node.node.metadata or {}
    file_name = meta.get("file_name") or meta.get("file") or ""
    section = meta.get("section") or meta.get("header_path") or ""
    parts = []
    if file_name:
        parts.append(f"来源: {file_name}")
    if section:
        parts.append(f"章节: {section}")
    return f"【{' | '.join(parts)}】" if parts else ""


def _join_nodes_with_meta(nodes: List[NodeWithScore]) -> str:
    """
    把检索节点拼接成发给 LLM 的参考资料,每个节点带上来源标签。

    Args:
        nodes: 检索节点。

    Returns:
        拼接后的文本;无节点时返回 ``"(无参考资料)"``。
    """
    if not nodes:
        return "(无参考资料)"
    blocks = []
    for n in nodes:
        label = _node_source_label(n)
        text = n.get_content() or ""
        blocks.append(f"{label}\n{text}" if label else text)
    return "\n\n".join(blocks)


class CustomRAGChatEngine(BaseChatEngine):
    """
    完全自控的 RAG 对话引擎。

    与 LlamaIndex 内置 ``ContextChatEngine`` 的关键差异:
    - 显式将 ``context_str`` 渲染到 user 消息里,避免版本升级后模板被忽略。
    - system 消息只放 system_prompt + chat_history,职责清晰。
    - 调用 LLM 时直接传 ``List[ChatMessage]``,可被 RAGDebugHandler 完整捕获。
    """

    def __init__(
        self,
        retriever,
        llm: LLM,
        memory: BaseMemory,
        system_prompt: str,
        context_template: str,
        min_score: Optional[float] = None,
        log_detail: Optional[bool] = None,
    ) -> None:
        """
        Args:
            retriever: 任意实现了 ``retrieve(str) -> List[NodeWithScore]`` 的检索器。
            llm: LLM 实例。
            memory: 对话记忆(``ChatMemoryBuffer`` 等),可为 None。
            system_prompt: 系统提示词。
            context_template: user 消息模板,占位符 ``{context_str}`` ``{message}``。
            min_score: 检索节点相似度下限(0~1);低于该分数的节点视为不相关并丢弃,
                None 时不过滤。用于防止知识库外的问题把不相关内容当参考资料喂给 LLM。
            log_detail: 是否打印对话全链路明细日志(用户消息 / 检索结果 / 系统提示词 /
                最终发送内容 / 模型回复);None 时读取 ``config.CHAT.log_chat_detail``。
        """
        self._retriever = retriever
        self._llm = llm
        self._memory = memory
        self._system_prompt = system_prompt
        self._context_template = context_template
        self._min_score = min_score
        #: 全链路明细日志开关(None 时回落到 config.CHAT.log_chat_detail)
        self._log_detail = CHAT.log_chat_detail if log_detail is None else log_detail

    # ---------- BaseChatEngine 抽象方法 ----------
    @property
    def chat_history(self) -> List[ChatMessage]:
        """返回当前对话历史(来自 memory)。"""
        return self._memory.get() if self._memory else []

    def reset(self) -> None:
        """清空对话历史。"""
        if self._memory:
            self._memory.reset()

    # ---------- 内部工具方法 ----------
    def _retrieve_nodes(self, message: str) -> List[NodeWithScore]:
        """
        显式调用 retriever,并按 ``min_score`` 过滤低相关节点。
        走显式调用而不是 context 内部隐式调用,确保 RAGDebugHandler 能正确触发 RETRIEVE 事件。

        Args:
            message: 用户原始问题。

        Returns:
            命中节点(含相似度分数,低于 ``min_score`` 的已被丢弃)。
        """
        nodes = self._retriever.retrieve(message)
        total = len(nodes)
        if self._min_score is not None:
            # score 为 None 的节点保守保留(无法判断相关性时不误杀)
            nodes = [
                n for n in nodes
                if n.score is None or n.score >= self._min_score
            ]
        if self._log_detail:
            _log_block("① 前端发送的用户消息", message)
            _log_block("② 检索结果(Milvus)", _format_retrieved_nodes(nodes, total))
        return nodes

    def _build_messages(
        self,
        message: str,
        context_str: str,
        chat_history: List[ChatMessage],
    ) -> List[ChatMessage]:
        """
        显式拼装 system + user 两条消息。

        Args:
            message: 用户问题。
            context_str: 检索出的文本(已 join)。
            chat_history: 已有对话历史。

        Returns:
            准备送入 LLM 的消息列表。
        """
        # system: 提示词 + 格式化的历史
        system_content = self._system_prompt
        hist_str = _format_chat_history(chat_history)
        if hist_str:
            system_content = system_content + hist_str

        # user: 模板显式 format,占位符一定被替换
        user_content = self._context_template.format(
            context_str=context_str,
            message=message,
        )

        if self._log_detail:
            _log_block("③ RAG 系统提示词", self._system_prompt)
            _log_block(
                "④ 最终发送给大模型的完整消息",
                f"[system]\n{system_content}\n\n[user]\n{user_content}",
            )

        return [
            ChatMessage(role=MessageRole.SYSTEM, content=system_content),
            ChatMessage(role=MessageRole.USER, content=user_content),
        ]

    # ---------- 核心:同步聊天 ----------
    def chat(self, message: str) -> AgentChatResponse:
        """
        同步对话入口。

        流程:
            1) 调 retriever 拿节点
            2) 拼接 context_str
            3) 拼装 messages
            4) 调 LLM
            5) 写回 memory

        Args:
            message: 用户输入。

        Returns:
            AgentChatResponse,含 ``response`` 与 ``source_nodes``。
        """
        chat_history = self.chat_history

        # 1) 检索
        nodes = self._retrieve_nodes(message)

        # 2) 拼接 context(每个节点带来源标签:文件名 + 章节,便于回答末尾引用)
        context_str = _join_nodes_with_meta(nodes)

        # 3) 拼装消息
        messages = self._build_messages(message, context_str, chat_history)

        # 4) 调用 LLM
        chat_response: ChatResponse = self._llm.chat(messages)
        assistant_text = chat_response.message.content or ""
        if self._log_detail:
            _log_block("⑤ 大模型回复", assistant_text or "(空)")

        # 5) 更新记忆
        if self._memory is not None:
            self._memory.put(ChatMessage(role=MessageRole.USER, content=message))
            self._memory.put(
                ChatMessage(role=MessageRole.ASSISTANT, content=assistant_text)
            )

        return AgentChatResponse(
            response=assistant_text,
            source_nodes=list(nodes),
        )

    # ---------- BaseChatEngine 抽象方法(异步/流式) ----------
    async def achat(self, message: str) -> AgentChatResponse:
        """
        异步对话入口。

        实现简化:直接复用 ``chat()``。如果上游 LLM 自身提供 async 接口,
        可改为 ``await self._llm.achat(messages)``。

        Args:
            message: 用户输入。

        Returns:
            AgentChatResponse。
        """
        return self.chat(message)

    def stream_chat(self, message: str) -> SimpleStreamChatResponse:
        """
        流式对话入口(真正的 token 级流式)。

        流程与 ``chat()`` 相同,差别在于第 4 步:
        迭代 ``self._llm.stream_chat(messages)``,边生成边 yield,
        生成完毕后统一写回 memory 并返回 source_nodes。

        Args:
            message: 用户输入。

        Returns:
            SimpleStreamChatResponse,其 ``response_gen`` 可迭代拿增量文本,
            ``source_nodes`` 为本次检索节点。
        """
        nodes = self._retrieve_nodes(message)
        return self._stream_from_nodes(message, nodes)

    def _stream_from_nodes(
        self, message: str, nodes: List[NodeWithScore]
    ) -> SimpleStreamChatResponse:
        """
        基于已检索节点直接流式生成(避免重复检索)。

        Args:
            message: 用户输入。
            nodes: 已检索出的节点(外部可先推送 sources 再调用本方法)。

        Returns:
            SimpleStreamChatResponse。
        """
        chat_history = self.chat_history
        context_str = _join_nodes_with_meta(nodes)
        messages = self._build_messages(message, context_str, chat_history)
        chat_iter = self._llm.stream_chat(messages)

        def _on_finish(assistant_text: str) -> None:
            """流正常结束:把完整回复写回 memory。"""
            if self._log_detail:
                _log_block("⑤ 大模型回复(流式)", assistant_text or "(空)")
            if self._memory is not None:
                self._memory.put(
                    ChatMessage(role=MessageRole.USER, content=message)
                )
                self._memory.put(
                    ChatMessage(role=MessageRole.ASSISTANT, content=assistant_text)
                )

        return SimpleStreamChatResponse(
            chat_stream=chat_iter,
            source_nodes=list(nodes),
            on_finish=_on_finish,
        )

    async def astream_chat(self, message: str) -> SimpleStreamChatResponse:
        """
        异步流式对话入口(当前为同步实现的直接包装)。

        Args:
            message: 用户输入。

        Returns:
            SimpleStreamChatResponse。
        """
        return self.stream_chat(message)
