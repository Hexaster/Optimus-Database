# 用大模型从文献和专利中抽取数据：设计文档

日期：2026-08-28
状态：待实现

## 0. 一句话说明

我们要做一个程序：喂给它一篇文献全文或一份专利 PDF，它读完之后，把里面提到的
Binder、CAR 骨架、制造工艺以及各种实验结果，整理成数据库能直接收下的表格数据。

这件事之所以要用大模型（LLM），是因为文献是写给人看的散文，没有固定格式。
Kd 值可能写在正文里，也可能藏在表格的某一格，还可能只出现在图注。
写死的规则处理不了这种情况，只能让模型读懂之后再填表。

## 1. 背景：我们有两条入库通道

数据进入数据库有两条路，走哪一条取决于原始数据长什么样：

**第一条，结构化通道（已经做好了）。**
原始数据本身就是表格，例如 Thera-SAbDab 的 CSV。这种情况下，我们只需要写一份对照表
（`docs/Mapping/*.yaml`），说明「原表的第 3 列对应数据库的 vh_sequence 字段」，
程序照着搬就行，不需要模型参与。代码见 `src/cart_db/parser/therasabdab.py`。

**第二条，文本通道（本文档要做的）。**
原始数据是文章。这里没有「第 3 列」可言，需要模型通读全文，判断哪些内容对应哪个字段。

两条通道最后必须产出同样格式的结果，这样后面的校验、去重、入库等步骤只要写一套。
共同的交接格式是 `NormalizedData`，也就是一行一条记录，每条记录写明「这条数据属于哪张表」
和「各字段的值」。

输入文件已经有现成的下载命令：

    make download-litc    # Europe PMC 文献全文 XML → data/raw/europe_pmc/
    make download-epar    # EMA 审评报告 PDF        → data/raw/ema_epar/

**本文档的目标**：给一个 PDF 或 XML 文件，产出一份结果文件
`data/normalised/<文件名>.jsonl`，里面每一行都是一条符合数据库表结构的记录。

## 2. 现在的草稿为什么跑不通

`src/cart_db/llm.py` 写得很完整，本次一行都不用改。它已经做好了这几件事：
调用模型、把重复的提示词缓存起来省钱、每次调用都记一笔账到数据库、
当天花费超过上限就自动拦下、以及批量提交接口。

问题出在 `src/cart_db/extraction.py`，它目前是一份跑不出结果的草稿，有三个毛病：

1. 传给模型的「答题格式」参数写成了 `List[NormalizedData]`。这在 Python 里不是一个
   可用的格式定义，调用当场就会报错。
2. 拿结果时读了 `result.records`，但没有任何地方定义过 `records` 这个东西。
3. 最要命的一条：`NormalizedData` 里的 `data` 字段被定义成「随便什么内容都行的字典」。
   而我们用的是**强制格式模式**——事先告诉模型「你只准填这些字段」，模型就填不出别的。
   在这个模式下，「随便什么内容都行」会被翻译成「一个字段都不准填」。
   也就是说，按现在的写法，模型只能返回空结果。

第 3 条决定了整个设计的方向：**必须为每张表写出明确的字段清单**，
让「不该出现的字段」在接口层面就填不进来，而不是只在提示词里叮嘱模型别乱填。

## 3. 已经拍板的决策

| 事项 | 决定 | 为什么 |
|---|---|---|
| 怎么约束模型填的字段 | 为每张表手写一份字段清单 | 接口层面直接卡死字段名、类型和可选值；不额外做一个「从 YAML 自动生成清单」的工具 |
| 怎么表达数据之间的关系 | 让模型输出嵌套结构，程序再拆平 | 见下方说明 |
| ABC 组合怎么处理 | 用列表序号引用 | 见下方说明 |
| 做到哪一步为止 | 产出 jsonl 结果文件即可 | 与结构化通道交接格式一致；写进数据库这一步两条通道共用，以后再写 |
| 文献出处谁来填 | 模型自己从原文里读 | 业务方决定；程序会检查出处是否为空，空的就丢弃该行 |
| 文件怎么读进来 | 都转成纯文本；XML 去掉参考文献部分 | 最省钱，全部在本地完成，不额外调用服务 |
| evidence 表的三个关联字段 | 从「必填」改为「可以为空」 | 见下方说明 |

**关于「嵌套结构」。**
一篇文献里可能有 3 个 Binder，每个各做了 2 组实验。程序最后要写进数据库的是一行行平表，
每条实验结果都得注明它属于哪个 Binder。让模型直接输出平表的话，它需要自己编号再互相引用，
容易指错。所以我们让模型把实验结果直接写在对应 Binder 的内部，像这样：

```
Binder ARB-202
  └─ 实验一：Kd = 2.4 nM，SPR 测定
  └─ 实验二：Tm = 68°C
Binder 5F9
  └─ 实验一：Kd = 40 nM，SPR 测定
```

归属关系由位置本身决定，不可能指错。程序再把这棵树拆成平表，顺手给每个 Binder 生成一个
唯一编号，填到对应的实验记录上。

**关于「ABC 组合」。**
一个 ABC 组合同时指向三样东西：一个 Binder、一个 CAR 骨架、一套制造工艺。
它没法「嵌套」在其中任何一个里面，否则另外两个的信息就丢了。
所以组合用序号来指：`binder_index: 0` 表示「上面 Binder 列表里的第 1 个」。
序号的好处是，模型如果写了个 7 而列表里只有 2 个 Binder，程序一眼就能发现并丢弃，
不会稀里糊涂地关联到错误的实体上。

**关于「evidence 表的三个关联字段」。**
`Evidence.yaml` 目前要求每条证据必须同时填写 Binder、CAR、制造工艺三个编号。
但一篇只测了亲和力的抗体文献，根本没有 CAR 也没有制造工艺。
按现在的规定，这类数据一条都存不进来——而这恰恰是文献里最常见的内容。
所以把这三个字段改为可以为空：一条证据说清楚它是关于谁的即可，其余留空。

## 4. 整体流程

    data/raw/europe_pmc/*.xml   （文献全文）
    data/raw/ema_epar/*.pdf     （审评报告）
            │
            ▼  第一步：把文件转成纯文本
        纯文本                    PDF 逐页取字；XML 删掉参考文献等无关段落
            │
            ▼  第二步：连同「填表说明」一起交给模型
      模型返回的嵌套结果          填表说明 = 抽取规则 + 数据库表结构说明
            │
            ▼  第三步：拆平
      一行行的表格数据            生成唯一编号、填好归属关系、检查明显错误
            │
            ▼  第四步：写文件
    data/normalised/<文件名>.jsonl

`.jsonl` 是一种朴素的文本格式：一行一条记录，可以直接用文本编辑器打开逐行核对。

## 5. 要填的六张表

`docs/Schema/` 里目前有效的目标表是这六张：

| 表 | 装什么 | 定义位置 |
|---|---|---|
| `binder` | Binder 本身的信息，如序列、靶点 | `Schema_A.yaml` |
| `car` | CAR 骨架的模块构成 | `Schema_B.yaml` |
| `manufacturing` | 制造工艺参数 | `Schema_C.yaml` |
| `evidence` | 所有实验结果与其出处 | `Evidence.yaml` |
| `abc_combination_db1` | 一个具体的 A+B+C 组合 | `Schema_DB1.yaml` |
| `abc_combination_experiments` | 该组合做过的实验 | `Schema_DB1.yaml` |

`evidence` 是一张合并表，用带前缀的字段名区分内容属于哪一类，
例如 `binder.kd`、`car.persistence`、`manufacturing.vcn`。
结果文件里原样保留这些带点的字段名，这样一行结果可以直接对着 `Evidence.yaml` 逐字核对。

**开工前提**：`docs/Schema/Record.yaml`，以及 `Schema_A/B/C.yaml` 里残留的
`binder_evidence`、`car_evidence`、`manufacturing_evidence` 三段，都已被合并进
`Evidence.yaml`，需要业务方先行删除。程序会把 `docs/Schema/` 整个目录读给模型看，
残留的旧定义会让模型去填已经不存在的表。

## 6. 字段清单（新增 `src/cart_db/extraction_models.py`）

这个文件是本次工作的核心，内容基本就是把 `docs/Schema/*.yaml` 的字段
一条条翻译成 Python 的写法，交给模型当作答题格式。

有一个地方需要变通。强制格式模式不允许「内容任意的对象」，
而表结构里有不少字段是 `json` 类型，也就是内容事先说不准的——
比如「实验条件」可能是温度、缓冲液、效靶比，每篇文献都不一样。
这类字段一律用「键值对列表」表达，程序收到后再还原成正常结构：

```python
class KV(BaseModel):
    key: str
    value: str
    # 模型写 [KV(key="效靶比", value="5:1")]，程序还原成 {"效靶比": "5:1"}
```

整体结构如下：

```python
class EvidenceBase(BaseModel):
    """Evidence.yaml 中不带实体前缀的字段：出处与实验背景，三类证据共用。"""
    source_type: Literal["public_database", "literature", "patent", "internal_data"]
    source_id: str | None            # DOI、专利号、登录号
    citation: str | None
    evidence_level: str | None
    experimental_conditions: list[KV] | None
    applicable_scenario: str | None
    contrary_evidence: bool          # 是否与主流结论相反
    time_of_upload: date | None
    time_of_download: date | None
    outcomes: list[KV] | None        # 仅 ABC 组合实验用

class BinderEvidence(EvidenceBase): ...          # 加上 Evidence.yaml 的 binder.* 字段
class CarEvidence(EvidenceBase): ...             # 加上 car.* 字段
class ManufacturingEvidence(EvidenceBase): ...   # 加上 manufacturing.* 字段

class Binder(BaseModel):             # Schema_A 的字段，去掉编号列（编号由程序生成）
    evidence: list[BinderEvidence]   # 该 Binder 的实验结果就写在这里

class Module(BaseModel):             # CAR 的一个模块
    module_type: Literal["linker", "hinge", "transmembrane_region",
                         "costimulatory_domain", "CD3zeta", "tag", "safety_switch"]
    source_molecule: str | None
    sequence: str | None
    length: int | None

class Car(BaseModel):
    name: str | None
    modules: list[Module]            # 按 CAR 中的实际顺序排列
    evidence: list[CarEvidence]

class Manufacturing(BaseModel):      # Schema_C 的字段，去掉编号列
    evidence: list[ManufacturingEvidence]

class Combination(BaseModel):
    binder_index: int                # 指向上面 binders 列表的第几个
    car_index: int
    manufacturing_index: int
    similarity: str | None
    completed_experiment_phase: Literal["design_only", "in_vitro", "in_vivo",
        "preclinical", "clinical_phase_1", "clinical_phase_2", "clinical_phase_3"] | None
    experiments: list[EvidenceBase]  # 组合层面的实验，结果写在 outcomes 里

class Extraction(BaseModel):         # 交给模型的完整答题格式
    binders: list[Binder]
    cars: list[Car]
    manufacturings: list[Manufacturing]
    combinations: list[Combination]
```

**两处刻意的取舍，供审阅时注意：**

其一，`source_id` 和 `evidence_level` 在表结构里是必填的，这里却允许留空。
这是故意的。如果在答题格式上强制必填，模型遇到确实找不到出处的情况时，
唯一的出路就是编一个 DOI 出来。允许留空，它才能如实空着，
再由第 8 节的检查把这行丢掉。宁可少一行，也不要一个假的出处。

其二，证据拆成三个清单而不是合并成一个。合并的话，
每条证据都要把 binder、car、manufacturing 三类字段全写一遍，
而强制格式模式要求每个字段都得出现，模型会在每行上写三十来个「无」。
拆开之后每行只需写二十来个字段，一份文档下来能省下可观的费用。

## 7. 主程序（重写 `src/cart_db/extraction.py`）

四个函数：

**`load_document(path)` —— 把文件读成纯文本。**
PDF 用 pymupdf 逐页取字。XML 读进来之后删掉 `<ref-list>`、`<back>`、`<ack>`
这几段，也就是参考文献、致谢和附录。文献里这几段往往占相当篇幅，
而且不含任何要抽取的内容，删掉是纯粹的省钱。其他格式的文件直接报错。

**`build_system_prompt()` —— 拼出给模型的填表说明。**
由三部分组成：现有的 `article_extraction_prompt.txt`（抽取规则）、
`docs/Schema/` 整个目录（表结构和每个字段的中文说明）、
以及一段输出格式说明（嵌套写法、组合用序号引用、json 字段用键值对列表）。
这段说明对每一篇文档都完全一样，`llm.py` 会把它标记为可缓存内容，
第二篇文档开始，这部分只按一折计费。

**`flatten(result)` —— 把嵌套结果拆成平表。**
逐层遍历，给每个实体和每条证据生成一个唯一编号，填好归属关系，
把键值对列表还原成正常结构，然后按顺序输出各表的记录：
先 `binder`、`car`、`manufacturing`，再 `evidence`，最后是两张组合表。
顺序有讲究——被引用的实体必须先出现，后面引用它的记录才有编号可填。

组合实验会同时产出两行：一行写进 `evidence`（出处、实验条件、
结果都在这里，三个实体编号取自该组合所引用的实体），
另一行写进 `abc_combination_experiments`，只保留关联信息，指向前者。
同一份结果不存两遍。

**`extract_document(path, out_dir=None, dry_run=False)` —— 串起全流程。**
加上 `dry_run=True` 时只估算这篇文档要花多少钱，不真的发起抽取。

产出的结果文件长这样：

```json
{"table":"binder","data":{"binder_id":"a1b2...","name":"ARB-202","target_antigen":"CDH17"}}
{"table":"evidence","data":{"record_id":"c3d4...","source_type":"literature",
  "source_id":"PMC123","evidence_level":"同行評議","binder.binder_id":"a1b2...",
  "binder.kd":2.4,"binder.measurement_method":"SPR","car.car_id":null}}
```

第二行的 `binder.binder_id` 与第一行的 `binder_id` 一致，
这就是「这条 Kd 数据属于 ARB-202」的表达方式。

## 8. 检查哪些错误

拆平的时候顺手做三项检查。任何一项不过，只丢弃**这一行**并在日志里写明原因，
不会让整篇文档的抽取作废：

1. **出处和证据等级不能为空。**这两个是表结构里的必填项，出处又是模型自己填的，
   空着的话这条数据无从追溯，留着反而有害。
2. **组合的序号必须在范围内。**模型指向一个不存在的 Binder，说明它把关系搞错了，
   这条组合直接丢弃。
3. **可选值字段必须是允许的取值之一。**这一项接口本身已经强制，
   这里只是防止以后表结构改了而代码没跟上。

## 9. 怎么运行、怎么测

```
scripts/extract.py <文件> [--out-dir data/normalised] [--dry-run]
make extract FILE=data/raw/europe_pmc/xxx.xml
```

仓库现在还没有测试框架，本次一并加上 `pytest` 和一个测试文件
`tests/test_extraction.py`，只测不花钱的部分：

- 拆平逻辑：编号生成、归属关系、键值对还原、组合序号解析、越界丢弃、输出顺序。
- XML 段落剥离：参考文献确实删掉了，正文确实一个字没少。
- 遇到不认识的文件格式确实会报错。

真实文档的效果不写进自动测试，靠先 `--dry-run` 估成本、再实跑一篇人工核对。

## 10. 花多少钱

计价用的是 `config.py` 里已有的口径。「token」可以粗略理解为模型处理的字数单位，
中文约一个字一个 token，英文约一个词 1.3 个。

- 填表说明：约 7–8 千 token。第一篇之后走缓存，只按一折计费。
- 一篇文献全文：约 3 万–6 万 token。
- 模型的回答：约 3 千 token。

**每篇文档约 ¥1.0–1.5。**方案里的 400 篇文献加 200 件专利，
合计约 **¥700–900**，而系统设的每日花费上限 `CART_LLM_DAILY_CAP_CNY` 默认是 800，
真跑全量会中途被拦下。

`llm.py` 里已经写好了批量提交接口，走批量按五折计费。本期不接，
但正式跑全量之前应该接上。

## 11. 需要业务方确认或处理的事

1. **`Evidence.yaml` 的三个关联字段**（`binder.binder_id`、`car.car_id`、
   `manufacturing.manufacturing_id`）当前是必填，本次改为可以为空。已确认。
2. **`Evidence.yaml` 新增了 `outcomes` 字段**，而 `Schema_DB1.yaml` 的
   `abc_combination_experiments` 也有同名字段。本设计按「结果写在 `evidence` 里，
   组合实验表只留关联」处理，请确认这是合并的本意。
3. **`Schema_C.yaml` 的可选值写法有误。**`t_cell_source` 的键名写成了
   `allowed values`（中间是空格），`vector_type` 写成了 `allowed value`，
   正确写法是 `allowed_values`；而且选项写成 `-自体`，短横线后面少一个空格，
   这样机器读出来是一整个字符串，不是一份选项清单。修好之前，
   这两个字段只能当自由文本处理，模型填什么都拦不住。
4. **`Schema_DB1.yaml` 的 `completed_experiment_phase`** 也用了 `allowed values`
   这个错误键名，但选项列表本身格式正确，改个键名即可。
5. **`sql/*.sql` 还是合并之前的表结构**（三张证据表分立，另有一张同名但含义不同的
   `core.evidence`）。本设计一律以 `docs/Schema/*.yaml` 为准，
   SQL 的同步不在本期范围内。

## 12. 本期明确不做

- **超长专利的分段处理。**先用字数统计拦一下，真遇到超长的再说。
- **跨文档的实体去重。**同一个 Binder 在十篇文献里出现，现在会产出十条独立记录，
  合并是后面单独的一步。
- **写进 Postgres。**先产出结果文件，入库两条通道共用一套代码，以后再写。
- **PDF 的表格识别。**目前 PDF 取出来的是纯文字，表格会被压成一行行文本，
  表格里的数值可能读串。如果人工核对发现这个问题严重，再评估要不要改用
  能看懂版面的方式（更准，但更贵）。
- **批量提交。**见第 10 节。

## 13. 实现顺序

1. `requirements.txt` 补上 `pymupdf` 和 `pytest`（前者代码里已经在用，但从来没声明过）。
2. 改 `docs/Schema/Evidence.yaml` 的三个关联字段为可以为空。
3. 写 `src/cart_db/extraction_models.py`（字段清单）。
4. 重写 `src/cart_db/extraction.py`（读文件、拼说明、拆平）。
5. 写 `tests/test_extraction.py`。
6. 写 `scripts/extract.py` 和 Makefile 的 `extract` 命令。
7. 拿一篇真实的 Europe PMC 文献先 `--dry-run` 核对成本，再实跑一篇，人工核对结果。

## 附录：术语表

| 术语 | 意思 |
|---|---|
| LLM / 大模型 | 这里指 Claude，负责读文章、填表 |
| token | 模型处理文字的计量单位，计费按它算。中文约一字一个 |
| 强制格式模式 | 调用模型时预先规定「只准填这些字段」，模型填不出规定外的内容 |
| 提示词缓存 | 每次调用都重复的那段说明只算一次全价，之后按一折计费 |
| 字段清单（Pydantic 模型） | 用 Python 写出的「这张表有哪些字段、各是什么类型」 |
| 关联字段（外键） | 一张表里指向另一张表某条记录的那一列，例如「这条 Kd 属于哪个 Binder」 |
| 唯一编号（UUID） | 程序生成的一长串不重复的编号，用来给记录之间建立关联 |
| 嵌套 / 拆平 | 模型按「实验写在实体内部」的树状结构作答；程序再拆成数据库的一行行平表 |
| jsonl | 一行一条记录的文本文件，可直接用编辑器打开核对 |
| JATS | 文献全文 XML 的通用格式，Europe PMC 用的就是它 |
