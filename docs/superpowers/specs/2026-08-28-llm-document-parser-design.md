# LLM 文本解析器设计（PDF / XML → NormalizedData）

日期：2026-08-28
状态：待实现

## 1. 背景与目标

数据库有两条入库通道：

- **结构化通道（已存在）**：CSV / Excel → `docs/Mapping/*.yaml` 字段映射 →
  `NormalizedData(table, data)` → `data/normalised/<source>.jsonl`。
  代码见 `src/cart_db/parser/therasabdab.py`。
- **文本通道（本设计）**：文献全文 XML、专利与 EPAR PDF → LLM 抽取 →
  同样的 `NormalizedData` → 同样的 jsonl。

两条通道的差别只在「字段值从哪里来」：结构化通道靠列名映射，文本通道靠 LLM 阅读全文。
下游（校验、去重、入库）共用一套 jsonl 契约，不为文本通道另建一条路。

输入来自已有的两个下载目标：

    make download-litc    # Europe PMC 全文 XML → data/raw/europe_pmc/
    make download-epar    # EMA EPAR PDF        → data/raw/ema_epar/

目标：给定一个 PDF 或 XML 文件，产出一份 `data/normalised/<stem>.jsonl`，
其中每行是一条符合 `docs/Schema/*.yaml` 的 `NormalizedData`。

## 2. 现状与必须修掉的缺陷

`src/cart_db/llm.py` 状态良好，本次不改：提示词缓存、`core.llm_usage` 计费打点、
当日费用上限、Batches API 都已实现。

`src/cart_db/extraction.py` 是草稿，当前无法产出数据，原因有三：

1. `extract(schema=List[NormalizedData], ...)` 传入的是 `typing.List`，没有
   `.model_json_schema()`，调用即报错。
2. 随后读取 `result.records`，但没有任何模型定义 `records` 字段。
3. 更根本的问题：`NormalizedData.data` 是 `dict[str, Any]`，经 `llm.py` 的
   `_strict()` 处理后变成 `{"type":"object","additionalProperties":false,"required":[]}`
   —— 一个禁止出现任何属性的 schema。严格结构化输出下这条路走不通。

因此本设计的核心是：**用逐表的 Pydantic 模型替代自由 dict**，让 API 层面强制字段名、
类型与枚举，而不是仅靠提示词约束。

## 3. 已确定的设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| schema 绑定方式 | 手写逐表 Pydantic 模型 | API 强制约束；不引入 YAML→模型编译器这一层 |
| 关系表达 | 嵌套输出，Python 展平 | 证据挂在父实体内部，外键不可能悬空 |
| ABC 组合 | 列表下标引用 | 组合指向三个父实体，无法嵌套；下标越界可精确检出 |
| 输出边界 | 文件 → `data/normalised/<stem>.jsonl` | 与结构化通道同一契约；入库留给共用 loader |
| 来源信息 | 由 LLM 自行抽取 | 业务决定；`source_id` 非空由 Python 校验兜底 |
| 文档载入 | 纯文本；XML 去除参考文献段 | 最省成本，全部本地完成 |
| evidence 外键 | 三个实体外键改为 `nullable: true` | 只报道 Kd 的文献没有 car 和 manufacturing |

## 4. 数据流

    data/raw/europe_pmc/*.xml
    data/raw/ema_epar/*.pdf
            |
            v   load_document()        PDF: pymupdf 取文本
        纯文本                          XML: 原文去掉 <ref-list>/<back>/<ack>
            |
            v   llm.extract(schema=Extraction, ...)      llm.py 不改
       嵌套 Extraction 树
            |
            v   flatten()              生成 UUID、回填外键、解析组合下标
       list[NormalizedData]
            |
            v   data/normalised/<stem>.jsonl

## 5. 目标表

`docs/Schema/` 中当前有效的目标表共 6 张：

| 表 | 定义位置 |
|---|---|
| `binder` | `Schema_A.yaml` 的 binder 段 |
| `car` | `Schema_B.yaml` 的 car 段 |
| `manufacturing` | `Schema_C.yaml` 的 manufacturing 段 |
| `evidence` | `Evidence.yaml`（已合并 record 与三张 *_evidence） |
| `abc_combination_db1` | `Schema_DB1.yaml` |
| `abc_combination_experiments` | `Schema_DB1.yaml` |

`Evidence.yaml` 用带前缀的字段名区分实体，例如 `binder.kd`、`car.persistence`、
`manufacturing.vcn`。jsonl 中原样保留这些带点的键名，一行 jsonl 可以直接对着
`Evidence.yaml` 逐字段核对。

**前置条件**：`docs/Schema/Record.yaml` 以及 `Schema_A/B/C.yaml` 中残留的
`binder_evidence` / `car_evidence` / `manufacturing_evidence` 段已被业务方清理。
系统提示词整目录读取 `docs/Schema/*.yaml`，若残留未清理，模型会看到已废弃的表定义。

## 6. 抽取模型（`src/cart_db/extraction_models.py`，新增）

严格结构化输出禁止开放对象，因此所有 `type: json` 字段一律用键值对列表表达，
Python 再还原成真正的 dict。这是整个模型层唯一的变通手段：

```python
class KV(BaseModel):
    key: str
    value: str
    # [KV(key="E:T", value="5:1")] -> {"E:T": "5:1"}
```

模型树：

```python
class EvidenceBase(BaseModel):
    """Evidence.yaml 中不带实体前缀的 9 个共享字段。"""
    source_type: Literal["public_database", "literature", "patent", "internal_data"]
    source_id: str | None
    citation: str | None
    evidence_level: str | None
    experimental_conditions: list[KV] | None
    applicable_scenario: str | None
    contrary_evidence: bool
    time_of_upload: date | None
    time_of_download: date | None

class BinderEvidence(EvidenceBase):   # Evidence.yaml 的 binder.* 字段，去掉 binder_id
class CarEvidence(EvidenceBase):      # car.* 字段，去掉 car_id
class ManufacturingEvidence(EvidenceBase):  # manufacturing.* 字段，去掉 manufacturing_id

class Binder(BaseModel):              # Schema_A 的 18 个字段，去掉 binder_id
    evidence: list[BinderEvidence]

class Module(BaseModel):              # Schema_B car.modules 的 item_schema
    module_type: Literal["linker", "hinge", "transmembrane_region",
                         "costimulatory_domain", "CD3zeta", "tag", "safety_switch"]
    source_molecule: str | None
    sequence: str | None
    length: int | None

class Car(BaseModel):
    name: str | None
    modules: list[Module]
    evidence: list[CarEvidence]

class Manufacturing(BaseModel):       # Schema_C 的 15 个字段，去掉 manufacturing_id
    evidence: list[ManufacturingEvidence]

class Experiment(EvidenceBase):
    outcomes: list[KV]

class Combination(BaseModel):
    binder_index: int
    car_index: int
    manufacturing_index: int
    similarity: str | None
    completed_experiment_phase: Literal["design_only", "in_vitro", "in_vivo",
        "preclinical", "clinical_phase_1", "clinical_phase_2", "clinical_phase_3"] | None
    experiments: list[Experiment]

class Extraction(BaseModel):          # 传给 llm.extract() 的根 schema
    binders: list[Binder]
    cars: list[Car]
    manufacturings: list[Manufacturing]
    combinations: list[Combination]
```

`source_id` 与 `evidence_level` 在 schema 中非空，模型里却声明为可空，这是有意的：
若在 JSON schema 层强制非空，模型无从填写时只能编造一个来源号。声明为可空让它可以
如实留空，再由第 8 节的校验丢弃该行——宁可少一行，不要一个假的 DOI。

三个证据模型而不是一个合并模型：严格模式要求每个键都出现，单一的 40 字段证据模型
会让模型在每一行上写约 30 个 null。拆开后每行约 22 个字段。

`Literal` 只用在 YAML 中枚举写法正确的字段上：`source_type`、`measurement_method`、
`module_type`、`car.metabolic_state`、`completed_experiment_phase`。
`t_cell_source` 与 `vector_type` 保持 `str | None`，原因见第 11 节。

## 7. `src/cart_db/extraction.py`（重写）

```python
def load_document(path: str | Path) -> str
```
按扩展名分发。`.pdf` 走 pymupdf 逐页取文本；`.xml` / `.nxml` 读原文后删除
`<ref-list>`、`<back>`、`<ack>` 三类元素——JATS 里这几段占全文相当比例，
且不含任何可抽取字段。其他扩展名抛 `ValueError`。

```python
def build_system_prompt() -> str
```
`article_extraction_prompt.txt` + `docs/Schema/*.yaml` 全目录 + 一段输出结构说明
（嵌套形式、组合用下标引用、json 字段用键值对列表）。这段前缀跨文档完全稳定，
由 `llm.py` 打上 `cache_control`，缓存命中后按输入价 0.1× 计费。

```python
def flatten(result: Extraction) -> list[NormalizedData]
```
深度优先遍历，为每个实体和每条证据生成 `uuid4`，回填外键，把 `list[KV]` 还原为 dict，
按外键顺序输出：`binder` → `car` → `manufacturing` → `evidence` →
`abc_combination_db1` → `abc_combination_experiments`。

`Combination.experiments` 中的每条实验同时产出两行：一行 `evidence`（继承自
`EvidenceBase` 的来源字段，三个实体外键均取自该组合所引用的实体），以及一行
`abc_combination_experiments`（`outcomes` 加上指向前者的 `record_id`）。

```python
def extract_document(path, *, out_dir=None, dry_run=False) -> list[NormalizedData]
```
串起全流程并写 jsonl。`dry_run=True` 时只调用 `llm.count_tokens` 打印 token 与
预估费用，不发起抽取请求。

输出示例：

```json
{"table":"binder","data":{"binder_id":"a1b2...","name":"ARB-202","target_antigen":"CDH17"}}
{"table":"evidence","data":{"record_id":"c3d4...","source_type":"literature",
  "source_id":"PMC123","evidence_level":"同行評議","binder.binder_id":"a1b2...",
  "binder.kd":2.4,"binder.measurement_method":"SPR","car.car_id":null}}
```

## 8. 校验

`flatten()` 内三项检查。任何一项失败只丢弃该行并 `logging.warning`，不让整份文档失败：

1. `source_id` 与 `evidence_level` 非空。二者是 schema 的非空列，但在抽取模型中
   声明为可空（理由见第 6 节）；来源信息由 LLM 自行抽取，空的 `source_id` 正是需要
   拦下的情形。`source_type` 由 API 的 `Literal` 强制，不需在此重复检查。
2. 组合的三个下标在对应列表范围内。越界即丢弃该组合并记录。
3. 枚举值合法。API 已强制，此项仅防 schema 漂移。

## 9. CLI 与测试

```
scripts/extract.py <file> [--out-dir data/normalised] [--dry-run]
make extract FILE=data/raw/europe_pmc/xxx.xml
```

仓库目前没有测试框架。新增 `pytest` 依赖与 `tests/test_extraction.py`，
只覆盖不花钱的部分：

- `flatten()`：UUID 生成、外键回填、KV 还原 dict、组合下标解析、越界丢弃、输出顺序。
- XML 段落剥离：确认 `<ref-list>` 被删除且正文完整保留。
- `load_document()` 对未知扩展名抛错。

真实文档的端到端验证靠 `--dry-run` 估算 + 单份文档人工核对，不写进自动化测试。

## 10. 成本

系统提示词约 7–8k token（首次之后按 0.1× 缓存价计费），一篇 JATS 全文约
30–60k token，输出约 3k token。按 `config.py` 的计价口径，**每份文档约 ¥1.0–1.5**。
方案中的 400 篇文献 + 200 件专利合计约 **¥700–900**，而
`CART_LLM_DAILY_CAP_CNY` 默认为 800，跑批时会触上限。

`llm.py` 的 `submit_batch` / `fetch_batch` 已实现，Batches API 按标准价 50% 计费。
本期不接，但跑全量之前应当接上。

## 11. 需要业务方处理的 schema 问题

1. `Evidence.yaml` 的 `binder.binder_id`、`car.car_id`、`manufacturing.manufacturing_id`
   当前为 `nullable: false`，本次改为 `nullable: true`（已确认）。
2. `Schema_C.yaml` 的 `t_cell_source` 用键名 `allowed values`、`vector_type` 用
   `allowed value`，均非 `allowed_values`；且列表项写作 `-自体`（短横线后无空格），
   YAML 会解析成单个字符串而非列表。修正前这两个字段在模型中保持 `str | None`。
3. `Schema_DB1.yaml` 的 `completed_experiment_phase` 同样使用 `allowed values`，
   但列表本身格式正确，可直接取用。
4. `sql/*.sql` 仍是合并前的表结构（`binder_evidence`、`car_evidence`、
   `manufacturing_evidence` 分立，另有一张语义不同的 `core.evidence`）。
   本设计以 `docs/Schema/*.yaml` 为准，SQL 的同步不在本期范围内。

## 12. 本期不做

- 超长专利的分块。先用 token 计数拦截，真的触发再处理。
- 跨文档实体去重与归一。
- 写入 Postgres。
- PDF 的版面/表格感知解析（原生 document block）。文本抽取会压平表格，
  若人工核对显示表格数值丢失严重，再评估。
- Batches API 批量跑批。

## 13. 实现顺序

1. `requirements.txt` 增加 `pymupdf`、`pytest`。
2. `docs/Schema/Evidence.yaml` 三个外键改 `nullable: true`。
3. `src/cart_db/extraction_models.py` —— 逐表模型。
4. `src/cart_db/extraction.py` —— `load_document`、`build_system_prompt`、`flatten`。
5. `tests/test_extraction.py` —— 覆盖 `flatten` 与 XML 剥离。
6. `scripts/extract.py` 与 Makefile 的 `extract` 目标。
7. 用一份真实 Europe PMC XML 跑 `--dry-run` 核对成本，再实跑一份并人工核对结果。
