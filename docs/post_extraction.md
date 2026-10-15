# 抽取后归一化与去重（v11）

适用于每篇文献/每件专利已经抽取好的五表 JSONL（每行 `{ "table": ..., "data": ... }`）。
v11 原有 `measurements.py` 与抽取输出校验已经支持部分单位转换；新批处理增加序列排版归一化、显式字段/值映射、跨文件候选发现及可追溯输出。

## 运行

在 `Fosun-db-master 11` 目录、已安装项目依赖的 Python 环境中：

```bash
PYTHONPATH=src python -m cart_db.postprocess \
  /path/to/paper-A/data.jsonl /path/to/patent-B/data.jsonl \
  --output-dir data/postprocessed/batch-001
```

每个文件代表一份完整文档抽取，必须包含主键和被引用的实体；不能把同一文档的各表拆成不同输入文件。输入顺序不影响结果。IDs 按输入绝对路径、表和原 ID 确定性生成，外键同步改写。同文件相同主键且归一化内容完全一致的重复行只输出一次；冲突主键、未知字段、无效结构、悬空外键使整个批次失败。每个输入行仍有 provenance，删除的序列化重复行仍留痕。未报告的可空字段补 null，保持与既有 agent_output 校验口径一致。

所有文档内外键改写完成后，再检查 evidence 与其 combination_id 指向的 ABC 组合是否一致。每个非 null 的 binder.binder_id、car.car_id、manufacturing.manufacturing_id 必须与组合中对应的实体 ID 相同；矛盾时整个批次失败，不猜测哪一方正确。检查不依赖 evidence 与组合行的先后顺序。缺失的直接实体引用仍为 null，不从组合自动补齐；evidence 仍须至少直接引用一个实体。此检查在 postprocess 批处理入口实施。

如确有经过确认的历史字段或枚举别名，可追加：

```bash
--rules examples/post_extraction/rules.example.json
```

示例仅展示语法，使用前核对自己的抽取格式。field_aliases 的键是对象路径，value_aliases 的键是完整字段路径；数组路径不带下标，例如 `car.modules.module_type`。两种字段同时出现且值不一致时失败，不覆盖。原文名称/基因/抗原不自动映射。将旧版平铺 VH 字符串映射到新版 heavy_chain 对象仍会类型校验失败，需要显式转换并注明 scope；重命名不改变结构。

## 输出

| 文件 | 内容 |
|---|---|
| normalized.jsonl | 五表格式归一化记录，保留不同 ID 的实体和证据 |
| provenance.jsonl | 每个输入行的原始完整记录、文件、行号、原 ID、新 ID |
| audit.jsonl | 字段路径、变更前后值、原因，以及无法换算/不确定残基的复核事件 |
| dedup_candidates.jsonl | 候选组及匹配依据；全部 review_required |
| summary.json | 输入/输出数量、序列化重复删除数、复核事件数、候选组数 |

不覆盖输入；输出目录已存在时拒绝运行。相同路径、内容和规则重复运行得到相同记录 ID；移动文件会改变命名空间，因此增量跑批应固定来源路径。当前输出是交接文件，不执行 SQL 入库或科学实体归并；已有数据库 ID 也会被当作文档局部标签重映射，所以不要用于重写已入库记录。

序列只去 ASCII 空白并转大写；数字、标题、缺口等保留并提示复核，不猜 OCR。X/B/Z/J/U/O 保留并标记，不用于确定性序列候选。linker 名称保留。模块顺序不排序，scope 不推断，缺序列不补齐。

测量按 YAML preferred_unit 转换，仅支持明确同量纲单位。单位别名采用明确列表，大小写不折叠；不推算分子量、比例/百分数语义或未知单位。raw 不改写。支持既有浓度、时间、结合速率和温度，以及新增体积、细胞密度、EU 密度和 °C 冷却速率。无法转换的单位保留并列入 audit。

测量处理顺序为：校验原始 measurement 的字段、类型、kind 与数值分量关系 → 单位别名替换 → 同量纲换算 → 在整条记录校验时再次检查结果。value、lower、upper、error 中的布尔值和数字字符串在任何换算前即被拒绝，防止 true 被算成 1；换算后再次校验可拒绝浮点溢出。前置校验不改变 audit 中的原始 before 值，也不会仅因补 null 而产生单位变更事件。

候选索引包含完整非主键 payload、确定的 scFv、scope 为 variable_region 的完整 VH/VL 配对、全模块有确定序列的有序 CAR 模块列表、名称/别名。同一候选特征不等于生物学同一性。工艺目前使用完整 payload 与名称/别名候选；不进行模糊工艺、序列相似度或专利族推断。未出现在候选组中不证明两实体不同。大批量时按候选组送审，避免全量两两比较。

CAR 的 exact_ordered_backbone_modules 指纹只使用按原顺序排列的 [{module_type, sequence}, ...]。每个模块仍须有仅含标准氨基酸字母的非空序列；模块数量、边界、类型、序列或顺序不同不会获得该索引的匹配。source_molecule 和 length 不参与该指纹，因此缺报或不同的可选注释不会遮蔽序列候选；这些字段完整保留在 normalized 和 provenance 中供复核，注释冲突不被覆盖。候选仍全部标记 review_required，不自动合并。

## 复核流程

本流程的人工复核提示词保存在 `docs/post_extraction/prompts/`，由复核者按需使用，不由程序自动加载。可执行的别名规则示例保存在 `examples/post_extraction/rules.example.json`，通过 `--rules` 显式传入。

1. 对 audit 中 review 事件使用 `docs/post_extraction/prompts/01_normalization.md`；提供对应原文和 Schema。
2. 对候选组使用 `docs/post_extraction/prompts/02_deduplication.md`；提供记录、其证据/组合及来源定位。
3. 人工确认实体身份、冲突保留策略、survivor 与外键映射后，再实施归并。实体归并与实验去重分别决定。已有 SQL `core.merge_log` 是留痕基础，但当前五表 YAML 与 SQL 历史结构有差异，本模块不假定二者可直接导入。
4. 归并后检查所有引用、来源、个体/聚合观测及相反证据均被保留；归并失败需能用 provenance 回滚。

测试：`PYTHONPATH=src python -m pytest tests/test_postprocess.py -q`。

## 可运行示例与验证结果

`examples/post_extraction/paper.jsonl` 与 `patent.jsonl` 是明确标记的合成数据，不代表真实科学结果。两文件都使用 b1/e1，包含同序列的不同名称、独立测量以及一条重复序列化行：

```bash
PYTHONPATH=src python -m cart_db.postprocess \
  examples/post_extraction/paper.jsonl examples/post_extraction/patent.jsonl \
  --output-dir data/postprocessed/demo-001
```

预期：5 条输入 → 4 条输出；删除 1 条序列化重复；两实体保留为不同 ID，并产生序列候选；两来源 evidence 都保留；0.002 ± 0.0003 µM → 2 ± 0.3 nM，raw 不变。

2026-10-09 验证：新增 9 项测试全部通过；命令行合成示例与拒绝覆盖检查通过。既有 44 项测试中 20 项失败、24 项通过；在去除本次修改的临时副本中重现相同 20 项失败，包括旧测量标量/字段/枚举与当前 Schema 不一致、缺失旧接口/脚本。这些既有问题未纳入本次改动。

2026-10-12 修复后验证：postprocess 共 52 项测试通过（原 9 项 + 新增 43 个参数化回归用例），覆盖换算前类型校验、换算后溢出、CAR 可选注释差异、三类实体与组合的一致性、前向引用及缺失直接引用。独立复核的 41 项检查全部通过，包含合成示例、输入顺序可复现性、来源保留与拒绝覆盖。全套测试 76 项通过、20 项失败；与修复前逐项比较，原有测试结果及失败名单一致。
