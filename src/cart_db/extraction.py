"""Utilities for extracting content from source documents."""

from typing import Any, Literal

import pymupdf
from pydantic import BaseModel


class Source(BaseModel):
    source_id: str | None
    source_type: Literal["literature"]
    evidence: str


class NormalizedData(BaseModel):
    record_type: Literal["binder", "car", "manufacturing", "combination"]
    data: dict[str, Any] #Do not care about the content for now
    source: Source  


class ExtractionResult(BaseModel):
    records: list[NormalizedData]


def load_pdf(pdf_file: str) -> str:
    with pymupdf.open(pdf_file) as doc:
        return "".join(page.get_text() for page in doc)


def load_xml(xml_file: str) -> str:
    """Read an XML file and return its raw content."""
    with open(xml_file, "r", encoding="utf-8") as f:
        return f.read()


def extract_article_data(article: str) -> list[dict]:
    from .llm import extract

    result = extract(
        schema=ExtractionResult,
        document=article,
        system_prompt=(
            "Extract binder, car, manufacturing, and combination records. "
            "Return normalized schema field names in data. "
            "Use only information stated in the article. "
            "For source, include the source ID if present, set source_type to "
            "literature, and quote the supporting text as evidence."
        ),
        purpose="article_extraction",
    )
    return [record.model_dump() for record in result.records]

