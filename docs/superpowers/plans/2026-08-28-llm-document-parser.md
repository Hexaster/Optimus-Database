# 文献/专利 LLM Parser 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给定一个 PDF / XML / Markdown 文档，用 LLM 抽取其中的 Binder、CAR 骨架、制造工艺与实验证据，产出 `data/normalised/<文件名>.jsonl`。

**Architecture:** 从 `docs/Schema/*.yaml` **动态构建** Pydantic 模型，作为 LLM 的强制答题格式——字段名、类型、可选值、可空性全部从 YAML 读，维护者只改 YAML，不用碰 Python。模型输出嵌套结构（证据写在所属实体内部），`flatten()` 再拆成一行行 `NormalizedData`，顺手生成 UUID、回填外键、丢弃校验不过的行。`src/cart_db/llm.py` 一行都不改。

**Tech Stack:** Python 3.11（conda 环境 `fosun`）、Pydantic v2、PyYAML、Anthropic SDK（经 `llm.py` 封装）、pymupdf、pytest

**Spec:** `docs/superpowers/specs/2026-08-28-llm-document-parser-design.md`

> 设计文档第 3 节写的是「手写字段清单」，本计划改为从 YAML 动态构建（业务方 2026-08-30 决定）。目的一致——让接口层面卡死字段——但维护成本落在 YAML 上，而不是两处各维护一份。

## Global Constraints

- **不修改 `src/cart_db/llm.py`。** 调用、缓存、计费、每日上限都已就绪，直接用。
- **Python 侧不写死任何字段名。** 字段名、类型、`allowed_values`、`nullable` 一律从 `docs/Schema/*.yaml` 读。Python 里只保留三条 YAML 表达不了的结构性约定：哪几张是实体表、哪张是证据表、哪张是组合表。往数据库加字段 = 改 YAML，不改代码。
- **`evidence` 的带前缀字段按前缀分组建模。** `car.memory_phenotype` 与 `manufacturing.memory_phenotype` **同名不同表**——必须落在两个不同的模型里，绝不能合并成一个扁平的证据模型，否则其中一个会被静默覆盖。
- **`NormalizedData.table` 只列当前五张表**：`binder`、`car`、`manufacturing`、`evidence`、`abc_combination_db1`。结构化通道那边怎么改是另一条线的事。
- **Python 解释器统一用 conda 的 `fosun` 环境**：`/home/zzz010122/anaconda3/envs/fosun/bin/python`。仓库里没有 `.venv`，不要创建。
- **`nullable: false` 与 `default` 暂不下沉到模型。** 构建出来的字段一律可空，`contrary_evidence` 这类带默认值的非空列可能落成 `null`。本期只产出 jsonl、不写库，所以还不构成问题；等写 Postgres 的 loader 时在那一层补默认值。
- **写文件一律 `ensure_ascii=False`、UTF-8。**
- **日志用 `logging`**（`scripts/extract.py` 面向用户的输出除外）。

---

### Task 1: 从 YAML 构建模型（`schema_models.py`）

本任务是整个计划的核心。做完之后，「模型能填哪些字段」完全由 `docs/Schema/*.yaml` 决定。

**Files:**
- Create: `src/cart_db/schema_models.py`
- Create: `tests/test_schema_models.py`
- Create: `pytest.ini`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `docs/Schema/*.yaml`；测试里用到 `cart_db.llm._strict`
- Produces:
  - `KV`（键值对模型）
  - `EntitySpec(kind, id_column, fk_column, model, evidence_model)`
  - `ExtractionSchema(extraction, entities, shared_evidence_fields, evidence_table, combination_table)`
  - `load_schema(schema_dir: Path | None = None) -> ExtractionSchema`

- [ ] **Step 1: 补依赖**

`requirements.txt` 末尾追加：

```
pymupdf>=1.24        # extraction.load_document 从 PDF 取文字
pytest>=8.0          # tests/
```

```bash
/home/zzz010122/anaconda3/envs/fosun/bin/pip install pymupdf pytest
```

仓库根新建 `pytest.ini`：

```ini
[pytest]
pythonpath = src
testpaths = tests
```

- [ ] **Step 2: 写失败的测试**

创建 `tests/test_schema_models.py`：

```python
"""模型必须完全由 docs/Schema/*.yaml 决定 —— 改 YAML 就该改模型，不用动 Python。"""
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from cart_db import llm
from cart_db.schema_models import KV, load_schema

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "docs" / "Schema"


def _yaml_fields(filename: str, table_key: str) -> dict:
    doc = yaml.safe_load((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    return doc[table_key]["fields"]


def _entity(schema, kind):
    return next(e for e in schema.entities if e.kind == kind)


def test_shared_evidence_fields_come_from_yaml():
    fields = _yaml_fields("Evidence.yaml", "evidence")
    expected = {name for name in fields if "." not in name} - {"record_id"}
    assert set(load_schema().shared_evidence_fields) == expected


def test_each_prefix_becomes_its_own_evidence_model():
    schema = load_schema()
    fields = _yaml_fields("Evidence.yaml", "evidence")
    for kind in ("binder", "car", "manufacturing"):
        expected = {
            name.split(".", 1)[1] for name in fields if name.startswith(f"{kind}.")
        } - {f"{kind}_id"}
        model = _entity(schema, kind).evidence_model
        actual = set(model.model_fields) - set(schema.shared_evidence_fields)
        assert actual == expected, f"{kind} 的证据字段与 Evidence.yaml 不一致"


def test_same_field_name_under_two_prefixes_does_not_collide():
    """car.memory_phenotype 与 manufacturing.memory_phenotype 同名不同表。

    合并成一个扁平证据模型的话，其中一个会被静默覆盖，数据从此对不上。
    """
    schema = load_schema()
    car = _entity(schema, "car").evidence_model
    manufacturing = _entity(schema, "manufacturing").evidence_model

    assert "memory_phenotype" in car.model_fields
    assert "memory_phenotype" in manufacturing.model_fields
    assert car is not manufacturing
    # 只有 manufacturing 有 exhaustion_phenotype，只有 car 有 persistence
    assert "exhaustion_phenotype" in manufacturing.model_fields
    assert "exhaustion_phenotype" not in car.model_fields
    assert "persistence" in car.model_fields
    assert "persistence" not in manufacturing.model_fields


def test_entity_models_match_yaml():
    schema = load_schema()
    cases = [("binder", "Schema_A.yaml", "binder", "binder_id"),
             ("car", "Schema_B.yaml", "car", "car_id"),
             ("manufacturing", "Schema_C.yaml", "manufacturing", "manufacturing_id")]
    for kind, filename, table_key, pk in cases:
        expected = set(_yaml_fields(filename, table_key)) - {pk}
        model = _entity(schema, kind).model
        assert set(model.model_fields) - {"evidence"} == expected


def test_primary_and_foreign_keys_are_never_asked_of_the_model():
    """编号由 flatten() 生成，让模型填就等于让它编。"""
    schema = load_schema()
    assert "binder_id" not in _entity(schema, "binder").model.model_fields
    assert "binder_id" not in _entity(schema, "binder").evidence_model.model_fields
    assert "record_id" not in _entity(schema, "binder").evidence_model.model_fields


def test_allowed_values_become_a_closed_choice():
    model = _entity(load_schema(), "manufacturing").model
    assert model(t_cell_source="自体").t_cell_source == "自体"
    with pytest.raises(ValidationError):
        model(t_cell_source="autologous")


def test_json_fields_become_key_value_lists():
    model = _entity(load_schema(), "binder").model
    built = model(fr_cdr_regions=[KV(key="CDR-H3", value="ARDYW")])
    assert built.fr_cdr_regions[0].key == "CDR-H3"


def test_item_schema_becomes_a_nested_model():
    """Schema_B.yaml 的 car.modules 带 item_schema，应生成真正的子模型。"""
    model = _entity(load_schema(), "car").model
    built = model(modules=[{"module_type": "hinge", "source_molecule": "CD8a", "length": 45}])
    assert built.modules[0].module_type == "hinge"
    with pytest.raises(ValidationError):
        model(modules=[{"module_type": "不存在的模块类型"}])


def test_combination_foreign_keys_become_indices():
    combination = load_schema().extraction.model_fields["combinations"].annotation
    fields = combination.__args__[0].model_fields
    assert {"binder_index", "car_index", "manufacturing_index"} <= set(fields)
    assert "binder_id" not in fields
    assert "combination_id" not in fields
    assert "experiments" in fields


def test_root_model_has_four_lists():
    assert set(load_schema().extraction.model_fields) == {
        "binders", "cars", "manufacturings", "combinations"}


def test_strict_schema_is_not_empty():
    """回归测试：旧版 data: dict[str, Any] 会被 _strict 变成「一个字段都不准填」。"""
    schema = llm._strict(load_schema().extraction.model_json_schema())
    binder = next(v for k, v in schema["$defs"].items() if k == "Binder")
    assert binder["additionalProperties"] is False
    assert "vh_sequence" in binder["properties"]
    assert set(binder["required"]) == set(binder["properties"])


def test_new_yaml_field_appears_without_touching_python(tmp_path):
    """这条测试就是本任务存在的理由：加字段只改 YAML。"""
    schema_dir = tmp_path / "Schema"
    shutil.copytree(SCHEMA_DIR, schema_dir)
    path = schema_dir / "Schema_A.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n    isotype:\n      type: string\n      nullable: true\n"
          "      description: 抗体亚型。\n",
        encoding="utf-8",
    )
    model = _entity(load_schema(schema_dir), "binder").model
    assert "isotype" in model.model_fields


def test_prefix_group_overlapping_a_shared_field_is_rejected(tmp_path):
    schema_dir = tmp_path / "Schema"
    shutil.copytree(SCHEMA_DIR, schema_dir)
    path = schema_dir / "Evidence.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n    binder.citation:\n      type: string\n      nullable: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="与共享字段重名"):
        load_schema(schema_dir)
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/test_schema_models.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'cart_db.schema_models'`

- [ ] **Step 4: 写 `src/cart_db/schema_models.py`**

```python
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
from typing import Any, Literal

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


class KV(BaseModel):
    """强制格式模式不允许「内容任意的对象」，json 字段一律用键值对列表表达。"""

    key: str
    value: str


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

    extraction: type[BaseModel]
    entities: tuple[EntitySpec, ...]
    shared_evidence_fields: tuple[str, ...]
    evidence_table: str
    combination_table: str


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

    if declared == "json":
        if "item_schema" in spec:
            return list[_build_model(nested_name, spec["item_schema"])]
        item_type = _SCALARS.get(spec.get("item_type"))
        if item_type is not None:                  # YAML 可以写 item_type: string
            return list[item_type]
        return list[KV]

    if spec.get("allowed_values"):
        return Literal[tuple(spec["allowed_values"])]

    return _SCALARS.get(declared, str)


def _build_model(name: str, fields: dict, *, skip_keys: bool = False) -> type[BaseModel]:
    """按 YAML 字段定义造一个 Pydantic 模型。

    所有字段都给 None 默认值：llm._strict() 会给没有 required 的对象补上
    「全部字段必填」，所以这不会放松对模型的约束。
    """
    definitions: dict[str, tuple] = {}
    for field_name, spec in fields.items():
        if not isinstance(spec, dict):
            continue
        if skip_keys and spec.get("key") in {"primary", "foreign"}:
            continue
        annotation = _annotation(spec, nested_name=f"{name}{_camel(field_name)}")
        definitions[field_name] = (annotation | None, None)
    return create_model(name, **definitions)


def _split_evidence(fields: dict) -> tuple[dict, dict[str, dict]]:
    """把证据表拆成「共享字段」和「按前缀分组的字段」。

    car.memory_phenotype 与 manufacturing.memory_phenotype 同名不同表，
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


@lru_cache(maxsize=4)
def load_schema(schema_dir: Path | None = None) -> ExtractionSchema:
    """读 docs/Schema/*.yaml，构建整套答题格式。"""
    tables = _load_tables(schema_dir or SCHEMA_DIR)
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
        combination_definitions[name] = (annotation | None, None)

    evidence_base = _build_model("EvidenceBase", shared_fields, skip_keys=True)
    combination_definitions["experiments"] = (
        list[evidence_base], Field(default_factory=list),
    )
    combination_model = create_model("Combination", **combination_definitions)
    root_fields["combinations"] = (list[combination_model], Field(default_factory=list))

    return ExtractionSchema(
        extraction=create_model("Extraction", **root_fields),
        entities=tuple(entities),
        shared_evidence_fields=tuple(evidence_base.model_fields),
        evidence_table=EVIDENCE_TABLE,
        combination_table=COMBINATION_TABLE,
    )
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/test_schema_models.py -v`
Expected: 13 passed

若 `test_entity_models_match_yaml` 失败，以 YAML 为准查构建逻辑，不要改测试。

- [ ] **Step 6: 提交**

```bash
git add requirements.txt pytest.ini src/cart_db/schema_models.py tests/test_schema_models.py
git commit -m "feat: build extraction models from docs/Schema YAML at runtime"
```

---

### Task 2: 读文件（`load_document`）

**Files:**
- Create: `src/cart_db/extraction.py`（本任务只写文件读取部分）
- Create: `tests/test_extraction.py`

**Interfaces:**
- Consumes: 无（纯本地文件处理）
- Produces:
  - `strip_xml_boilerplate(xml: str) -> str`
  - `load_document(path: str | Path) -> str`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_extraction.py`：

```python
"""文档读取与拆平逻辑的测试。不联网、不调模型。"""
import pytest

from cart_db.extraction import load_document, strip_xml_boilerplate

JATS = """<article>
  <front><article-title>Anti-CDH17 CAR-T</article-title></front>
  <body><p>SPR 测得 Kd = 2.4 nM。</p></body>
  <back>
    <ack><p>感谢基金支持。</p></ack>
    <ref-list><ref><mixed-citation>Smith 2020</mixed-citation></ref></ref-list>
  </back>
</article>"""


def test_strip_removes_back_matter():
    out = strip_xml_boilerplate(JATS)
    assert "Smith 2020" not in out
    assert "感谢基金支持" not in out


def test_strip_keeps_body_intact():
    out = strip_xml_boilerplate(JATS)
    assert "Kd = 2.4 nM" in out
    assert "Anti-CDH17 CAR-T" in out


def test_strip_removes_standalone_ref_list():
    xml = "<article><body><p>正文</p></body><ref-list><ref>X</ref></ref-list></article>"
    out = strip_xml_boilerplate(xml)
    assert "正文" in out
    assert "<ref>" not in out


def test_load_xml_file(tmp_path):
    path = tmp_path / "PMC1.xml"
    path.write_text(JATS, encoding="utf-8")
    text = load_document(path)
    assert "Kd = 2.4 nM" in text
    assert "Smith 2020" not in text


def test_load_nxml_extension(tmp_path):
    path = tmp_path / "PMC1.nxml"
    path.write_text(JATS, encoding="utf-8")
    assert "Kd = 2.4 nM" in load_document(path)


def test_load_markdown_verbatim(tmp_path):
    """Markdown 已经是纯文本，原样送进去，不做任何剥离。"""
    path = tmp_path / "note.md"
    path.write_text("# 实验记录\n\nKd = 2.4 nM\n\n<ref-list>保留</ref-list>\n", encoding="utf-8")
    text = load_document(path)
    assert "# 实验记录" in text
    assert "Kd = 2.4 nM" in text
    assert "<ref-list>保留</ref-list>" in text


def test_load_markdown_alias_extension(tmp_path):
    path = tmp_path / "note.markdown"
    path.write_text("Kd = 2.4 nM\n", encoding="utf-8")
    assert "Kd = 2.4 nM" in load_document(path)


def test_unknown_extension_raises(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的文件格式"):
        load_document(path)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/test_extraction.py -v`
Expected: FAIL，`ImportError: cannot import name 'load_document'`

- [ ] **Step 3: 写 `src/cart_db/extraction.py`**

整份替换旧内容：

```python
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
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/test_extraction.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add src/cart_db/extraction.py tests/test_extraction.py
git commit -m "feat: load PDF/XML/Markdown documents to plain text"
```

---

### Task 3: 拆平（`flatten`）

**Files:**
- Modify: `src/cart_db/basemodel.py`
- Modify: `src/cart_db/extraction.py`
- Modify: `tests/test_extraction.py`

**Interfaces:**
- Consumes: Task 1 的 `load_schema()`、`ExtractionSchema`、`EntitySpec`；`cart_db.basemodel.NormalizedData`
- Produces: `flatten(result, schema: ExtractionSchema | None = None) -> list[NormalizedData]`

**关于设计文档第 8 节的三项检查：** 第 1 项（出处、证据等级非空）与第 2 项（组合序号在范围内）在本任务实现。第 3 项（可选值合法）不需要额外代码——`Literal` 由 Pydantic 在 `model_validate` 阶段就拦下了。不要再写一遍手工检查。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_extraction.py` 末尾追加：

```python
from cart_db.extraction import flatten
from cart_db.schema_models import KV, load_schema

SCHEMA = load_schema()
Extraction = SCHEMA.extraction
Combination = Extraction.model_fields["combinations"].annotation.__args__[0]


def _entity(kind):
    return next(e for e in SCHEMA.entities if e.kind == kind)


def _ev(kind, **kw):
    """一条能通过校验的最小证据。"""
    model = _entity(kind).evidence_model
    return model(source_type="literature", source_id="PMC1",
                 evidence_level="同行評議", **kw)


def _shared_ev(**kw):
    """组合实验用的证据（只有共享字段）。"""
    model = Combination.model_fields["experiments"].annotation.__args__[0]
    return model(source_type="literature", source_id="PMC1",
                 evidence_level="同行評議", **kw)


def _rows_of(rows, table):
    return [r for r in rows if r.table == table]


def test_evidence_points_at_its_own_binder():
    Binder = _entity("binder").model
    ex = Extraction(binders=[
        Binder(name="ARB-202", target_antigen="CDH17",
               evidence=[_ev("binder", kd=2.4, measurement_method="SPR")]),
        Binder(name="5F9", evidence=[_ev("binder", kd=40.0)]),
    ])
    rows = flatten(ex)
    binders = _rows_of(rows, "binder")
    by_kd = {e.data["binder.kd"]: e for e in _rows_of(rows, "evidence")}

    assert len(binders) == 2
    assert by_kd[2.4].data["binder.binder_id"] == binders[0].data["binder_id"]
    assert by_kd[40.0].data["binder.binder_id"] == binders[1].data["binder_id"]
    assert binders[0].data["binder_id"] != binders[1].data["binder_id"]


def test_evidence_carries_all_three_fk_columns():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(name="A", evidence=[_ev("binder")])])
    data = _rows_of(flatten(ex), "evidence")[0].data
    assert data["binder.binder_id"] is not None
    assert data["car.car_id"] is None
    assert data["manufacturing.manufacturing_id"] is None


def test_shared_fields_are_not_prefixed():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(name="A", evidence=[_ev("binder")])])
    data = _rows_of(flatten(ex), "evidence")[0].data
    assert data["source_id"] == "PMC1"
    assert "binder.source_id" not in data


def test_car_and_manufacturing_memory_phenotype_stay_apart():
    """同名字段必须写成两个不同的列，绝不能互相覆盖。"""
    Car = _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        cars=[Car(name="BBz", evidence=[_ev("car", memory_phenotype="Tcm 偏多")])],
        manufacturings=[Manufacturing(
            name="LV", evidence=[_ev("manufacturing", memory_phenotype="Tscm 偏多")])],
    )
    rows = _rows_of(flatten(ex), "evidence")
    values = {}
    for row in rows:
        values.update({k: v for k, v in row.data.items() if k.endswith("memory_phenotype")})
    assert values["car.memory_phenotype"] == "Tcm 偏多"
    assert values["manufacturing.memory_phenotype"] == "Tscm 偏多"


def test_kv_lists_become_dicts():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(
        name="A",
        fr_cdr_regions=[KV(key="CDR-H3", value="ARDYW")],
        evidence=[_ev("binder", measurement_conditions=[
            KV(key="温度", value="25°C"), KV(key="缓冲液", value="PBS")])],
    )])
    rows = flatten(ex)
    assert _rows_of(rows, "binder")[0].data["fr_cdr_regions"] == {"CDR-H3": "ARDYW"}
    assert _rows_of(rows, "evidence")[0].data["binder.measurement_conditions"] == {
        "温度": "25°C", "缓冲液": "PBS"}


def test_modules_stay_a_list():
    Car = _entity("car").model
    ex = Extraction(cars=[Car(name="BBz", modules=[
        {"module_type": "hinge", "source_molecule": "CD8a", "length": 45},
        {"module_type": "CD3zeta"},
    ])])
    modules = _rows_of(flatten(ex), "car")[0].data["modules"]
    assert isinstance(modules, list) and len(modules) == 2
    assert modules[0]["module_type"] == "hinge"


def test_entities_come_before_evidence():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(name="A", evidence=[_ev("binder")])])
    tables = [r.table for r in flatten(ex)]
    assert tables.index("binder") < tables.index("evidence")


def test_combination_resolves_indices_and_emits_one_evidence_row():
    Binder, Car = _entity("binder").model, _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        binders=[Binder(name="A"), Binder(name="B")],
        cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV-MOI5")],
        combinations=[Combination(
            binder_index=1, car_index=0, manufacturing_index=0,
            completed_experiment_phase="in_vitro",
            experiments=[_shared_ev(outcomes=[KV(key="killing_rate", value="85%")])],
        )],
    )
    rows = flatten(ex)
    combo = _rows_of(rows, "abc_combination_db1")[0]
    evidence = _rows_of(rows, "evidence")[0]

    assert combo.data["binder_id"] == _rows_of(rows, "binder")[1].data["binder_id"]
    assert combo.data["completed_experiment_phase"] == "in_vitro"
    assert evidence.data["binder.binder_id"] == combo.data["binder_id"]
    assert evidence.data["car.car_id"] == combo.data["car_id"]
    assert evidence.data["manufacturing.manufacturing_id"] == combo.data["manufacturing_id"]
    assert evidence.data["outcomes"] == {"killing_rate": "85%"}


def test_out_of_range_combination_is_dropped(caplog):
    Binder, Car = _entity("binder").model, _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        binders=[Binder(name="A")], cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV")],
        combinations=[Combination(binder_index=7, car_index=0, manufacturing_index=0)],
    )
    with caplog.at_level("WARNING"):
        rows = flatten(ex)
    assert _rows_of(rows, "abc_combination_db1") == []
    assert "序号越界" in caplog.text


def test_negative_index_is_dropped():
    Binder, Car = _entity("binder").model, _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        binders=[Binder(name="A")], cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV")],
        combinations=[Combination(binder_index=-1, car_index=0, manufacturing_index=0)],
    )
    assert _rows_of(flatten(ex), "abc_combination_db1") == []


def test_evidence_without_source_id_is_dropped(caplog):
    Binder = _entity("binder").model
    model = _entity("binder").evidence_model
    ex = Extraction(binders=[Binder(name="A", evidence=[
        model(source_type="literature", source_id=None,
              evidence_level="同行評議", kd=2.4)])])
    with caplog.at_level("WARNING"):
        rows = flatten(ex)
    assert _rows_of(rows, "evidence") == []
    assert _rows_of(rows, "binder") != []       # 实体本身保留
    assert "出处" in caplog.text


def test_evidence_with_blank_evidence_level_is_dropped():
    Binder = _entity("binder").model
    model = _entity("binder").evidence_model
    ex = Extraction(binders=[Binder(name="A", evidence=[
        model(source_type="literature", source_id="PMC1", evidence_level="   ")])])
    assert _rows_of(flatten(ex), "evidence") == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/test_extraction.py -v`
Expected: FAIL，`ImportError: cannot import name 'flatten'`

- [ ] **Step 3: 把 `NormalizedData.table` 改成当前五张表**

`src/cart_db/basemodel.py` 整份替换：

```python
from typing import Any, Literal

from pydantic import BaseModel


class NormalizedData(BaseModel):
    """入库前的交接格式：一行一条记录。"""

    table: Literal[
        "binder",
        "car",
        "manufacturing",
        "evidence",
        "abc_combination_db1",
    ]
    data: dict[str, Any]
```

- [ ] **Step 4: 在 `src/cart_db/extraction.py` 追加拆平逻辑**

顶部 import 区补上：

```python
from typing import Any
from uuid import uuid4

from .basemodel import NormalizedData
from .schema_models import ExtractionSchema, load_schema
```

文件末尾追加：

```python
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
```

- [ ] **Step 5: 运行全部测试，确认通过**

Run: `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/ -v`
Expected: 全部通过（Task 1 的 13 条 + Task 2 的 8 条 + 本任务的 12 条）

- [ ] **Step 6: 提交**

```bash
git add src/cart_db/basemodel.py src/cart_db/extraction.py tests/test_extraction.py
git commit -m "feat: flatten nested extraction into NormalizedData rows"
```

---

### Task 4: 填表说明与全流程

**Files:**
- Modify: `src/cart_db/extraction.py`
- Modify: `tests/test_extraction.py`

**Interfaces:**
- Consumes: Task 1 的 `load_schema`、Task 2 的 `load_document`、Task 3 的 `flatten`；`cart_db.llm` 的 `extract`、`count_tokens`；`cart_db.config` 的 `settings`、`cost_cny`
- Produces:
  - `build_system_prompt() -> str`
  - `extract_document(path, *, out_dir=None, dry_run=False) -> list[NormalizedData]`

- [ ] **Step 1: 写失败的测试**

在 `tests/test_extraction.py` 末尾追加：

```python
import json

from cart_db import extraction


def test_system_prompt_contains_rules_schema_and_output_guide():
    prompt = extraction.build_system_prompt()
    assert "biomedical data extraction agent" in prompt      # article_extraction_prompt.txt
    assert "target_antigen" in prompt                        # Schema_A.yaml
    assert "abc_combination_db1" in prompt                   # Schema_DB1.yaml
    assert "binder.kd" in prompt                             # Evidence.yaml
    assert "binder_index" in prompt                          # 输出格式说明


def test_system_prompt_is_stable_across_calls():
    """跨文档完全一致才能命中提示词缓存。"""
    assert extraction.build_system_prompt() == extraction.build_system_prompt()


def test_extract_document_writes_jsonl(tmp_path, monkeypatch):
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")
    Binder = _entity("binder").model
    captured = {}

    def fake_extract(*, schema, document, system_prompt, purpose, **kw):
        captured.update(document=document, purpose=purpose, schema=schema)
        return Extraction(binders=[
            Binder(name="ARB-202", evidence=[_ev("binder", kd=2.4)])])

    monkeypatch.setattr(extraction.llm, "extract", fake_extract)
    out_dir = tmp_path / "out"
    rows = extraction.extract_document(doc, out_dir=out_dir)

    assert "Kd = 2.4 nM" in captured["document"]      # 正文送进去了
    assert "Smith 2020" not in captured["document"]   # 参考文献没送
    assert captured["purpose"] == "article_extraction"
    assert captured["schema"] is SCHEMA.extraction

    written = (out_dir / "PMC1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(written) == len(rows) == 2
    assert json.loads(written[0])["data"]["name"] == "ARB-202"


def test_extract_document_writes_readable_utf8(tmp_path, monkeypatch):
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")
    Binder = _entity("binder").model
    monkeypatch.setattr(extraction.llm, "extract",
                        lambda **kw: Extraction(binders=[Binder(name="抗体")]))

    extraction.extract_document(doc, out_dir=tmp_path / "out")
    raw = (tmp_path / "out" / "PMC1.jsonl").read_text(encoding="utf-8")
    assert "抗体" in raw


def test_dry_run_estimates_without_calling_extract(tmp_path, monkeypatch):
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")

    def boom(**kw):
        raise AssertionError("dry_run 不该真的调用模型")

    monkeypatch.setattr(extraction.llm, "extract", boom)
    monkeypatch.setattr(extraction.llm, "count_tokens", lambda **kw: 42_000)

    rows = extraction.extract_document(doc, out_dir=tmp_path / "out", dry_run=True)
    assert rows == []
    assert not (tmp_path / "out" / "PMC1.jsonl").exists()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/test_extraction.py -v -k "prompt or extract_document or dry_run"`
Expected: FAIL，`AttributeError: module 'cart_db.extraction' has no attribute 'build_system_prompt'`

- [ ] **Step 3: 追加实现**

顶部 import 区补上：

```python
import json

from . import llm
from .config import cost_cny, settings
from .schema_models import SCHEMA_DIR
```

文件末尾追加：

```python
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
```

- [ ] **Step 4: 运行全部测试，确认通过**

Run: `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/ -v`
Expected: 全部通过（新增 5 条）

- [ ] **Step 5: 提交**

```bash
git add src/cart_db/extraction.py tests/test_extraction.py
git commit -m "feat: build cacheable system prompt and run the full extraction pipeline"
```

---

### Task 5: 命令行入口

**Files:**
- Create: `scripts/extract.py`
- Modify: `Makefile`
- Modify: `tests/test_extraction.py`

**Interfaces:**
- Consumes: Task 4 的 `extract_document`
- Produces: `scripts/extract.py` 的 `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: 写失败的测试**

在 `tests/test_extraction.py` 末尾追加：

```python
import subprocess
import sys
from pathlib import Path as _Path

REPO = _Path(__file__).resolve().parents[1]


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "extract.py"), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--dry-run" in result.stdout


def test_cli_main_passes_arguments(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO / "scripts"))
    import extract as cli

    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")
    seen = {}

    def fake(path, *, out_dir=None, dry_run=False):
        seen.update(path=str(path), out_dir=str(out_dir), dry_run=dry_run)
        return []

    monkeypatch.setattr(cli, "extract_document", fake)
    assert cli.main([str(doc), "--out-dir", str(tmp_path / "out"), "--dry-run"]) == 0
    assert seen["dry_run"] is True
    assert seen["path"] == str(doc)


def test_cli_reports_missing_file(tmp_path, capsys):
    sys.path.insert(0, str(REPO / "scripts"))
    import extract as cli

    assert cli.main([str(tmp_path / "nope.xml")]) == 1
    assert "不存在" in capsys.readouterr().err
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/test_extraction.py -v -k cli`
Expected: FAIL，找不到 `scripts/extract.py`

- [ ] **Step 3: 写 `scripts/extract.py`**

```python
#!/usr/bin/env python
"""从一份 PDF / XML / Markdown 文档抽取结构化数据。

    python scripts/extract.py data/raw/europe_pmc/PMC123.xml
    python scripts/extract.py data/raw/ema_epar/carvykti.pdf --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cart_db.extraction import extract_document      # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="要抽取的 .pdf / .xml / .nxml / .md 文件")
    parser.add_argument("--out-dir", default=None, help="结果目录，默认 data/normalised/")
    parser.add_argument("--dry-run", action="store_true",
                        help="只估算 token 与费用，不调模型、不写文件")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    path = Path(args.file)
    if not path.exists():
        print(f"文件不存在：{path}", file=sys.stderr)
        return 1

    rows = extract_document(path, out_dir=args.out_dir, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"写出 {len(rows)} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 改 Makefile**

把第 4 行的解释器指向 conda 的 `fosun` 环境（仓库里没有 `.venv`，现有目标其实都跑不起来）：

```makefile
PY ?= /home/zzz010122/anaconda3/envs/fosun/bin/python
```

`.PHONY` 那一行末尾追加 ` extract`，并在「原始数据下载」一节之前插入：

```makefile
# ---- 文本抽取 ------------------------------------------------------------
extract:  ## 从一份 PDF/XML/MD 抽取数据：make extract FILE=data/raw/europe_pmc/x.xml
	$(PY) scripts/extract.py $(FILE) $(ARGS)
```

- [ ] **Step 5: 运行全部测试，确认通过**

Run: `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/ -v`
Expected: 全部通过（新增 3 条，合计约 41 条）

- [ ] **Step 6: 提交**

```bash
git add scripts/extract.py Makefile tests/test_extraction.py
git commit -m "feat: add extract CLI and make target"
```

---

### Task 6: 用真实文档验证

这一步需要 `ANTHROPIC_API_KEY`，且会真的花钱。前五个任务全绿之后再做。

**Files:**
- 只读：`data/raw/europe_pmc/`、`data/normalised/`

**Interfaces:**
- Consumes: Task 5 的命令行入口
- Produces: 一份人工核对过的 `data/normalised/<文件名>.jsonl`

- [ ] **Step 1: 准备一篇真实文献**

```bash
ls data/raw/europe_pmc/
```

若目录下没有 `.xml` 全文，先 `make download-litc`。

- [ ] **Step 2: 先估成本**

```bash
make extract FILE=data/raw/europe_pmc/<文件名>.xml ARGS=--dry-run
```

Expected: 打印类似 `输入 42000 token，预计约 ¥0.95`。
设计文档第 10 节按每篇 ¥1.0–1.5 估算了全量 600 篇，实测明显偏离要反馈。

- [ ] **Step 3: 实跑一篇**

```bash
make extract FILE=data/raw/europe_pmc/<文件名>.xml
```

Expected: 打印 `写出 N 行`，生成 `data/normalised/<文件名>.jsonl`。

- [ ] **Step 4: 人工核对**

```bash
/home/zzz010122/anaconda3/envs/fosun/bin/python -c "
import json, collections, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
print(collections.Counter(r['table'] for r in rows))
for r in rows[:5]:
    print(r['table'], json.dumps(r['data'], ensure_ascii=False)[:200])
" data/normalised/<文件名>.jsonl
```

对照原文逐项确认：

1. 抽出的 Binder / CAR / 工艺数量与文中实际描述一致，没有凭空多出来的实体。
2. 每条 evidence 的 `binder.binder_id` 确实指向正确的那个 Binder。
3. 数值与单位跟原文一致；范围值（如 `Kd = 2–5 nM`）没有被擅自取中位数。
4. `source_id` 是文中真实的 PMID / PMCID / DOI，不是编的。
5. 序列（`vh_sequence` 等）与原文逐字符一致。
6. 若同时出现 CAR 与制造工艺的证据，确认 `car.memory_phenotype` 与
   `manufacturing.memory_phenotype` 各归各位，没有串。

- [ ] **Step 5: 检查被丢弃的行**

留意 WARNING。若大量证据因「缺少出处」被丢弃，说明提示词需要更明确地要求模型填出处——记录观察结果，不要靠放宽校验让数字变好看。

- [ ] **Step 6: 记录结果**

```bash
git add data/normalised/
git commit -m "chore: first real extraction output for manual review"
```

---

## 完成标准

- `/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/ -v` 全绿（约 41 条）。
- 往 `docs/Schema/*.yaml` 加一个字段，不改任何 Python，该字段就出现在模型里（`test_new_yaml_field_appears_without_touching_python` 守着这条）。
- `make extract FILE=<一篇真实 XML>` 能产出 jsonl。
- 人工核对确认：实体数量正确、归属关系正确、数值与序列与原文一致、出处真实、同名字段没串。
