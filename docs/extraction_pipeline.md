# 原始文档 → JSONL → PostgreSQL

保留现有提取后端、模型选项、提示词与校验修正流程。在原命令中增加
`--import-db`，即可接通数据库。省略这个参数仍只提取 JSONL。

## 客户演示：独立数据库，结束后清理

无需配置数据库密码或修改 `.env`。本机需已有 PostgreSQL 服务端工具；演示命令
在项目 `.pipeline-demo/` 中创建私有实例，只开放私有 Unix socket，不监听 TCP，
不连接 `.env` 中的业务数据库。模型认证和提取选项继续使用原配置。

```bash
# 替换成实际 PDF/XML 路径，并沿用你原来的 --agent、--model 等参数。
python scripts/demo_pipeline.py run --file data/raw/example.pdf

# 预览，不启动数据库，也不调用模型。
python scripts/demo_pipeline.py run --file data/raw/example.pdf --dry-run

# 提取结束后进入演示数据库查看数据；用 \q 退出。
python scripts/demo_pipeline.py psql
```

在数据库查询终端中可以执行：

```sql
SELECT * FROM cart.binder;
SELECT * FROM cart.evidence;
SELECT table_name, status, count(*) FROM cart.staged_record GROUP BY table_name, status;
```

提取产物和入库报告在 `.pipeline-demo/output/`。提取命令结束不会立即删库，便于
继续展示；再次运行相同命令可以续跑。结束展示并退出查询终端后执行：

```bash
python scripts/demo_pipeline.py cleanup
```

这会停止并删除该演示 PostgreSQL 实例，同时删除演示输出、报告和日志；输入
PDF/XML 保留。演示目录及锁文件已加入 Git 忽略规则。清理命令不会删除项目其他
提取结果，也不会操作业务数据库。原始文档必须位于 `.pipeline-demo/` 外。
运行演示或查询期间，工具会阻止另一条命令清理；中断后可再次执行清理命令。

完整演示会真实调用当前模型，费用规则与原提取入口一致；这与不调用模型的
`scripts/demo_ingest.py` 合成 JSONL 演示不同。

## 运行

在项目根目录、已安装 requirements.txt 的 Python 环境中运行。数据库使用既有
`PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`、`PGPASSWORD` 配置；密码放环境变量
或本地 `.env`，不放命令参数。先指向独立演示数据库。

```bash
# 保留你原来的 --agent、--model 等参数，只增加 --import-db。
python scripts/run_extraction_agent.py --file data/raw/example.pdf --import-db

# XML / NXML 使用相同入口；目录模式按 --workers 并发处理。
python scripts/run_extraction_agent.py --dir data/raw/demo --workers 2 --import-db

# 先检查输入、输出位置和目标数据库名称，不调用模型、不修改数据库。
python scripts/run_extraction_agent.py --file data/raw/example.xml --import-db --dry-run
```

没有指定后端时，沿用原默认值 Claude/opus；显式的 `--agent`、`--model`、
`--effort`、`--budget`、`--validation-retries` 和计价参数继续有效。
不同后端的费用上限能力沿用原实现，终端会提示实际约束。
`--no-progress` 关闭动态面板，但仍逐行显示中文阶段进度，适合录屏、重定向和终端日志。

数据库连接、迁移及 schema 核对发生在模型调用之前。使用版本化增量迁移，
仅维护 `cart` schema，不执行旧的 reset 脚本，不搬迁旧版表的数据。

## 实际处理顺序

1. 核对文档和已有结果的校验和，决定提取或续跑。
2. 使用原有 agent 提取，保留原有来源检查、校验及失败修正。
3. 保存原始提取 JSONL、校验后的 JSONL、来源依据与原文路径/校验和。
4. 入库程序再次规范化序列与单位，检查 JSONL、字段类型和引用，并保存暂存记录及问题。
5. 比较新记录与数据库中的实体/来源记录，确定新增、关联或待审核。
6. 收集同一实体的所有名称，重写外键；相同 A/B/C 组合复用，来源观测分别保留。
7. 在事务内检查引用和数据库约束，提交可确定的记录；身份不确定的实体独立入库并标记匹配结果待确认，依赖它们的证据正常保存。
8. 中文输出数量与编号，保存完整入库报告。

提取校验仍按原实现要求整份输出通过；失败草稿不入库。进入数据库阶段后，
无效记录和待审核记录不妨碍同批次中独立且有效的记录入库。
程序完成不代表全部记录已入库，以“已入库／待审核／质检未通过”数量为准。
匹配结果待确认不会自动调用另一个模型，也不会等待终端交互。

## 产物与续跑

每份文档的输出目录包含：

| 文件 | 内容 |
|---|---|
| `original.jsonl` | 模型最终通过校验的原始输出，保留原本的文档内 ID 和计量原文 |
| `data.jsonl` | 原提取器校验、补齐字段、生成 ID 和规范化单位后的 JSONL |
| `reasoning.md` | 来源依据及提取决策说明 |
| `error_log.jsonl` | 提取过程报告的异常，存在时保留 |
| `source_manifest.json` | 原文路径、原文校验和、schema 版本以及上述文件的校验和 |
| `database_report.json` | 数据库批次、各行入库映射、待审核原因和本次新增/关联数量 |
| `pipeline_error.json` | 本次流程异常的技术诊断，发生异常时写入 |

数据库同时保存 JSONL 原文、原始提取文件、manifest 和依据文件。PDF/XML 本身仍
保存在原位置，不作为大文件写进 SQL；不要删除用于核对的原始文档。

重复运行同一命令，会在原文、schema 和提取文件都一致时复用 JSONL，不再调用模型。
数据库根据 JSONL 校验和识别同一批次；即使上次已经提交而终端中断，也不会重复插入。
原文或产物有变化、不兼容的 schema 改变，或旧结果没有 manifest 时，会明确停止该文档的自动续跑。
先核对变化，再使用 `--force` 重新提取。强制重新提取是新版本，可能产生新的来源观测，
不应把它当成数据库失败后的重试方式。

终端显示中文进度、摘要与操作提示。科学字段、标识符、单位、原文及机器状态代码不翻译。
详细技术错误写入诊断文件；`python -m cart_db.ingest --json status <批次编号>` 等命令
可输出机器可读详情，普通 `status`、`publish`、`candidates` 显示中文结果。

## 入库与去重分开

质检通过的实体可以保存，不再要求先确认跨来源身份。缺少序列、多个候选、工艺信息不全
或者规范化存在待核对问题时，创建来源独立的实体，组合和证据照常关联并入库。
无效类型、缺失引用、证据与组合引用冲突仍然拦截，不能用空外键绕过。

终端与 `database_report.json` 分别记录入库状态和身份状态：

| 身份状态 | 含义 |
|---|---|
| `resolved` | 本次匹配检查完成：新增、关联已有实体或已人工确认；不代表字段完整 |
| `unresolved` | 存在疑似或多个匹配，或规范化疑点影响身份判断，已独立入库 |
| `similar` | 类似工艺，保留各自实体 ID |
| `conflict` | 明确身份冲突，显示冲突字段，禁止自动合并 |

Binder 可以凭有区分度的精确名称或来源确认的 alias 唯一匹配；泛称不证明身份。
CAR 是不含 Binder 的骨架，按有序模块类型和组件名称匹配；完整序列匹配仍保留。
名称相同但对应已知序列不同，标记“匹配信息冲突”，保存双方来源和冲突字段。多个匹配不任意选一个。

`inspect`、`candidates` 和报告中的 `identity_details` 提供审核依据。
目前不调用 Jev；已有 `decide` 仍处理尚未发布的记录，不用于合并已入库实体。
已入库实体的人工/Jev 合并执行工作流另行实现，不能直接删除一方的记录或证据。

## 制造工艺匹配

主要比较：有序分选步骤（input/output/method）、激活方法、基因导入方式、
扩增容器与模式，以及培养周期。主要维度明确且精确相同，才自动关联。
不要求 CD4:CD8 比例、MOI、每种试剂的剂量、冻存和制剂参数齐全。

基因导入方式和规范化后的培养周期相同，可判为类似工艺，但不合并 ID。
周、天和小时统一换算；不能仅根据“1–2 天”和“1–2 周”的宽泛分类认定工艺相同。
计量原文可能包含培养起止点，因此原文不同而数值相同只支持类似分组，复杂语义留给来源审核。
当前基因导入词表也支持 `CRISPR/Cas9+AAV定点插入`。

明确直接使用 PBMC、不分选，可写入现有 selection_steps 的 input/output/method。
未报告分选方法仍是未知，不能推断成“不分选”。

新增的 `process_step_status` 和 `harvest_steps` 已从活动 YAML 和工艺表移除。
迁移 003 先把已入库值存入 `cart.retired_manufacturing_fields` 再删除活动列；
历史 JSONL 原文不变。导入旧 JSONL 时，这两个已撤销字段单独记入审计，不再参与身份判定。
旧版 002 提取 manifest 可复用原产物，重新按当前规则质检入库，无需重新调用模型。
已应用的历史迁移文件不修改，以便现有演示数据库正常升级。

## 验证

`tests/test_pipeline.py` 替代付费 agent 调用，真实执行提取器的输出校验、文件保存、
数据库迁移、匹配和入库。覆盖 PDF/XML、续跑、提交后中断、质检失败、制造工艺匹配与旧库迁移。
它验证流程集成，不代表真实文献提取准确率。

```bash
# CART_TEST_DSN 指向可创建临时数据库的隔离 PostgreSQL 实例。
PYTHONPATH=src python -m pytest tests/test_pipeline.py tests/test_ingest.py -q
```
