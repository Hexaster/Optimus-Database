# 文献/专利 LLM Parser 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给定一个 PDF 或 XML 文档，用 LLM 抽取其中的 Binder / CAR / 制造工艺 / 实验证据，产出 `data/normalised/<文件名>.jsonl`。

**Architecture:** 为 `docs/Schema/*.yaml` 的每张表手写 Pydantic 模型，作为 LLM 的强制答题格式；模型输出嵌套结构（证据写在所属实体内部），Python 的 `flatten()` 再拆成一行行 `NormalizedData`，顺手生成 UUID、回填外键、丢弃校验不过的行。`src/cart_db/llm.py` 一行都不改。

**Tech Stack:** Python 3.13、Pydantic v2、Anthropic SDK（经 `llm.py` 封装）、pymupdf（PDF 取字）、PyYAML、pytest

**Spec:** `docs/superpowers/specs/2026-08-28-llm-document-parser-design.md`

## Global Constraints

- **不修改 `src/cart_db/llm.py`。** 调用、缓存、计费、每日上限都已就绪，直接用。
- **模型字段名必须与 `docs/Schema/*.yaml` 完全一致**，只有两处例外：主键列不出现在模型里（UUID 由 `flatten()` 生成），以及 `evidence` 的带前缀字段（`binder.kd`）在模型里写作无前缀的 `kd`，前缀由 `flatten()` 补回——Python 属性名不能带点。
- **五张目标表**：`binder`、`car`、`manufacturing`、`evidence`、`abc_combination_db1`。
- **`NormalizedData.table` 只列当前五张表。** 结构化通道那边怎么改是另一条线的事，本计划不为它保留旧表名。
- **写文件一律 `ensure_ascii=False`、UTF-8。** 中文字段值要能直接看。
- **日志用 `logging`，不用 `print`**（`scripts/extract.py` 的用户输出除外）。
- **所有 json 类型字段用 `list[KV]` 表达**，`flatten()` 还原成 dict。
- 虚拟环境路径固定为 `./.venv`，与 Makefile 的 `PY := ./.venv/bin/python` 一致。

---

### Task 1: 环境与字段清单（`extraction_models.py`）

**Files:**
- Create: `src/cart_db/extraction_models.py`
- Create: `tests/test_extraction_models.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `src/cart_db/llm.py` 的 `_strict()`（只在测试里用，用来验证生成的 JSON Schema 合法）
- Produces: `KV`、`EvidenceBase`、`BinderEvidence`、`CarEvidence`、`ManufacturingEvidence`、`Binder`、`Module`、`Car`、`Manufacturing`、`Combination`、`Extraction`。三个证据子类各有 `PREFIX: ClassVar[str]`，取值 `"binder"` / `"car"` / `"manufacturing"`。

**关于默认值的说明（实现者请勿"修正"）：** 所有可空字段都给 `= None` 默认值，列表字段给 `Field(default_factory=list)`。这不会放松对模型的约束：`llm._strict()` 会对没有 `required` 键的对象补上「全部字段必填」。而少数确实必填的字段（`Combination` 的三个序号、`Module.module_type`、`EvidenceBase.source_type`）不给默认值，Pydantic 会为它们生成一个 `required` 列表，`_strict()` 的 `setdefault` 会保留该列表——这些字段仍是必填，其余字段允许省略并落到 `None`。省略与显式填 `null` 在结果上一致，还省输出 token。

- [ ] **Step 1: 建虚拟环境并补依赖**

```bash
cd /home/zzz010122/Fosun-db
python3 -m venv .venv
```

在 `requirements.txt` 末尾追加两行（`pymupdf` 代码里早就在用，只是从来没声明过）：

```
pymupdf>=1.24        # extraction.load_document 从 PDF 取文字
pytest>=8.0          # tests/
```

```bash
./.venv/bin/pip install -r requirements.txt
```

- [ ] **Step 2: 写失败的测试**

创建 `tests/test_extraction_models.py`：

```python
"""字段清单必须与 docs/Schema/*.yaml 对得上，且能生成合法的强制格式 schema。"""
from pathlib import Path

import yaml

from cart_db import llm
from cart_db.extraction_models import (
    Binder, BinderEvidence, Car, CarEvidence, EvidenceBase, Extraction,
    Manufacturing, ManufacturingEvidence,
)

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "docs" / "Schema"


def _fields(filename: str, table_key: str) -> dict:
    doc = yaml.safe_load((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    return doc[table_key]["fields"]


def _prefixed(prefix: str) -> set[str]:
    """Evidence.yaml 里 binder.* 这类字段，去掉前缀和外键列。"""
    fields = _fields("Evidence.yaml", "evidence")
    return {
        name.split(".", 1)[1]
        for name in fields
        if name.startswith(f"{prefix}.")
    } - {f"{prefix}_id"}


def _extra(model) -> set[str]:
    """子类相对 EvidenceBase 多出来的字段。"""
    return set(model.model_fields) - set(EvidenceBase.model_fields)


def test_evidence_base_matches_shared_schema_fields():
    fields = _fields("Evidence.yaml", "evidence")
    shared = {name for name in fields if "." not in name} - {"record_id"}
    assert set(EvidenceBase.model_fields) == shared


def test_binder_evidence_matches_schema():
    assert _extra(BinderEvidence) == _prefixed("binder")


def test_car_evidence_matches_schema():
    assert _extra(CarEvidence) == _prefixed("car")


def test_manufacturing_evidence_matches_schema():
    assert _extra(ManufacturingEvidence) == _prefixed("manufacturing")


def test_entity_models_match_schema():
    cases = [
        (Binder, "Schema_A.yaml", "binder", "binder_id"),
        (Car, "Schema_B.yaml", "car", "car_id"),
        (Manufacturing, "Schema_C.yaml", "manufacturing", "manufacturing_id"),
    ]
    for model, filename, table_key, pk in cases:
        expected = set(_fields(filename, table_key)) - {pk}
        actual = set(model.model_fields) - {"evidence"}
        assert actual == expected, f"{model.__name__} 与 {filename} 不一致"


def test_evidence_subclasses_declare_prefix():
    assert BinderEvidence.PREFIX == "binder"
    assert CarEvidence.PREFIX == "car"
    assert ManufacturingEvidence.PREFIX == "manufacturing"


def test_strict_schema_is_not_empty():
    """回归测试：旧版 data: dict[str, Any] 会被 _strict 变成「一个字段都不准填」。"""
    schema = llm._strict(Extraction.model_json_schema())
    binder = schema["$defs"]["Binder"]
    assert binder["additionalProperties"] is False
    assert "vh_sequence" in binder["properties"]
    assert set(binder["required"]) == set(binder["properties"])
    assert len(binder["required"]) > 10
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `./.venv/bin/python -m pytest tests/test_extraction_models.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'cart_db.extraction_models'`

如果报的是找不到 `cart_db`，在仓库根新建 `pytest.ini`：

```ini
[pytest]
pythonpath = src
testpaths = tests
```

- [ ] **Step 4: 写 `src/cart_db/extraction_models.py`**

```python
"""交给模型的答题格式：docs/Schema/*.yaml 的字段逐条翻译成 Pydantic 模型。

字段名与 YAML 保持一致，两处例外：
1. 主键列（binder_id 等）不在这里 —— 编号由 flatten() 生成，不能让模型编造。
2. evidence 的带前缀字段（binder.kd）在这里写作无前缀的 kd，前缀由 flatten()
   按 PREFIX 补回，因为 Python 属性名不能带点。
"""
from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field


class KV(BaseModel):
    """强制格式模式不允许「内容任意的对象」，json 类型字段一律用键值对列表表达。"""

    key: str
    value: str


class EvidenceBase(BaseModel):
    """Evidence.yaml 中不带实体前缀的字段：出处与实验背景，三类证据共用。"""

    source_type: Literal["public_database", "literature", "patent", "internal_data"]
    source_id: str | None = None
    citation: str | None = None
    evidence_level: str | None = None
    experimental_conditions: list[KV] | None = None
    applicable_scenario: str | None = None
    contrary_evidence: bool = False
    time_of_upload: str | None = None      # ISO 8601，例 "2024-03-01"
    time_of_download: str | None = None
    outcomes: list[KV] | None = None       # 仅 ABC 组合实验用


class BinderEvidence(EvidenceBase):
    PREFIX: ClassVar[str] = "binder"

    epitope: str | None = None
    binding_site: str | None = None
    kd: float | None = None
    kon: float | None = None
    koff: float | None = None
    measurement_method: Literal["SPR", "BLI"] | None = None
    measurement_conditions: list[KV] | None = None
    cross_reactivity_protein: list[KV] | None = None
    cross_reactivity_cell: list[KV] | None = None
    species_reactivity: list[KV] | None = None
    tm: float | None = None
    viscosity: float | None = None
    aggregation_tendency: str | None = None
    solubility: str | None = None
    hydrophobicity: float | None = None
    charge: float | None = None
    immunogenicity_ada_risk: str | None = None


class CarEvidence(EvidenceBase):
    PREFIX: ClassVar[str] = "car"

    activation_speed: str | None = None
    metabolic_state: Literal["glycolytic", "oxidative"] | None = None
    expansion_capacity: str | None = None
    memory_phenotype: str | None = None
    persistence: str | None = None
    exhaustion_risk: str | None = None
    tonic_signaling_tendency: str | None = None
    geometric_length: float | None = None
    epitope_distance_effect: str | None = None
    immune_synapse_effect: str | None = None
    tonic_signaling_effect: str | None = None
    compatible_modules: list[KV] | None = None
    incompatible_modules: list[KV] | None = None
    assembly_rules: list[KV] | None = None


class ManufacturingEvidence(EvidenceBase):
    PREFIX: ClassVar[str] = "manufacturing"

    cell_viability: float | None = None
    transduction_efficiency: float | None = None
    vcn: float | None = None
    cd3_positive_ratio: float | None = None
    memory_phenotype: str | None = None
    exhaustion_phenotype: str | None = None
    treg_phenotype: str | None = None
    sterility: str | None = None
    mycoplasma: str | None = None
    endotoxin: str | None = None
    killing_activity: str | None = None
    cytokine_release: list[KV] | None = None


class Binder(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    scfv_sequence: str | None = None
    vh_sequence: str | None = None
    vl_sequence: str | None = None
    linker: str | None = None
    numbering_scheme: str | None = None
    fr_cdr_regions: list[KV] | None = None
    cdr_lengths: list[KV] | None = None
    vdj_genes: list[KV] | None = None
    germline_origin: str | None = None
    somatic_mutations: list[KV] | None = None
    target_antigen: str | None = None
    glycosylation_sites: list[KV] | None = None
    free_cysteines: list[KV] | None = None
    humanization_level: str | None = None
    structure_template: str | None = None
    complex_structure: str | None = None
    evidence: list[BinderEvidence] = Field(default_factory=list)


class Module(BaseModel):
    module_type: Literal[
        "linker", "hinge", "transmembrane_region", "costimulatory_domain",
        "CD3zeta", "tag", "safety_switch",
    ]
    source_molecule: str | None = None
    sequence: str | None = None
    length: int | None = None


class Car(BaseModel):
    name: str | None = None
    modules: list[Module] = Field(default_factory=list)   # 按 CAR 中的实际顺序排列
    evidence: list[CarEvidence] = Field(default_factory=list)


class Manufacturing(BaseModel):
    name: str | None = None
    t_cell_source: Literal["自体", "异体"] | None = None
    cd4_cd8_ratio: str | None = None
    starting_cell_quality: list[KV] | None = None
    activation_method: str | None = None
    reagents: list[KV] | None = None
    vector_type: Literal["慢病毒", "逆转录病毒", "转座子", "电转"] | None = None
    moi: float | None = None
    transduction_transfection_conditions: list[KV] | None = None
    culture_system: str | None = None
    cytokine_combination: list[KV] | None = None
    culture_duration: str | None = None
    cryopreservation_conditions: list[KV] | None = None
    formulation: list[KV] | None = None
    corresponding_car_product: str | None = None
    evidence: list[ManufacturingEvidence] = Field(default_factory=list)


class Combination(BaseModel):
    binder_index: int                # 指向 Extraction.binders 的第几个（从 0 数）
    car_index: int
    manufacturing_index: int
    similarity: str | None = None
    completed_experiment_phase: Literal[
        "design_only", "in_vitro", "in_vivo", "preclinical",
        "clinical_phase_1", "clinical_phase_2", "clinical_phase_3",
    ] | None = None
    experiments: list[EvidenceBase] = Field(default_factory=list)


class Extraction(BaseModel):
    """交给模型的完整答题格式。"""

    binders: list[Binder] = Field(default_factory=list)
    cars: list[Car] = Field(default_factory=list)
    manufacturings: list[Manufacturing] = Field(default_factory=list)
    combinations: list[Combination] = Field(default_factory=list)
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `./.venv/bin/python -m pytest tests/test_extraction_models.py -v`
Expected: 8 passed

若 `test_entity_models_match_schema` 失败，以 `docs/Schema/*.yaml` 为准改模型，不要改测试。

- [ ] **Step 6: 提交**

```bash
git add requirements.txt pytest.ini src/cart_db/extraction_models.py tests/test_extraction_models.py
git commit -m "feat: add per-table extraction models for the LLM document parser"
```

---

### Task 2: 读文件（`load_document`）

**Files:**
- Create: `src/cart_db/extraction.py`（本任务只写文件读取部分，后续任务往里加）
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


def test_unknown_extension_raises(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的文件格式"):
        load_document(path)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `./.venv/bin/python -m pytest tests/test_extraction.py -v`
Expected: FAIL，`ImportError: cannot import name 'load_document'`

- [ ] **Step 3: 重写 `src/cart_db/extraction.py`**

整份替换旧内容：

```python
"""从 PDF / XML 文档中抽取结构化数据。

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
    """把 PDF 或 XML 读成纯文本。其他格式直接报错。"""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        import pymupdf

        with pymupdf.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)

    if suffix in {".xml", ".nxml"}:
        return strip_xml_boilerplate(path.read_text(encoding="utf-8"))

    raise ValueError(
        f"不支持的文件格式：{path.suffix}（只支持 .pdf / .xml / .nxml）"
    )
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `./.venv/bin/python -m pytest tests/test_extraction.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/cart_db/extraction.py tests/test_extraction.py
git commit -m "feat: load PDF/XML documents to plain text, stripping JATS back matter"
```

---

### Task 3: 拆平（`flatten`）

**Files:**
- Modify: `src/cart_db/basemodel.py`（给 `table` 的取值列表补两个新表名）
- Modify: `src/cart_db/extraction.py`（追加 `flatten` 及其两个辅助函数）
- Modify: `tests/test_extraction.py`（追加拆平测试）

**Interfaces:**
- Consumes: Task 1 的 `Extraction`、`Binder`、`BinderEvidence`、`Car`、`CarEvidence`、`Manufacturing`、`ManufacturingEvidence`、`Combination`、`KV`、`EvidenceBase`；`cart_db.basemodel.NormalizedData`
- Produces: `flatten(result: Extraction) -> list[NormalizedData]`

**关于设计文档第 8 节的三项检查：** 第 1 项（出处、证据等级非空）和第 2 项（组合序号在范围内）在本任务的 `_evidence_data` 与 `flatten` 里实现。第 3 项（可选值合法）不需要额外代码——`Literal` 由 Pydantic 在 `model_validate` 阶段就拦下了，模型返回越界取值会直接校验失败。不要为它再写一遍手工检查。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_extraction.py` 末尾追加：

```python
from cart_db.extraction import flatten
from cart_db.extraction_models import (
    Binder, BinderEvidence, Car, CarEvidence, Combination, EvidenceBase,
    Extraction, KV, Manufacturing, ManufacturingEvidence, Module,
)


def _ev_kwargs(**kw):
    """一条能通过校验的最小证据。"""
    base = {"source_type": "literature", "source_id": "PMC1", "evidence_level": "同行評議"}
    base.update(kw)
    return base


def _rows_of(rows, table):
    return [r for r in rows if r.table == table]


def test_evidence_points_at_its_own_binder():
    ex = Extraction(binders=[
        Binder(name="ARB-202", target_antigen="CDH17",
               evidence=[BinderEvidence(**_ev_kwargs(kd=2.4, measurement_method="SPR"))]),
        Binder(name="5F9", evidence=[BinderEvidence(**_ev_kwargs(kd=40.0))]),
    ])
    rows = flatten(ex)
    binders = _rows_of(rows, "binder")
    evidence = _rows_of(rows, "evidence")

    assert len(binders) == 2 and len(evidence) == 2
    by_kd = {e.data["binder.kd"]: e for e in evidence}
    assert by_kd[2.4].data["binder.binder_id"] == binders[0].data["binder_id"]
    assert by_kd[40.0].data["binder.binder_id"] == binders[1].data["binder_id"]
    assert binders[0].data["binder_id"] != binders[1].data["binder_id"]


def test_evidence_carries_all_three_fk_columns():
    ex = Extraction(binders=[Binder(name="A", evidence=[BinderEvidence(**_ev_kwargs())])])
    row = _rows_of(flatten(ex), "evidence")[0]
    assert row.data["binder.binder_id"] is not None
    assert row.data["car.car_id"] is None
    assert row.data["manufacturing.manufacturing_id"] is None


def test_shared_fields_are_not_prefixed():
    ex = Extraction(binders=[Binder(name="A", evidence=[BinderEvidence(**_ev_kwargs())])])
    data = _rows_of(flatten(ex), "evidence")[0].data
    assert data["source_type"] == "literature"
    assert data["source_id"] == "PMC1"
    assert "binder.source_id" not in data


def test_kv_lists_become_dicts():
    ex = Extraction(binders=[Binder(
        name="A",
        fr_cdr_regions=[KV(key="CDR-H3", value="ARDYW")],
        evidence=[BinderEvidence(**_ev_kwargs(
            measurement_conditions=[KV(key="温度", value="25°C"),
                                    KV(key="缓冲液", value="PBS")]))],
    )])
    rows = flatten(ex)
    assert _rows_of(rows, "binder")[0].data["fr_cdr_regions"] == {"CDR-H3": "ARDYW"}
    assert _rows_of(rows, "evidence")[0].data["binder.measurement_conditions"] == {
        "温度": "25°C", "缓冲液": "PBS"}


def test_modules_stay_a_list():
    ex = Extraction(cars=[Car(name="BBz", modules=[
        Module(module_type="hinge", source_molecule="CD8a", length=45),
        Module(module_type="CD3zeta"),
    ])])
    modules = _rows_of(flatten(ex), "car")[0].data["modules"]
    assert isinstance(modules, list) and len(modules) == 2
    assert modules[0]["module_type"] == "hinge"


def test_entities_come_before_evidence():
    ex = Extraction(binders=[Binder(name="A", evidence=[BinderEvidence(**_ev_kwargs())])])
    tables = [r.table for r in flatten(ex)]
    assert tables.index("binder") < tables.index("evidence")


def test_combination_resolves_indices_and_emits_one_evidence_row():
    ex = Extraction(
        binders=[Binder(name="A"), Binder(name="B")],
        cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV-MOI5")],
        combinations=[Combination(
            binder_index=1, car_index=0, manufacturing_index=0,
            completed_experiment_phase="in_vitro",
            experiments=[EvidenceBase(**_ev_kwargs(
                outcomes=[KV(key="killing_rate", value="85%")]))],
        )],
    )
    rows = flatten(ex)
    combo = _rows_of(rows, "abc_combination_db1")[0]
    evidence = _rows_of(rows, "evidence")[0]

    assert combo.data["binder_id"] == _rows_of(rows, "binder")[1].data["binder_id"]
    assert combo.data["car_id"] == _rows_of(rows, "car")[0].data["car_id"]
    assert combo.data["completed_experiment_phase"] == "in_vitro"
    # 组合实验只产出一行 evidence，三个外键都填上
    assert evidence.data["binder.binder_id"] == combo.data["binder_id"]
    assert evidence.data["car.car_id"] == combo.data["car_id"]
    assert evidence.data["manufacturing.manufacturing_id"] == combo.data["manufacturing_id"]
    assert evidence.data["outcomes"] == {"killing_rate": "85%"}


def test_out_of_range_combination_is_dropped(caplog):
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
    ex = Extraction(
        binders=[Binder(name="A")], cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV")],
        combinations=[Combination(binder_index=-1, car_index=0, manufacturing_index=0)],
    )
    assert _rows_of(flatten(ex), "abc_combination_db1") == []


def test_evidence_without_source_id_is_dropped(caplog):
    ex = Extraction(binders=[Binder(name="A", evidence=[
        BinderEvidence(source_type="literature", source_id=None,
                       evidence_level="同行評議", kd=2.4),
    ])])
    with caplog.at_level("WARNING"):
        rows = flatten(ex)
    assert _rows_of(rows, "evidence") == []
    assert _rows_of(rows, "binder") != []      # 实体本身保留
    assert "出处" in caplog.text


def test_evidence_with_blank_evidence_level_is_dropped():
    ex = Extraction(binders=[Binder(name="A", evidence=[
        BinderEvidence(source_type="literature", source_id="PMC1", evidence_level="   "),
    ])])
    assert _rows_of(flatten(ex), "evidence") == []


def test_manufacturing_evidence_uses_its_own_prefix():
    ex = Extraction(manufacturings=[Manufacturing(
        name="LV", evidence=[ManufacturingEvidence(**_ev_kwargs(vcn=2.1))])])
    data = _rows_of(flatten(ex), "evidence")[0].data
    assert data["manufacturing.vcn"] == 2.1
    assert data["binder.binder_id"] is None


def test_car_evidence_uses_its_own_prefix():
    ex = Extraction(cars=[Car(name="BBz", evidence=[
        CarEvidence(**_ev_kwargs(persistence="long"))])])
    data = _rows_of(flatten(ex), "evidence")[0].data
    assert data["car.persistence"] == "long"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `./.venv/bin/python -m pytest tests/test_extraction.py -v`
Expected: FAIL，`ImportError: cannot import name 'flatten'`

- [ ] **Step 3: 把 `NormalizedData.table` 改成当前五张表**

`src/cart_db/basemodel.py` 整份替换。取值就是 `docs/Schema/*.yaml` 现有的五张表，合并前的旧表名一律删掉：

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

在文件顶部的 import 区补上：

```python
from typing import Any
from uuid import uuid4

from .basemodel import NormalizedData
from .extraction_models import EvidenceBase, Extraction
```

在文件末尾追加：

```python
# evidence 表里三个实体外键的列名。
_FK_COLUMNS = {
    "binder": "binder.binder_id",
    "car": "car.car_id",
    "manufacturing": "manufacturing.manufacturing_id",
}


def _unkv(value: Any) -> Any:
    """把 [{"key": k, "value": v}, ...] 还原成 {k: v}；其他值原样返回。

    Module 之类的列表每项有四个键，不会被误认成键值对。
    """
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, dict) and set(item) == {"key", "value"} for item in value)
    ):
        return {item["key"]: item["value"] for item in value}
    return value


def _entity_data(entity, id_column: str) -> tuple[str, dict[str, Any]]:
    """实体行：生成 UUID，键值对还原成 dict，去掉嵌套的 evidence。"""
    entity_id = str(uuid4())
    data: dict[str, Any] = {id_column: entity_id}
    for name, value in entity.model_dump(exclude={"evidence"}).items():
        data[name] = _unkv(value)
    return entity_id, data


def _evidence_data(evidence: EvidenceBase, owner_ids: dict[str, str]) -> dict[str, Any] | None:
    """证据行。出处或证据等级为空就丢弃这一行（返回 None）。"""
    if not (evidence.source_id or "").strip():
        logger.warning("证据缺少出处（source_id 为空），丢弃该行：%r", evidence.model_dump())
        return None
    if not (evidence.evidence_level or "").strip():
        logger.warning("证据缺少证据等级，丢弃该行（出处 %s）", evidence.source_id)
        return None

    dumped = evidence.model_dump()
    shared = set(EvidenceBase.model_fields)

    data: dict[str, Any] = {"record_id": str(uuid4())}
    for name in EvidenceBase.model_fields:
        data[name] = _unkv(dumped[name])

    prefix = getattr(type(evidence), "PREFIX", None)
    if prefix:
        for name in type(evidence).model_fields:
            if name not in shared:
                data[f"{prefix}.{name}"] = _unkv(dumped[name])

    # 三个外键列都写出来，只有归属的那个有值 —— 结果文件能直接对着 Evidence.yaml 看。
    for kind, column in _FK_COLUMNS.items():
        data[column] = owner_ids.get(kind)

    return data


def _at(ids: list[str], index: int) -> str | None:
    """按序号取实体编号；越界或负数返回 None。"""
    if 0 <= index < len(ids):
        return ids[index]
    return None


def flatten(result: Extraction) -> list[NormalizedData]:
    """把模型返回的嵌套结果拆成一行行 NormalizedData。

    输出顺序：binder、car、manufacturing、abc_combination_db1，最后 evidence。
    被引用的实体必须先出现，后面引用它的行才有编号可填。
    """
    entity_rows: list[NormalizedData] = []
    combination_rows: list[NormalizedData] = []
    evidence_rows: list[NormalizedData] = []

    ids: dict[str, list[str]] = {"binder": [], "car": [], "manufacturing": []}
    plan = [
        ("binder", result.binders, "binder_id"),
        ("car", result.cars, "car_id"),
        ("manufacturing", result.manufacturings, "manufacturing_id"),
    ]

    for kind, entities, id_column in plan:
        for entity in entities:
            entity_id, data = _entity_data(entity, id_column)
            ids[kind].append(entity_id)
            entity_rows.append(NormalizedData(table=kind, data=data))
            for evidence in entity.evidence:
                row = _evidence_data(evidence, {kind: entity_id})
                if row is not None:
                    evidence_rows.append(NormalizedData(table="evidence", data=row))

    for position, combination in enumerate(result.combinations):
        owner_ids = {
            "binder": _at(ids["binder"], combination.binder_index),
            "car": _at(ids["car"], combination.car_index),
            "manufacturing": _at(ids["manufacturing"], combination.manufacturing_index),
        }
        if any(value is None for value in owner_ids.values()):
            logger.warning(
                "组合 #%d 的序号越界，丢弃：binder=%d(共%d) car=%d(共%d) manufacturing=%d(共%d)",
                position,
                combination.binder_index, len(ids["binder"]),
                combination.car_index, len(ids["car"]),
                combination.manufacturing_index, len(ids["manufacturing"]),
            )
            continue

        combination_rows.append(NormalizedData(table="abc_combination_db1", data={
            "combination_id": str(uuid4()),
            "binder_id": owner_ids["binder"],
            "car_id": owner_ids["car"],
            "manufacturing_id": owner_ids["manufacturing"],
            "similarity": combination.similarity,
            "completed_experiment_phase": combination.completed_experiment_phase,
        }))

        # 组合实验只产出一行 evidence，三个外键都填上。
        for experiment in combination.experiments:
            row = _evidence_data(experiment, owner_ids)
            if row is not None:
                evidence_rows.append(NormalizedData(table="evidence", data=row))

    return entity_rows + combination_rows + evidence_rows
```

- [ ] **Step 5: 运行全部测试，确认通过**

Run: `./.venv/bin/python -m pytest tests/ -v`
Expected: 全部通过（Task 1 的 8 条 + Task 2 的 6 条 + 本任务的 12 条）

- [ ] **Step 6: 提交**

```bash
git add src/cart_db/basemodel.py src/cart_db/extraction.py tests/test_extraction.py
git commit -m "feat: flatten nested extraction into NormalizedData rows"
```

---

### Task 4: 填表说明与全流程（`build_system_prompt` / `extract_document`）

**Files:**
- Modify: `src/cart_db/extraction.py`
- Modify: `tests/test_extraction.py`

**Interfaces:**
- Consumes: Task 3 的 `flatten`、Task 2 的 `load_document`；`cart_db.llm` 的 `extract` 与 `count_tokens`；`cart_db.config` 的 `settings`、`cost_cny`
- Produces:
  - `build_system_prompt() -> str`
  - `extract_document(path: str | Path, *, out_dir: str | Path | None = None, dry_run: bool = False) -> list[NormalizedData]`

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

    captured = {}

    def fake_extract(*, schema, document, system_prompt, purpose, **kw):
        captured["document"] = document
        captured["purpose"] = purpose
        return Extraction(binders=[Binder(
            name="ARB-202",
            evidence=[BinderEvidence(**_ev_kwargs(kd=2.4))])])

    monkeypatch.setattr(extraction.llm, "extract", fake_extract)

    out_dir = tmp_path / "out"
    rows = extraction.extract_document(doc, out_dir=out_dir)

    assert "Kd = 2.4 nM" in captured["document"]      # 正文送进去了
    assert "Smith 2020" not in captured["document"]   # 参考文献没送
    assert captured["purpose"] == "article_extraction"

    written = (out_dir / "PMC1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(written) == len(rows) == 2
    first = json.loads(written[0])
    assert first["table"] == "binder"
    assert first["data"]["name"] == "ARB-202"


def test_extract_document_writes_utf8_not_escaped(tmp_path, monkeypatch):
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")
    monkeypatch.setattr(extraction.llm, "extract", lambda **kw: Extraction(
        binders=[Binder(name="抗体", evidence=[])]))

    extraction.extract_document(doc, out_dir=tmp_path / "out")
    raw = (tmp_path / "out" / "PMC1.jsonl").read_text(encoding="utf-8")
    assert "抗体" in raw          # 不是 抗体


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

Run: `./.venv/bin/python -m pytest tests/test_extraction.py -v -k "prompt or extract_document or dry_run"`
Expected: FAIL，`AttributeError: module 'cart_db.extraction' has no attribute 'build_system_prompt'`

- [ ] **Step 3: 追加实现**

`src/cart_db/extraction.py` 顶部 import 区补上：

```python
import json

from . import llm
from .config import cost_cny, settings
```

文件末尾追加：

```python
PROMPT_PATH = Path(__file__).with_name("article_extraction_prompt.txt")
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "Schema"

# 抽取规则（article_extraction_prompt.txt）讲的是「抽什么」，
# 这段讲的是「怎么摆」—— 嵌套形式、组合用序号、json 字段用键值对。
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
- Field names here omit the table prefix used in Evidence.yaml: write `kd`,
  not `binder.kd`.
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
        estimated = cost_cny(input_tokens, 3000)      # 输出按方案估的 3k token 算
        logger.info(
            "%s：输入 %d token，预计约 ¥%.2f（输出按 3000 token 估）",
            path.name, input_tokens, estimated,
        )
        return []

    result = llm.extract(
        schema=Extraction,
        document=document,
        system_prompt=system_prompt,
        purpose="article_extraction",
    )
    rows = flatten(result)

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

Run: `./.venv/bin/python -m pytest tests/ -v`
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
    code = cli.main([str(doc), "--out-dir", str(tmp_path / "out"), "--dry-run"])

    assert code == 0
    assert seen["dry_run"] is True
    assert seen["path"] == str(doc)


def test_cli_reports_missing_file(tmp_path, capsys):
    sys.path.insert(0, str(REPO / "scripts"))
    import extract as cli

    code = cli.main([str(tmp_path / "nope.xml")])
    assert code == 1
    assert "不存在" in capsys.readouterr().err
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `./.venv/bin/python -m pytest tests/test_extraction.py -v -k cli`
Expected: FAIL，找不到 `scripts/extract.py`

- [ ] **Step 3: 写 `scripts/extract.py`**

```python
#!/usr/bin/env python
"""从一份 PDF / XML 文档抽取结构化数据。

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
    parser.add_argument("file", help="要抽取的 .pdf / .xml / .nxml 文件")
    parser.add_argument("--out-dir", default=None,
                        help="结果目录，默认 data/normalised/")
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

- [ ] **Step 4: 给 Makefile 加目标**

在 `.PHONY` 那一行末尾追加 ` extract`，并在「原始数据下载」一节之前插入：

```makefile
# ---- 文本抽取 ------------------------------------------------------------
extract:  ## 从一份 PDF/XML 抽取数据：make extract FILE=data/raw/europe_pmc/x.xml
	$(PY) scripts/extract.py $(FILE) $(ARGS)
```

- [ ] **Step 5: 运行全部测试，确认通过**

Run: `./.venv/bin/python -m pytest tests/ -v`
Expected: 全部通过（新增 3 条）

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
- Produces: 一份人工核对过的 `data/normalised/<文件名>.jsonl`，以及对成本估算的确认

- [ ] **Step 1: 准备一篇真实文献**

```bash
ls data/raw/europe_pmc/
```

若目录下没有 `.xml` 全文，先下载：

```bash
make download-litc
```

- [ ] **Step 2: 先估成本**

```bash
./.venv/bin/python scripts/extract.py data/raw/europe_pmc/<文件名>.xml --dry-run
```

Expected: 打印类似 `输入 42000 token，预计约 ¥0.95`。
若单篇明显超过 ¥1.5，记下实际数字——设计文档第 10 节按每篇 ¥1.0–1.5 估算了全量 600 篇的总额，偏差要反馈。

- [ ] **Step 3: 实跑一篇**

```bash
./.venv/bin/python scripts/extract.py data/raw/europe_pmc/<文件名>.xml
```

Expected: 打印 `写出 N 行`，并生成 `data/normalised/<文件名>.jsonl`。

- [ ] **Step 4: 人工核对**

```bash
./.venv/bin/python -c "
import json, collections, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
print(collections.Counter(r['table'] for r in rows))
for r in rows[:5]:
    print(r['table'], json.dumps(r['data'], ensure_ascii=False)[:200])
" data/normalised/<文件名>.jsonl
```

对照原文逐项确认：

1. 抽出的 Binder / CAR / 工艺数量与文中实际描述的一致，没有凭空多出来的实体。
2. 每条 evidence 的 `binder.binder_id` 确实指向正确的那个 Binder。
3. 数值和单位与原文一致，范围值（如 `Kd = 2–5 nM`）没有被擅自取中位数。
4. `source_id` 是文中真实的 PMID / PMCID / DOI，不是编的。
5. 序列（`vh_sequence` 等）与原文逐字符一致。

- [ ] **Step 5: 检查日志里被丢弃的行**

跑的时候留意 WARNING。若大量证据因「缺少出处」被丢弃，说明提示词需要更明确地要求模型填写出处——把观察结果记下来，不要靠放宽校验来让数字变好看。

- [ ] **Step 6: 记录结果**

```bash
git add data/normalised/
git commit -m "chore: first real extraction output for manual review"
```

---

## 完成标准

- `./.venv/bin/python -m pytest tests/ -v` 全绿（约 34 条）。
- `make extract FILE=<一篇真实 XML>` 能产出 jsonl。
- 人工核对确认：实体数量正确、归属关系正确、数值与序列与原文一致、出处真实。
