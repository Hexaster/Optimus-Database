"""从 docs/Schema/*.yaml 构建 LLM 的答题格式。

维护者只改 YAML：字段名、类型、可选值、可空性全部从 YAML 读。
Python 这边只保留三条 YAML 里表达不了的结构性约定 ——
哪几张是实体表、哪张是证据表、哪张是组合表。

主键与外键不出现在模型里：编号由 extraction.flatten() 生成，
让模型填就等于让它编。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, get_origin

import yaml
from pydantic import BaseModel, Field, create_model

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "Schema"

# YAML 里表达不了的结构性约定，只有这三条。
ENTITY_TABLES = ("binder", "car", "manufacturing")
EVIDENCE_TABLE = "evidence"
COMBINATION_TABLE = "abc_combination_db1"

_SCALARS: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "date": str,      # JSON 没有日期类型，用 ISO 8601 字符串
    "any": str,
}


class Measurement(BaseModel):
    """定量结果；kind 对应的字段和抽取规则见 Evidence.yaml 顶部。"""

    kind: Literal[
        "single_value", "range", "mean_with_standard_deviation",
        "mean_with_standard_error", "plus_minus_unspecified",
        "greater_than", "greater_than_or_equal",
        "less_than", "less_than_or_equal",
    ]
    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    error: float | None = None
    unit: str | None = None
    raw: str


@dataclass(frozen=True)
class EntitySpec:
    """一张实体表，以及挂在它下面的证据模型。"""

    kind: str                      # "binder" / "car" / "manufacturing"
    id_column: str                 # "binder_id"
    fk_column: str                 # evidence 表里的列名 "binder.binder_id"
    model: type[BaseModel]
    evidence_model: type[BaseModel]


@dataclass(frozen=True)
class ExtractionSchema:
    """构建好的一整套模型，外加 flatten() 需要的元信息。"""

    tables: dict[str, dict]
    extraction: type[BaseModel]
    entities: tuple[EntitySpec, ...]
    shared_evidence_fields: tuple[str, ...]
    evidence_table: str
    combination_table: str
    # 每张表单独一次 LLM 调用；每个模型只带 extraction 上同名同类型的那一个字段。
    # 顺序固定：binders, cars, manufacturings, combinations —— 后者的索引提示
    # 依赖前三者已经抽取完毕。
    requests: tuple[tuple[str, type[BaseModel]], ...]


def _camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.replace(".", "_").split("_"))


def _load_tables(schema_dir: Path) -> dict[str, dict]:
    """读整个目录，返回 {表名: fields 定义}。"""
    tables: dict[str, dict] = {}
    for path in sorted(schema_dir.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key, body in document.items():
            tables[body.get("table", key)] = body.get("fields") or {}
    return tables


def _annotation(spec: dict, *, nested_name: str) -> Any:
    """把一条 YAML 字段定义翻译成 Python 类型标注。"""
    declared = spec.get("type")

    if declared == "measurement":
        return Measurement | None if spec.get("nullable", True) else Measurement

    if declared == "json":
        if "item_schema" in spec:
            model = _build_model(nested_name, spec["item_schema"])
            if spec.get("shape") == "object":
                return model | None if spec.get("nullable") else model
            return list[model]
        item_type = _SCALARS.get(spec.get("item_type"))
        if item_type is not None:                  # YAML 可以写 item_type: string
            return list[item_type]
        # 没有结构约定的 json 字段：强制格式模式不允许「内容任意的对象」，
        # 键值对列表会在 20+ 个可空字段时把编译后的 grammar 撑爆（见阻塞报告），
        # 改成一段自由文本，交给模型自己组织格式。
        return str

    if spec.get("allowed_values"):
        return Literal[tuple(spec["allowed_values"])]

    return _SCALARS.get(declared, str)


def _build_model(name: str, fields: dict, *, skip_keys: bool = False) -> type[BaseModel]:
    """按 YAML 构建模型；可空字段省略时为 None，必需列表仍允许空列表。"""
    definitions: dict[str, tuple] = {}
    for field_name, spec in fields.items():
        if not isinstance(spec, dict):
            continue
        if skip_keys and spec.get("key") in {"primary", "foreign"}:
            continue
        annotation = _annotation(spec, nested_name=f"{name}{_camel(field_name)}")
        if spec.get("nullable", True):
            annotation = annotation | None
        if get_origin(annotation) is list and not spec.get("nullable", True):
            definitions[field_name] = (annotation, Field(default_factory=list))
        else:
            definitions[field_name] = (annotation, Field(default=spec.get("default")))
    return create_model(name, **definitions)


def _split_evidence(fields: dict) -> tuple[dict, dict[str, dict]]:
    """把证据表拆成「共享字段」和「按前缀分组的字段」。

    car.exhaustion_phenotype 与 manufacturing.exhaustion_phenotype 同名不同表，
    分组正是为了让它们落进两个不同的模型。
    """
    shared: dict[str, dict] = {}
    grouped: dict[str, dict] = {}
    for name, spec in fields.items():
        if "." in name:
            prefix, bare = name.split(".", 1)
            grouped.setdefault(prefix, {})[bare] = spec
        else:
            shared[name] = spec
    return shared, grouped


def load_schema(schema_dir: Path | None = None) -> ExtractionSchema:
    """读 docs/Schema/*.yaml，构建整套答题格式。

    薄封装：把参数归一化成同一个值后再进缓存，让 load_schema()、
    load_schema(None)、load_schema(SCHEMA_DIR) 命中同一条缓存、
    返回同一个对象 —— lru_cache 按字面参数取键，不按解析后的默认值取键，
    否则这几种写法会各自建一套结构相同但不是同一个类的模型，
    下游用 `is`/`isinstance` 比较模型类时会静默出错。
    """
    return _load_schema_cached(schema_dir or SCHEMA_DIR)


@lru_cache(maxsize=4)
def _load_schema_cached(schema_dir: Path) -> ExtractionSchema:
    tables = _load_tables(schema_dir)
    shared_fields, grouped = _split_evidence(tables[EVIDENCE_TABLE])

    entities: list[EntitySpec] = []
    root_fields: dict[str, tuple] = {}

    for kind in ENTITY_TABLES:
        prefixed = grouped[kind]
        overlap = set(prefixed) & set(shared_fields)
        if overlap:
            raise ValueError(
                f"{EVIDENCE_TABLE} 表中 {kind}.* 的字段 {sorted(overlap)} 与共享字段重名，"
                "会互相覆盖，请在 YAML 里改名"
            )

        evidence_model = _build_model(
            f"{_camel(kind)}Evidence", {**shared_fields, **prefixed}, skip_keys=True,
        )
        entity_model = create_model(
            _camel(kind),
            __base__=_build_model(_camel(kind), tables[kind], skip_keys=True),
            evidence=(list[evidence_model], Field(default_factory=list)),
        )
        id_column = next(
            name for name, spec in tables[kind].items()
            if isinstance(spec, dict) and spec.get("key") == "primary"
        )
        fk_name = next(
            name for name, spec in prefixed.items()
            if isinstance(spec, dict) and spec.get("key") == "foreign"
        )

        entities.append(EntitySpec(
            kind=kind, id_column=id_column, fk_column=f"{kind}.{fk_name}",
            model=entity_model, evidence_model=evidence_model,
        ))
        root_fields[f"{kind}s"] = (list[entity_model], Field(default_factory=list))

    # 组合表：外键列换成序号，指向根模型上对应的列表。
    combination_definitions: dict[str, tuple] = {}
    for name, spec in tables[COMBINATION_TABLE].items():
        if not isinstance(spec, dict) or spec.get("key") == "primary":
            continue
        if spec.get("key") == "foreign":
            target = str(spec.get("references") or spec.get("to", "")).split(".")[0]
            combination_definitions[f"{target}_index"] = (int, ...)
            continue
        annotation = _annotation(spec, nested_name=f"Combination{_camel(name)}")
        if spec.get("nullable", True):
            annotation = annotation | None
        combination_definitions[name] = (annotation, Field(default=None))

    evidence_base = _build_model("EvidenceBase", shared_fields, skip_keys=True)
    combination_definitions["experiments"] = (
        list[evidence_base], Field(default_factory=list),
    )
    combination_model = create_model("Combination", **combination_definitions)
    root_fields["combinations"] = (list[combination_model], Field(default_factory=list))

    # 每次 LLM 调用只填 extraction 上的一个字段：整份 Extraction 一次性提交
    # 会让强制格式的 grammar 超出接口上限（见阻塞报告）。字段名与标注跟
    # extraction 模型上的完全一致，flatten() 消费的仍是拼回去的完整 Extraction。
    requests = tuple(
        (field_name, create_model(f"{_camel(field_name)}Request",
                                   **{field_name: root_fields[field_name]}))
        for field_name in ("binders", "cars", "manufacturings", "combinations")
    )

    return ExtractionSchema(
        tables=tables,
        extraction=create_model("Extraction", **root_fields),
        entities=tuple(entities),
        shared_evidence_fields=tuple(evidence_base.model_fields),
        evidence_table=EVIDENCE_TABLE,
        combination_table=COMBINATION_TABLE,
        requests=requests,
    )
