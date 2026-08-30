"""从 PDF / XML / Markdown 文档中抽取结构化数据。

与结构化通道（parser/therasabdab.py）的区别只在字段值从哪里来：
那边靠 docs/Mapping/*.yaml 的列名映射，这边靠模型通读全文。
两边最后都产出 NormalizedData。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import llm
from .basemodel import NormalizedData
from .config import cost_cny, settings
from .schema_models import SCHEMA_DIR, ExtractionSchema, load_schema

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

def _unkv(value: Any) -> Any:
    """把 [{"key": k, "value": v}, ...] 还原成 {k: v}；其他值原样返回。

    modules 之类的列表每项有四个键，不会被误认成键值对。
    """
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, dict) and set(item) == {"key", "value"} for item in value)
    ):
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
    """证据行。出处或证据等级为空就丢弃这一行（返回 None）。

    prefix 决定字段前缀：car 的 memory_phenotype 写成 car.memory_phenotype，
    manufacturing 的写成 manufacturing.memory_phenotype —— 两者同名不同列。
    """
    if not (getattr(evidence, "source_id", None) or "").strip():
        logger.warning("证据缺少出处（source_id 为空），丢弃该行：%r", evidence.model_dump())
        return None
    if not (getattr(evidence, "evidence_level", None) or "").strip():
        logger.warning("证据缺少证据等级，丢弃该行（出处 %s）", evidence.source_id)
        return None

    dumped = evidence.model_dump()
    data: dict[str, Any] = {"record_id": str(uuid4())}
    for name in shared:
        data[name] = _unkv(dumped[name])
    if prefix is not None:
        for name in type(evidence).model_fields:
            if name not in shared:
                data[f"{prefix}.{name}"] = _unkv(dumped[name])

    # 三个外键列都写出来，只有归属的那个有值 —— 结果能直接对着 Evidence.yaml 看。
    for kind, column in fk_columns.items():
        data[column] = owner_ids.get(kind)
    return data


def _at(ids: list[str], index: int) -> str | None:
    """按序号取实体编号；越界或负数返回 None。"""
    return ids[index] if 0 <= index < len(ids) else None


def flatten(result, schema: ExtractionSchema | None = None) -> list[NormalizedData]:
    """把模型返回的嵌套结果拆成一行行 NormalizedData。

    输出顺序：binder、car、manufacturing、abc_combination_db1，最后 evidence。
    被引用的实体必须先出现，后面引用它的行才有编号可填。
    """
    schema = schema or load_schema()
    fk_columns = {entity.kind: entity.fk_column for entity in schema.entities}
    shared = schema.shared_evidence_fields

    entity_rows: list[NormalizedData] = []
    combination_rows: list[NormalizedData] = []
    evidence_rows: list[NormalizedData] = []
    ids: dict[str, list[str]] = {entity.kind: [] for entity in schema.entities}

    for entity in schema.entities:
        for item in getattr(result, f"{entity.kind}s"):
            entity_id = str(uuid4())
            ids[entity.kind].append(entity_id)

            data: dict[str, Any] = {entity.id_column: entity_id}
            for name, value in item.model_dump(exclude={"evidence"}).items():
                data[name] = _unkv(value)
            entity_rows.append(NormalizedData(table=entity.kind, data=data))

            for evidence in item.evidence:
                row = _evidence_data(
                    evidence, prefix=entity.kind, shared=shared,
                    owner_ids={entity.kind: entity_id}, fk_columns=fk_columns,
                )
                if row is not None:
                    evidence_rows.append(
                        NormalizedData(table=schema.evidence_table, data=row))

    for position, combination in enumerate(result.combinations):
        owner_ids = {
            entity.kind: _at(ids[entity.kind],
                             getattr(combination, f"{entity.kind}_index"))
            for entity in schema.entities
        }
        if any(value is None for value in owner_ids.values()):
            logger.warning(
                "组合 #%d 的序号越界，丢弃：%s",
                position,
                {entity.kind: (getattr(combination, f"{entity.kind}_index"),
                               len(ids[entity.kind])) for entity in schema.entities},
            )
            continue

        combination_data: dict[str, Any] = {"combination_id": str(uuid4())}
        for entity in schema.entities:
            combination_data[entity.id_column] = owner_ids[entity.kind]
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
            if row is not None:
                evidence_rows.append(
                    NormalizedData(table=schema.evidence_table, data=row))

    return entity_rows + combination_rows + evidence_rows


PROMPT_PATH = Path(__file__).with_name("article_extraction_prompt.txt")

# article_extraction_prompt.txt 讲「抽什么」，这段讲「怎么摆」。
OUTPUT_GUIDE = """\
# Output Structure

Return one JSON object with four lists: `binders`, `cars`, `manufacturings`,
`combinations`.

- Nest every experimental result inside the entity it describes, in that
  entity's `evidence` list. Do not emit identifiers of your own; the pipeline
  assigns them.
- Every schema field of type `json` is expressed here as a list of
  `{"key": ..., "value": ...}` pairs, both written as strings.
- A combination refers to its three parts by zero-based position in the lists
  above: `binder_index: 0` means the first entry of `binders`. Emit a
  combination only when the source ties a binder, a CAR backbone and a
  manufacturing process to the same experimental system or product. A
  combination whose index does not exist will be discarded.
- Results measured on the combination as a whole go in that combination's
  `experiments` list, with the measured values as key/value pairs under
  `outcomes`.
- Field names here omit the table prefix used in Evidence.yaml: inside a
  binder's evidence write `kd`, not `binder.kd`.
- Use `null` for anything the source does not report. Never guess.
"""


def build_system_prompt() -> str:
    """抽取规则 + 全部表结构 + 输出格式说明。

    对每篇文档都完全一样，llm.py 会把它标为可缓存内容，
    第二篇起这部分按输入价的 0.1× 计费。
    """
    schema = "\n\n".join(
        f"# {path.name}\n{path.read_text(encoding='utf-8')}"
        for path in sorted(SCHEMA_DIR.glob("*.yaml"))
    )
    return "\n\n".join([
        PROMPT_PATH.read_text(encoding="utf-8"),
        f"# Database Schema\n\n```yaml\n{schema}\n```",
        OUTPUT_GUIDE,
    ])


def extract_document(
    path: str | Path,
    *,
    out_dir: str | Path | None = None,
    dry_run: bool = False,
) -> list[NormalizedData]:
    """读文件 → 调模型 → 拆平 → 写 data/normalised/<文件名>.jsonl。

    dry_run=True 时只估算 token 与费用，不调模型、不写文件，返回空列表。
    """
    path = Path(path)
    document = load_document(path)
    system_prompt = build_system_prompt()

    if dry_run:
        input_tokens = llm.count_tokens(document=document, system_prompt=system_prompt)
        logger.info(
            "%s：输入 %d token，预计约 ¥%.2f（输出按 3000 token 估）",
            path.name, input_tokens, cost_cny(input_tokens, 3000),
        )
        return []

    schema = load_schema()
    result = llm.extract(
        schema=schema.extraction,
        document=document,
        system_prompt=system_prompt,
        purpose="article_extraction",
    )
    rows = flatten(result, schema)

    out_dir = Path(out_dir) if out_dir else settings.data_root / "normalised"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{path.stem}.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.model_dump(), ensure_ascii=False) + "\n")

    logger.info("%s → %s（%d 行）", path.name, out_path, len(rows))
    return rows
