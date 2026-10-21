# Retained text-loading/flattening helpers. The active runner is scripts/run_extraction_agent.py; older extraction APIs expected by some tests are absent.
"""从 PDF / XML / Markdown 文档中抽取结构化数据。

与结构化通道（parser/therasabdab.py）的区别只在字段值从哪里来：
那边靠 docs/Mapping/*.yaml 的列名映射，这边靠 Claude Code 通读全文
（抽取规则见 .claude/skills/extract-cart-data/SKILL.md）。
两边最后都产出 NormalizedData。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from .basemodel import NormalizedData
from .measurements import normalize_rows
from .schema_models import ExtractionSchema, load_schema

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

    # Read PDF text page by page using PyMuPDF.
    if suffix == ".pdf":
        import pymupdf

        # Close the PDF after extracting text from all pages.
        with pymupdf.open(path) as document:
            # Build mapped values from document.
            return "\n".join(page.get_text() for page in document)

    # Read XML as text and remove the explicitly configured boilerplate sections.
    if suffix in {".xml", ".nxml"}:
        return strip_xml_boilerplate(path.read_text(encoding="utf-8"))

    # Markdown is already plain text; retain its contents.
    if suffix in {".md", ".markdown"}:
        return path.read_text(encoding="utf-8")

    raise ValueError(
        f"不支持的文件格式：{path.suffix}"
        "（只支持 .pdf / .xml / .nxml / .md / .markdown）"
    )

def _unkv(value: Any) -> Any:
    """把 [{"key": k, "value": v}, ...] 还原成 {k: v}；其他值原样返回。

    modules 之类的列表每项有四个键，不会被误认成键值对。
    """
    # Convert only exact key/value-pair lists; structured module lists must stay lists.
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, dict) and set(item) == {"key", "value"} for item in value)
    ):
        # Build mapped values from value.
        return {item["key"]: item["value"] for item in value}
    return value


def _evidence_data(
    evidence,
    *,
    prefix: str | None,
    shared: tuple[str, ...],
    owner_ids: dict[str, str | None],
    fk_columns: dict[str, str],
) -> dict[str, Any] | None:
    """证据行。出处为空就丢弃这一行（返回 None）。

    prefix 决定字段前缀：car 的 exhaustion_phenotype 写成 car.exhaustion_phenotype，
    manufacturing 的写成 manufacturing.exhaustion_phenotype —— 两者同名不同列。
    """
    # Discard evidence lacking a usable source identifier.
    if not (getattr(evidence, "source_id", None) or "").strip():
        logger.warning("证据缺少出处（source_id 为空），丢弃该行：%r", evidence.model_dump())
        return None
    dumped = evidence.model_dump()
    data: dict[str, Any] = {"record_id": str(uuid4())}
    # Copy shared provenance fields without an entity prefix.
    for name in shared:
        data[name] = _unkv(dumped[name])
    # Entity-specific measurements need a prefix to avoid collisions across owners.
    if prefix is not None:
        # Inspect every model field for entity-specific measurements.
        for name in type(evidence).model_fields:
            # Do not duplicate shared provenance fields under an entity prefix.
            if name not in shared:
                data[f"{prefix}.{name}"] = _unkv(dumped[name])

    # 三个外键列都写出来，只有归属的那个有值 —— 结果能直接对着 Evidence.yaml 看。
    for kind, column in fk_columns.items():
        data[column] = owner_ids.get(kind)
    return data


def _at(ids: list[str], index: int) -> str | None:
    """按序号取实体编号；越界或负数返回 None。"""
    # Use ids[index] when 0 <= index < len(ids); otherwise use None.
    return ids[index] if 0 <= index < len(ids) else None



def flatten(result, schema: ExtractionSchema | None = None) -> list[NormalizedData]:
    """把模型返回的嵌套结果拆成一行行 NormalizedData。

    输出顺序：binder、car、manufacturing、abc_combination_db1，最后 evidence。
    被引用的实体必须先出现，后面引用它的行才有编号可填。
    """
    # Prefer schema; if empty or absent, fall back to load_schema().
    schema = schema or load_schema()
    # Build mapped values from schema.entities.
    fk_columns = {entity.kind: entity.fk_column for entity in schema.entities}
    shared = schema.shared_evidence_fields

    entity_rows: list[NormalizedData] = []
    combination_rows: list[NormalizedData] = []
    evidence_rows: list[NormalizedData] = []
    # Build mapped values from schema.entities.
    ids: dict[str, list[str]] = {entity.kind: [] for entity in schema.entities}

    # Create all entity IDs before resolving evidence and combinations.
    for entity in schema.entities:
        # Assign one UUID per extracted entity in its original list order.
        for item in getattr(result, f"{entity.kind}s"):
            entity_id = str(uuid4())
            ids[entity.kind].append(entity_id)

            data: dict[str, Any] = {entity.id_column: entity_id}
            # Copy the entity payload while separating nested evidence for later emission.
            for name, value in item.model_dump(exclude={"evidence"}).items():
                data[name] = _unkv(value)
            entity_rows.append(NormalizedData(table=entity.kind, data=data))

            # Build each observation with the UUID of its actual owning entity.
            for evidence in item.evidence:
                row = _evidence_data(
                    evidence, prefix=entity.kind, shared=shared,
                    owner_ids={entity.kind: entity_id}, fk_columns=fk_columns,
                )
                # Append only evidence rows with usable source provenance.
                if row is not None:
                    evidence_rows.append(
                        NormalizedData(table=schema.evidence_table, data=row))

    # Resolve each combination's entity indices after entity IDs have been generated.
    for position, combination in enumerate(result.combinations):
        # Build mapped values from schema.entities.
        owner_ids = {
            entity.kind: _at(ids[entity.kind],
                             getattr(combination, f"{entity.kind}_index"))
            for entity in schema.entities
        }
        # Drop combinations with invalid entity indices rather than fabricate a relationship.
        if any(value is None for value in owner_ids.values()):
            # Build mapped values from schema.entities.
            logger.warning(
                "组合 #%d 的序号越界，丢弃：%s",
                position,
                {entity.kind: (getattr(combination, f"{entity.kind}_index"),
                               len(ids[entity.kind])) for entity in schema.entities},
            )
            continue

        combination_data: dict[str, Any] = {"combination_id": str(uuid4())}
        # Copy all resolved A/B/C owner IDs into the combination.
        for entity in schema.entities:
            combination_data[entity.id_column] = owner_ids[entity.kind]
        # Copy non-index combination attributes without exposing model-local references.
        for name, value in combination.model_dump(
            exclude={"experiments"} | {f"{e.kind}_index" for e in schema.entities}
        ).items():
            combination_data[name] = _unkv(value)
        combination_rows.append(
            NormalizedData(table=schema.combination_table, data=combination_data))

        # 组合实验只产出一行 evidence，三个外键都填上。
        for experiment in combination.experiments:
            row = _evidence_data(
                experiment, prefix=None, shared=shared,
                owner_ids=owner_ids, fk_columns=fk_columns,
            )
            # Keep only combination observations with source provenance.
            if row is not None:
                evidence_rows.append(
                    NormalizedData(table=schema.evidence_table, data=row))

    return normalize_rows(entity_rows + combination_rows + evidence_rows, schema)
