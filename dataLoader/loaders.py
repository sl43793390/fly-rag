"""
dataLoader.loaders
~~~~~~~~~~~~~~~~~~~~
使用 LlamaIndex 实现的多种文档解析器,统一返回 ``List[Document]``。

支持格式
--------
- Word  (.docx)        -> DocxReader
- Excel (.xlsx/.xls)   -> PandasExcelReader
- PDF   (.pdf)         -> PDFReader / PyMuPDFReader / PDFPlumberReader
- Txt   (.txt)         -> SimpleDirectoryReader
- Markdown (.md)       -> MarkdownReader
- HTML  (.html)        -> HTMLTagReader
- JSON  (.json)        -> JSONReader
- Web   (URL 列表)     -> BeautifulSoupWebReader / SimpleWebPageReader

对未识别后缀,可使用 ``auto_load`` 按后缀自动路由;
批量解析目录使用 ``load_directory``;
需要"只列文件不读内容"的流式场景使用 :func:`list_supported_files`。
"""
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Union

from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import Document
from llama_index.readers.file import (
    DocxReader,
    PandasExcelReader,
    PDFReader,
    PyMuPDFReader,
    MarkdownReader,
    HTMLTagReader,
)
from llama_index.readers.json import JSONReader
from llama_index.readers.web import (
    BeautifulSoupWebReader,
    SimpleWebPageReader,
)

logger = logging.getLogger(__name__)

# 项目支持的全部文件后缀(用于 auto_load / load_directory / list_supported_files)。
SUPPORTED_EXTS: tuple = (
    ".docx", ".xlsx", ".xls", ".pdf",
    ".txt", ".md", ".markdown",
    ".html", ".htm", ".json",
    # anydoc 支持的额外格式
    ".doc", ".docm",
    ".ppt", ".pps", ".pot", ".pptx", ".pptm", ".ppsx", ".ppsm",
    ".xlsm", ".xlsb",
    ".odt", ".ods", ".odp",
    ".rtf", ".epub", ".csv",
)

# `PDFPlumberReader` 在新版 llama-index-readers-file 中被移除,
# 这里做可选导入,失败时 ``load_pdf_plumber`` / ``load_pdf_auto(backend="pdfplumber")``
# 会抛 ``ImportError`` 提示用户安装旧版或换用其他后端。
try:
    from llama_index.readers.file import PDFPlumberReader
    _HAS_PDFPLUMBER = True
except ImportError:  # pragma: no cover - 依赖缺失分支
    PDFPlumberReader = None  # type: ignore[assignment]
    _HAS_PDFPLUMBER = False

# anydoc 是第三方库,支持多种办公文档格式并自动转换为 markdown。
# 这里做可选导入,失败时 ``load_anydoc`` 会抛 ``ImportError``。
try:
    import anydoc
    _HAS_ANYDOC = True
except ImportError:  # pragma: no cover - 依赖缺失分支
    anydoc = None  # type: ignore[assignment]
    _HAS_ANYDOC = False

# anydoc 支持的额外文件后缀(LlamaIndex 原生不支持的格式)。
ANYDOC_EXTS: tuple = (
    ".doc", ".docm",           # Word (扩展)
    ".ppt", ".pps", ".pot", ".pptx", ".pptm", ".ppsx", ".ppsm",  # PowerPoint
    ".xlsm", ".xlsb",          # Excel (扩展)
    ".odt", ".ods", ".odp",    # OpenDocument
    ".rtf",                    # Rich Text Format
    ".epub",                   # EPUB
    ".csv",                    # CSV
)

# html2text 是可选的(HTML -> Markdown,供 "markdown 标题切分" 使用)。
try:
    import html2text
    _HAS_HTML2TEXT = True
except ImportError:  # pragma: no cover - 依赖缺失分支
    html2text = None  # type: ignore[assignment]
    _HAS_HTML2TEXT = False

# 文件后缀 -> 切分器类型(doc_type)的统一映射。
# anydoc 支持的格式输出为 markdown,所以用 "markdown" 切分器。
# 供 main.ingest_* 与 api 层共用,消除重复定义。
EXT_DOC_TYPE_MAP: Dict[str, str] = {
    ".md": "markdown", ".markdown": "markdown",
    ".html": "html", ".htm": "html",
    ".json": "json",
    ".txt": "text",
    ".docx": "text",
    ".xlsx": "text", ".xls": "text",
    ".pdf": "text",
    # anydoc 支持的额外格式(输出为 markdown)
    ".doc": "markdown", ".docm": "markdown",
    ".ppt": "markdown", ".pps": "markdown", ".pot": "markdown",
    ".pptx": "markdown", ".pptm": "markdown",
    ".ppsx": "markdown", ".ppsm": "markdown",
    ".xlsm": "markdown", ".xlsb": "markdown",
    ".odt": "markdown", ".ods": "markdown", ".odp": "markdown",
    ".rtf": "markdown",
    ".epub": "markdown",
    ".csv": "markdown",
}


def get_doc_type(file_path: Union[str, Path]) -> str:
    """
    根据文件后缀返回推荐的切分器类型(doc_type)。

    Args:
        file_path: 文件路径(只取后缀)。

    Returns:
        ``EXT_DOC_TYPE_MAP`` 中的 doc_type;未识别的后缀返回 ``"text"``。
    """
    ext = Path(file_path).suffix.lower()
    return EXT_DOC_TYPE_MAP.get(ext, "text")


# ============================================================
# 1. Word (.docx)
# ============================================================
def load_word(file_path: Union[str, Path]) -> List[Document]:
    """
    解析 Word 文档 (.docx)。

    Args:
        file_path: .docx 文件路径。

    Returns:
        Document 列表(每个段落可能为一个 Document)。
    """
    reader = DocxReader()
    return reader.load_data(file=file_path)


# ============================================================
# 2. Excel (.xlsx / .xls)
# ============================================================
def load_excel(
    file_path: Union[str, Path],
    sheet_name: Optional[str] = None,
    pandas_config: Optional[Dict] = None,
) -> List[Document]:
    """
    解析 Excel 文档。

    Args:
        file_path: .xlsx / .xls 文件路径。
        sheet_name: 指定 sheet 名;为 None 时读取全部 sheet。
        pandas_config: 透传给 pandas.read_excel 的额外参数。

    Returns:
        Document 列表(每个 sheet 通常对应一个 Document)。
    """
    reader = PandasExcelReader(pandas_config=pandas_config or {})
    return reader.load_data(file=file_path, sheet_name=sheet_name)


# ============================================================
# 3. Txt
# ============================================================
def load_txt(
    file_path: Union[str, Path],
    encoding: str = "utf-8",
) -> List[Document]:
    """
    解析纯文本文件。

    Args:
        file_path: .txt 文件路径。
        encoding: 文件编码,默认 utf-8。

    Returns:
        Document 列表。
    """
    reader = SimpleDirectoryReader(
        input_files=[str(file_path)],
        encoding=encoding,
    )
    return reader.load_data()


# ============================================================
# 4. Markdown
# ============================================================
def load_markdown(file_path: Union[str, Path]) -> List[Document]:
    """
    解析 Markdown 文档,按章节切分 Document。

    Args:
        file_path: .md 文件路径。

    Returns:
        Document 列表。
    """
    reader = MarkdownReader()
    return reader.load_data(file=file_path)


# ============================================================
# 5. HTML (本地文件)
# ============================================================
def load_html(
    file_path: Union[str, Path],
    tag: str = "body",
    ignore_no_id: bool = False,
) -> List[Document]:
    """
    解析本地 HTML 文档(按标签提取正文内容)。

    Args:
        file_path: .html / .htm 文件路径。
        tag: 提取的 HTML 标签名,默认 ``"body"``。
            - ``"section"``:LlamaIndex 默认,只取带 id 的 <section>(一般 HTML
              没有 id,会返回空列表)。
            - ``"body"``:取整页正文,适合一般 HTML 文件。
            - ``"p"``/``"div"``/其它:按需选,多个同名标签会分别成 Document。
        ignore_no_id: 是否只保留带 ``id`` 的标签块,默认 ``False``(全保留)。
            注意 LlamaIndex 的语义:**``True`` 会丢掉所有没 id 的标签**,
            对 ``tag="body"`` 这种场景,通常应保持 ``False``。

    Returns:
        Document 列表。
    """
    reader = HTMLTagReader(tag=tag, ignore_no_id=ignore_no_id)
    return reader.load_data(file=file_path)


# ============================================================
# 6. JSON
# ============================================================
def load_json(
    file_path: Union[str, Path],
    levels_back: Optional[int] = None,
    collapse_length: Optional[int] = None,
    is_jsonl: bool = False,
) -> List[Document]:
    """
    解析 JSON / JSONL 文档。

    Args:
        file_path: .json / .jsonl 文件路径。
        levels_back: 回溯嵌套层数,0 表示全展开;None 表示把整段 JSON 展平
            为一个 Document。
        collapse_length: 当 ``levels_back`` 不为 None 时,超过该长度的 JSON
            片段会被折叠成单行。
        is_jsonl: 是否按 JSONL 解析。

    Returns:
        Document 列表。

    Note:
        新版 ``llama-index-readers-json`` 的参数名是 ``levels_back``(旧版叫
        ``levels``);用关键字传参最稳。
    """
    reader = JSONReader(
        levels_back=levels_back,
        collapse_length=collapse_length,
        is_jsonl=is_jsonl,
    )
    return reader.load_data(input_file=str(file_path))


# ============================================================
# 7. PDF —— 三种后端可选
# ============================================================
def load_pdf(
    file_path: Union[str, Path],
    return_full_document: bool = False,
) -> List[Document]:
    """
    解析 PDF(基于 pypdf,依赖最轻)。

    Args:
        file_path: .pdf 文件路径。
        return_full_document:
            - False:每页一个 Document
            - True :整本 PDF 合并为一个 Document

    Returns:
        Document 列表。
    """
    reader = PDFReader(return_full_document=return_full_document)
    return reader.load_data(file=file_path)


def load_pdf_pymupdf(file_path: Union[str, Path]) -> List[Document]:
    """
    使用 PyMuPDF 解析 PDF,对复杂排版/扫描件更友好(推荐)。

    Args:
        file_path: .pdf 文件路径。

    Returns:
        Document 列表。
    """
    reader = PyMuPDFReader()
    return reader.load_data(file_path=str(file_path))


def load_pdf_plumber(file_path: Union[str, Path]) -> List[Document]:
    """
    使用 pdfplumber 解析 PDF,擅长抽取表格(财务报表类 PDF 推荐)。

    Args:
        file_path: .pdf 文件路径。

    Returns:
        Document 列表。

    Raises:
        ImportError: 当前 ``llama-index-readers-file`` 版本未提供 ``PDFPlumberReader``。
    """
    if not _HAS_PDFPLUMBER:
        raise ImportError(
            "当前 llama-index-readers-file 未提供 PDFPlumberReader,"
            "请改用 backend='pymupdf' 或安装支持 pdfplumber 的旧版。"
        )
    reader = PDFPlumberReader()
    return reader.load_data(file=file_path)


def load_pdf_auto(
    file_path: Union[str, Path],
    backend: str = "pymupdf",
) -> List[Document]:
    """
    统一 PDF 解析入口。

    Args:
        file_path: .pdf 文件路径。
        backend: 后端类型,可选 ``"pymupdf"`` / ``"pdfplumber"`` / ``"pypdf"``。

    Returns:
        Document 列表。

    Raises:
        ValueError: backend 不是以上三种之一时抛出。
    """
    backend = backend.lower()
    if backend == "pymupdf":
        return load_pdf_pymupdf(file_path)
    if backend == "pdfplumber":
        return load_pdf_plumber(file_path)
    if backend == "pypdf":
        return load_pdf(file_path)
    raise ValueError(f"不支持的 PDF 后端: {backend}")


# ============================================================
# 8. anydoc —— 多格式办公文档解析(转换为 markdown)
# ============================================================
def load_anydoc(file_path: Union[str, Path]) -> List[Document]:
    """
    使用 anydoc 库解析多种办公文档格式,自动转换为 markdown。

    支持的格式:
        - Word: .doc, .docx, .docm
        - PowerPoint: .ppt, .pps, .pot, .pptx, .pptm, .ppsx, .ppsm
        - Excel: .xls, .xlsx, .xlsm, .xlsb
        - OpenDocument: .odt, .ods, .odp
        - Rich Text Format: .rtf
        - EPUB: .epub
        - CSV: .csv
        - PDF: .pdf

    Args:
        file_path: 任意受支持格式的文件路径。

    Returns:
        Document 列表(内容为 markdown 格式)。

    Raises:
        ImportError: 未安装 anydoc 库。
    """
    if not _HAS_ANYDOC:
        raise ImportError(
            "未安装 anydoc 库,请运行: pip install anydoc"
        )
    markdown_content = anydoc.to_markdown(str(file_path))
    return [Document(text=markdown_content)]


# ============================================================
# 9. Web
# ============================================================
def load_web(
    urls: List[str],
    use_bs4: bool = True,
) -> List[Document]:
    """
    抓取并解析网页内容。

    Args:
        urls: 网页 URL 列表。
        use_bs4:
            - True :使用 BeautifulSoupWebReader(更灵活,推荐)
            - False:使用 SimpleWebPageReader(简单抓取)

    Returns:
        Document 列表(每个 URL 通常对应一个 Document)。
    """
    if use_bs4:
        reader = BeautifulSoupWebReader()
    else:
        reader = SimpleWebPageReader(html_to_text=True)
    return reader.load_data(urls=urls)


# ============================================================
# 10. 通用入口(按后缀自动选择 Loader)
# ============================================================
def auto_load(file_path: Union[str, Path]) -> List[Document]:
    """
    根据文件后缀自动选择合适的 Loader。

    Args:
        file_path: 任意受支持格式的文件路径。

    Returns:
        Document 列表。

    Raises:
        ValueError: 后缀无法识别时退化为 SimpleDirectoryReader。
    """
    ext = Path(file_path).suffix.lower()
    # LlamaIndex 原生支持的格式
    mapping = {
        ".docx": load_word,
        ".xlsx": load_excel,
        ".xls": load_excel,
        ".pdf": load_pdf_auto,
        ".txt": load_txt,
        ".md": load_markdown,
        ".markdown": load_markdown,
        ".html": load_html,
        ".htm": load_html,
        ".json": load_json,
    }
    if ext in mapping:
        return mapping[ext](file_path)
    # anydoc 支持的额外格式
    if ext in ANYDOC_EXTS:
        return load_anydoc(file_path)
    # 未识别后缀退化为通用加载器
    return SimpleDirectoryReader(input_files=[str(file_path)]).load_data()


# ============================================================
# 10b. 转换为 markdown 后加载(供 "markdown 标题切分" 使用)
# ============================================================
#: 可通过 anydoc 转为 markdown 的后缀(含原生 loader 支持的 .docx/.xlsx/.xls/.pdf)。
ANYDOC_MARKDOWN_EXTS: tuple = ANYDOC_EXTS + (".docx", ".xlsx", ".xls", ".pdf")


def load_as_markdown(file_path: Union[str, Path]) -> List[Document]:
    """
    把任意受支持格式的文档转换为 markdown 后加载,供 "markdown 标题切分" 使用。

    用户明确选择 markdown 标题切分时,若上传的是其它格式(Word / PDF / PPT /
    HTML 等),先转换为 markdown(保留标题层级),再交给 MarkdownNodeParser 按
    标题切分;否则非 markdown 文档没有标题结构,切分会退化成普通文本块。

    转换路径(按优先级):
    - .md / .markdown    : 本身就是 markdown,直接解析;
    - anydoc 支持的格式  : 用 anydoc 转 markdown(含 .docx/.pdf/.pptx 等);
    - .html / .htm       : 用 html2text 转 markdown(标题 -> # 层级);
    - 其它(如 .txt/.json): 无可转换的标题结构,退回默认加载。

    Args:
        file_path: 任意受支持格式的文件路径。

    Returns:
        Document 列表(内容为 markdown 格式)。
    """
    ext = Path(file_path).suffix.lower()
    if ext in (".md", ".markdown"):
        return load_markdown(file_path)
    if ext in (".html", ".htm"):
        return _load_html_as_markdown(file_path)
    if ext in ANYDOC_MARKDOWN_EXTS:
        try:
            return load_anydoc(file_path)
        except Exception as exc:  # noqa: BLE001 - 转换失败退回默认解析
            logger.warning("anydoc 转 markdown 失败(%s),退回默认解析", exc)
    return auto_load(file_path)


def _load_html_as_markdown(file_path: Union[str, Path]) -> List[Document]:
    """用 html2text 把 HTML 转为 markdown;未安装 html2text 时退回 HTMLTagReader。"""
    if _HAS_HTML2TEXT:
        converter = html2text.HTML2Text()
        converter.body_width = 0  # 不强制按列换行
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            md = converter.handle(f.read())
        return [Document(text=md)]
    return load_html(file_path)


# ============================================================
# 11. 批量加载目录
# ============================================================
def load_directory(
    directory: Union[str, Path],
    recursive: bool = True,
    required_exts: Optional[List[str]] = None,
) -> List[Document]:
    """
    加载目录下所有支持的文档(默认递归)。

    警告:
        本函数会一次性把目录里所有文件读入内存。
        对超大型目录(数 GB 以上)请改用 :func:`list_supported_files` +
        ``index.insert(nodes)`` 的流式模式(见 ``main.ingest_directory``)。

    Args:
        directory: 目录路径。
        recursive: 是否递归子目录。
        required_exts: 限定加载的文件后缀;为 None 时加载全部支持格式(见 :data:`SUPPORTED_EXTS`)。

    Returns:
        Document 列表。
    """
    if required_exts is None:
        required_exts = list(SUPPORTED_EXTS)
    reader = SimpleDirectoryReader(
        input_dir=str(directory),
        recursive=recursive,
        required_exts=required_exts,
    )
    return reader.load_data()


def list_supported_files(
    directory: Union[str, Path],
    recursive: bool = True,
    required_exts: Optional[List[str]] = None,
) -> List[Path]:
    """
    只列出目录下受支持的文件路径,**不读取文件内容**。

    与 :func:`load_directory` 的区别:
        - ``load_directory`` 一次性把全目录载入,大目录(数 GB)易触发 OOM。
        - ``list_supported_files`` 只做文件系统扫描,内存常驻只与"文件数"相关,
          适合配合 ``index.insert(nodes)`` 做"逐文件加载-切分-入库"的流式入库。

    Args:
        directory: 目录路径。
        recursive: 是否递归子目录。
        required_exts: 限定后缀;为 None 时使用 :data:`SUPPORTED_EXTS`。

    Returns:
        排序后的 :class:`pathlib.Path` 列表。
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"不是有效目录: {directory}")

    ext_set = (
        tuple(e.lower() for e in required_exts)
        if required_exts is not None
        else SUPPORTED_EXTS
    )
    ext_set = tuple(e if e.startswith(".") else f".{e}" for e in ext_set)

    if recursive:
        # pathlib 的 rglob("*"):跨平台,符号链接按 os.walk 默认行为。
        # 加一层 is_file() 过滤,顺便跳过断链 / 隐藏文件目录项。
        matches = (
            p for p in directory.rglob("*")
            if p.is_file() and p.suffix.lower() in ext_set
        )
    else:
        matches = (
            p for p in directory.iterdir()
            if p.is_file() and p.suffix.lower() in ext_set
        )
    return sorted(matches)
