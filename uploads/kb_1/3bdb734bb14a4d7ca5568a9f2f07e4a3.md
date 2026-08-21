# llamaindex-loader

> 基于 **LlamaIndex** 的多格式文档 → 切分 → 向量化(Milvus)→ RAG 对话 完整流水线，支持 Web 界面与 RAGAS 评估。

---

## 1. 项目简介

本项目演示了如何用 LlamaIndex 解析 **Word / Excel / PDF / Txt / Markdown / HTML / JSON / Web** 等多种数据源,
经过切分后写入 **Milvus** 向量数据库,并通过 **OpenAI 兼容的 LLM** 实现带记忆的检索增强对话(RAG Chat)。

适合作为企业内部知识库、文档问答机器人、客服助手的脚手架。

**核心特性**:
- **多格式解析** —— Word/Excel/PDF/MD/HTML/JSON/Web,以及通过 anydoc 支持 PPT/RTF/EPUB/CSV 等更多格式
- **多种切分器** —— 句子、Token、Markdown、HTML、JSON、代码、语义切分
- **Milvus 持久化** —— 嵌入式(零依赖)与集群模式皆可
- **OpenAI 兼容 LLM** —— 支持 DeepSeek / 通义千问 / Ollama / vLLM / dmxapi 等
- **两种对话模式** —— 多轮问题改写(Condense)与原文直接检索(自实现引擎)
- **Web 界面** —— FastAPI + Vue3 前端，支持多知识库管理、批量文档上传、RAG 对话
- **全链路 Debug 日志** —— 系统提示词 / 检索节点 / LLM prompt / 模型返回 一键打印
- **三档配置优先级** —— 调用参数 > `config.py` > 环境变量

---

## 2. 架构

```
┌────────────────────────┐
│  dataLoader (解析)     │  Word / Excel / PDF / Txt / MD / HTML / JSON / Web
└──────────┬─────────────┘
           │  List[Document]
           ▼
┌────────────────────────┐
│  spliter   (切分)      │  Sentence / Token / Markdown / HTML / JSON / Code / Semantic
└──────────┬─────────────┘
           │  List[BaseNode]
           ▼
┌────────────────────────────────────────────────┐
│  vectorStore (Milvus + 对话)                    │
│   ├── milvus_store.py  : 写入/加载/自检        │
│   ├── callbacks.py     : RAGDebugHandler       │
│   ├── custom_engine.py : CustomRAGChatEngine   │
│   └── chat.py          : build_chat_engine()   │
└──────────┬─────────────────────────────────────┘
           │  VectorStoreIndex
           ▼
┌────────────────────────┐
│  chat(检索对话)        │  Retriever → Context → LLM → 回答
└────────────────────────┘
```

**Web 架构**:
```
frontend/ (Vue3 + Element Plus)          用户界面
        │  /api (vite 代理 -> 8000)
        ▼
api/ (FastAPI)                            REST 服务
 ├── routers/kb.py        知识库 CRUD
 ├── routers/documents.py 批量上传 / 状态轮询 / 删除 / 重试
 ├── routers/chat.py      会话管理 / RAG 问答
 └── services/            后台解析(线程池) / 引擎缓存
        │
        ├── MySQL(kb_rag)   知识库 / 文档 / 会话 / 消息 元数据
        └── Milvus(kb_{id}) 每个知识库一个 collection,数据隔离
```

---

## 3. 快速开始

### 3.1 安装依赖

```bash
# 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\activate           # Windows
# source .venv/bin/activate        # Linux/Mac

# 安装后端依赖
pip install -r requirements.txt

# 本地嵌入式 Milvus
pip install pymilvus[milvus_lite]

# 安装前端依赖
cd frontend && npm install
```

### 3.2 配置环境变量

```bash
# OpenAI 兼容的 LLM / Embedding
set OPENAI_API_KEY=sk-xxxxxx
set OPENAI_BASE_URL=https://api.openai.com/v1
set LLM_MODEL=gpt-4o-mini
set EMBED_MODEL=text-embedding-3-small
set EMBED_DIM=1536

# Milvus(嵌入式本地模式)
set MILVUS_URI=./milvus_llamaindex.db
set MILVUS_COLLECTION=llamaindex_rag
set MILVUS_OVERWRITE=true

# MySQL(用于 Web 界面)
set MYSQL_HOST=127.0.0.1
set MYSQL_PORT=3306
set MYSQL_USER=root
set MYSQL_PASSWORD=root
set MYSQL_DB=kb_rag
```

> 完整配置字段见 [config.py](./config.py) 和 [api/api_config.py](./api/api_config.py)。

### 3.3 初始化数据库

```bash
mysql -uroot -p < sql/init.sql
```

### 3.4 启动服务

**方式 A: CLI 模式(脚本化)**

```python
from main import ingest_file, start_chat
from vectorStore import load_existing_index

# 解析单文件 -> 切分 -> 入库
index = ingest_file("Oracle-19c-安装及常用命令.md")

# 启动对话
start_chat(index, enable_question_rewriting=False, debug=True)
```

**方式 B: Web 界面(推荐)**

```bash
# 启动后端 API
python run_server.py
# 访问 http://localhost:8000/docs 查看 API 文档

# 启动前端(新终端)
cd frontend
npm run dev
# 访问 http://localhost:5173
```

---

## 4. 核心模块

### 4.1 `dataLoader` — 文档解析

| 函数 | 用途 |
|---|---|
| `load_word(path)` | `.docx` |
| `load_excel(path)` | `.xlsx` / `.xls` |
| `load_pdf_auto(path, backend="pymupdf")` | `.pdf`(推荐 pymupdf) |
| `load_txt/markdown/html/json(path)` | 文本类文档 |
| `load_anydoc(path)` | PPT/RTF/EPUB/CSV 等(需安装 anydoc) |
| `load_web(urls)` | 网页抓取 |
| `auto_load(path)` | 按后缀自动选 loader |
| `load_directory(dir)` | 批量加载目录 |

### 4.2 `spliter` — 文档切分

| 函数 | 说明 |
|---|---|
| `split_by_sentence(docs, chunk_size=1024, chunk_overlap=200)` | 句子切分(**默认**) |
| `split_by_token(docs, chunk_size=512)` | Token 切分 |
| `split_markdown/html/json(docs)` | 结构化切分 |
| `split_code(docs, language="python")` | 代码切分 |
| `auto_split(docs, doc_type="text")` | 按类型自动选 splitter |

### 4.3 `vectorStore` — Milvus + 对话

| 函数 | 说明 |
|---|---|
| `configure_settings(embed_model, llm, chunk_size, chunk_overlap)` | 全局注册配置 |
| `build_milvus_store(collection_name, overwrite)` | 构造 Milvus 客户端 |
| `create_index(nodes, milvus_store)` | 写入 Milvus 并构建索引 |
| `load_existing_index(milvus_store)` | 加载已存在的 collection |
| `build_chat_engine(index, enable_question_rewriting, debug)` | 构造对话引擎 |
| `CustomRAGChatEngine` | 自实现的 Chat Engine |
| `RAGDebugHandler` | 全链路日志回调 |

---

## 5. Web 界面功能

### 5.1 知识库管理

- **创建知识库**:指定名称、描述、切分器类型、chunk 参数
- **编辑/删除**:修改配置或删除知识库(连带 Milvus 数据)
- **多知识库隔离**:每个知识库对应独立的 Milvus collection(`kb_{id}`)

### 5.2 文档管理

- **批量上传**:支持拖拽多选,单次可上传多个文件
- **格式支持**:Word/Excel/PDF/TXT/MD/HTML/JSON/PPT/RTF/EPUB/CSV 等
- **解析状态**:pending → processing → done/failed,前端 3s 轮询
- **失败重试**:解析失败的文档可一键重试
- **删除文档**:按文档粒度删除 Milvus 向量节点

### 5.3 RAG 对话

- **会话管理**:每个知识库可创建多个独立会话
- **RAG 引用**:回答附带引用来源(文本、相似度分数、文件名)
- **历史持久化**:MySQL 存储,服务重启后自动恢复
- **清空会话**:一键清空历史消息

### 5.4 API 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/kb` | 知识库列表 / 创建 |
| GET/PUT/DELETE | `/api/kb/{id}` | 知识库详情 / 更新 / 删除 |
| POST | `/api/kb/{id}/documents` | 批量上传文档 |
| GET | `/api/kb/{id}/documents` | 文档列表(含状态) |
| DELETE | `/api/kb/documents/{doc_id}` | 删除文档 |
| POST | `/api/kb/documents/{doc_id}/retry` | 失败重试 |
| GET/POST | `/api/chat/sessions` | 会话列表 / 创建 |
| GET | `/api/chat/sessions/{id}/messages` | 历史消息 |
| POST | `/api/chat/sessions/{id}/chat` | 发送消息,返回 `{answer, sources[]}` |
| POST | `/api/chat/sessions/{id}/clear` | 清空会话 |

---

## 6. 关键配置

### 6.1 对话模式

| 值 | 行为 | 引擎 |
|---|---|---|
| `enable_question_rewriting=True` | 多轮问题改写 | `CondenseQuestionChatEngine` |
| `enable_question_rewriting=False` (默认) | 保留原问题 | `CustomRAGChatEngine` |

### 6.2 配置优先级

调用参数 > `config.py` > 环境变量

```python
# 1. 调用时传参(最高优先级)
start_chat(index, enable_question_rewriting=False, debug=True)

# 2. 改 config.py(项目级默认)
CHAT.enable_question_rewriting = False

# 3. 环境变量(部署/CI)
set ENABLE_QUESTION_REWRITING=false
```

### 6.3 切换 Embedding / LLM

- **DeepSeek**:`OPENAI_BASE_URL=https://api.deepseek.com/v1`,`LLM_MODEL=deepseek-chat`
- **通义千问**:`OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- **Ollama**:`OPENAI_BASE_URL=http://localhost:11434/v1`,`LLM_MODEL=qwen2.5`

> `EMBED_DIM` 必须与 Embedding 模型匹配(OpenAI `text-embedding-3-small` = 1536)。

---

## 7. 常见问题

**Q1. `ModuleNotFoundError: No module named 'milvus_lite'`?**
```bash
pip install pymilvus[milvus_lite] milvus_lite
```

**Q2. Embedding dimension mismatch?**
`EMBED_DIM` 必须与 Embedding 模型维度一致(OpenAI `text-embedding-3-small` = 1536)。

**Q3. 中文 PDF 乱码?**
切换后端:`load_pdf_auto("x.pdf", backend="pdfplumber")` 或 `"pymupdf"`。

**Q4. 想用本地 Embedding(BGE / M3E)?**
```bash
pip install sentence-transformers
```
在 `vectorStore/milvus_store.py` 的 `get_embed_model` 中改为 `HuggingFaceEmbedding`。

**Q5. 看不到 debug 日志?**
确认三处都开:① `start_chat(index, debug=True)` 或 ② `CHAT.debug = True` 或 ③ `RAG_DEBUG=true`。

**Q6. MySQL 连接失败?**
确认 MySQL 服务已启动,且 `sql/init.sql` 已执行。可用环境变量覆盖连接配置。

---

## 8. RAGAS 评测

```python
from ragasEvaluator import run_ragas_eval, RAGASEvaluator
from dataLoader import auto_load

# 一站式评测
docs = auto_load("data/sample.pdf")
result = run_ragas_eval(docs=docs, n_questions_per_chunk=2)
print(result["scores"])
```

**评估指标**:
- `faithfulness`:忠实度
- `answer_relevancy`:答案相关性
- `context_precision`:上下文精确率
- `context_recall`:上下文召回率

---

## 9. 项目结构

```
llamaindex-loader/
├── config.py                 # 统一配置
├── main.py                   # CLI 入口
├── run_server.py             # Web API 入口
├── requirements.txt          # 后端依赖
├── sql/init.sql              # MySQL 建表脚本
│
├── dataLoader/               # 文档解析
├── spliter/                  # 文档切分
├── vectorStore/              # 向量存储 + 对话
├── hybridRetriever/          # 混合检索
├── ragasEvaluator/           # RAGAS 评测
│
├── api/                      # FastAPI 后端
│   ├── main.py               #   应用入口
│   ├── routers/              #   路由(kb/documents/chat)
│   ├── services/             #   业务逻辑(解析/对话)
│   ├── models.py             #   ORM 模型
│   └── database.py           #   数据库连接
│
└── frontend/                 # Vue3 前端
    ├── src/views/            #   页面组件
    ├── src/api/              #   API 封装
    └── package.json          #   前端依赖
```
