"""从 PDF / XML / Markdown 文档中抽取结构化数据。

与结构化通道（parser/therasabdab.py）的区别只在字段值从哪里来：
那边靠 docs/Mapping/*.yaml 的列名映射，这边靠模型通读全文。
两边最后都产出 NormalizedData。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# JATS 的参考文献、致谢、附录：占篇幅，不含可抽取内容，删掉纯粹省钱。
# 非贪婪匹配到最近的闭合标签；<back> 里嵌套的 <ref-list> 会被一并吃掉。
_BOILERPLATE = re.compile(
    r"<(ref-list|back|ack)\b[^>]*>.*?</\1\s*>",
    re.DOTALL | re.IGNORECASE,
)


def strip_xml_boilerplate(xml: str) -> str:
    """删掉 <ref-list> / <back> / <ack> 三类段落。"""
    return _BOILERPLATE.sub("", xml)


def load_document(path: str | Path) -> str:
    """把文档读成纯文本。

    .pdf        逐页取字
    .xml/.nxml  读原文，去掉参考文献等无关段落
    .md         已经是纯文本，原样读入
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        import pymupdf

        with pymupdf.open(path) as document:
            return "\n".join(page.get_text() for page in document)

    if suffix in {".xml", ".nxml"}:
        return strip_xml_boilerplate(path.read_text(encoding="utf-8"))

    if suffix in {".md", ".markdown"}:
        return path.read_text(encoding="utf-8")

    raise ValueError(
        f"不支持的文件格式：{path.suffix}"
        "（只支持 .pdf / .xml / .nxml / .md / .markdown）"
    )