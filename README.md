# CAR-T 数据库环境（阶段1.1 · Day3 环境搭建产出）

完整 PDF/XML → JSONL → PostgreSQL 流程：参见 [提取与入库操作说明](docs/extraction_pipeline.md)。
在现有提取命令后增加 `--import-db`，保留原后端与模型，中文显示进度，支持校验后的续跑。

中文只读数据浏览：运行 `python scripts/browse_database.py --demo`，打开 http://127.0.0.1:8765 。参见 [浏览页面说明](docs/database_browser.md)。

当前 JSONL 入库入口：参见 [数据库入库流程与演示](docs/database_import.md)。
`python -m cart_db.ingest` 支持归一化、QC、暂存、实体比对、人工决策和事务发布；
版本化迁移在独立 `cart` schema 中创建与当前 YAML 对齐的表，不覆盖旧库。
下面的 Day3 SQL/setup 说明保留为旧版环境文档，不作为当前科学数据的入库接口。

七个数据库的统一开发环境：代码仓库骨架、Python 环境、PostgreSQL 建表脚本、
Raw Data 存储规范、LLM 用量计费打点。对应 18 天计划里 Day3「环境搭建」的六项任务。

**当前定位：本地优先。** 云服务器与 SSH 不在本期范围；`ANTHROPIC_API_KEY` 先留空，
本地建库完全不需要它，等 Day7 做提示词工程时再填进 `.env`。

## 快速开始

```bash
cd CAR-T数据库环境
./setup.sh          # venv + 依赖 + 数据库 + 建表 + 冒烟测试，一条命令跑完
```

没有 Docker 的话走 Homebrew（本机已按这条路装好并验证通过）：

```bash
brew install postgresql@17 pgvector
brew services start postgresql@17
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"   # keg-only，需手动加
createuser -s cart && createdb -O cart cart
./setup.sh
```

`postgresql@17` 是 keg-only，`psql` / `pg_isready` 不会自动进 PATH。`setup.sh` 内部会
自动探测 keg 路径，但你要在终端里直接用 `psql`，得把上面那行 export 加进 `~/.zshrc`。

常用命令（`make` 查看全部）：

| 命令 | 作用 |
|---|---|
| `make init` | 执行建表脚本（幂等，可反复跑） |
| `make reset` | 整库删除后重建 —— Schema 改动后用这个 |
| `make smoke` | 端到端冒烟测试 |
| `make kpi` | 打印当前数量指标，抄进跟踪表「5.数量指标KPI」 |

## 目录

```
sql/                建表脚本，按文件名顺序执行，全部幂等
  00_extensions     扩展与 9 个 schema
  01_enums          受控词表 + 证据等级→权重映射函数
  02_core           来源登记 / 批次 / 用量 / 归并留痕
  03_binder         1.1 结合域库
  04_car            1.2 CAR 库（模块级 + 整装级）
  05_process        1.3 制造工艺库
  06_lit_patent     1.4 文献库 + 1.5 专利库 + 抽取证据表
  07_db1_db2        1.6 ABC 组合 + 1.7 预测预留
  08_qc             QC 问题清单 + 通过率视图 + KPI 视图
  99_drop_all       整库删除（仅开发期）
src/cart_db/
  config.py         环境变量与计价口径
  db.py             连接、DDL 执行、批次上下文
  storage.py        Raw Data 目录规范、校验和、来源登记
  llm.py            Claude 调用、结构化抽取、用量打点、批量接口
scripts/            init_db.py（建表）· smoke_test.py（冒烟）
data/raw/           原始数据：<source>/<snapshot>/<file>，不入 Git
docs/               目录与命名规范、Day3 验收清单
```

## 表结构要点

建表脚本按你已有的《第一阶段数据库字段规范》生成，不是另起一套：

- **公共元数据**（唯一ID、名称、来源类型、来源ID、实验条件、证据等级、来源可信度权重、
  版本、录入日期、引用/适用场景/相反证据）在 binder、car、process 三库中逐字段落地。
- **来源可信度权重不手填** —— `source_weight` 是生成列，由 `evidence_level` 经
  `core.weight_of()` 自动映射（内部实验 1.0 / 同行评议 0.7 / 专利预印本 0.4 / 模型预测 0.2），
  从根上杜绝等级与权重对不上。
- **CAR 库两层**：`car.module`（模块级，带兼容/不兼容约束）+ `car.construct`（整装构型），
  对应字段规范里「推荐引擎按 A×B×C 拼模块」的设计。
- **`core.evidence`** 记录每个字段的证据出处（文档 + 章节/权利要求号/SEQ ID NO + 原文引用 +
  置信度）。Day14「引用可追溯性检查」直接查这张表。
- **`qc.kpi` 视图**一条 SQL 返回全部数量指标，`make kpi` 即可打印。

## 与 18 天计划的对应

| 计划任务 | 这里的落点 |
|---|---|
| Day3 代码仓库 + 目录规范 | 本仓库结构 + `.gitignore` |
| Day3 venv + 依赖锁定 | `setup.sh` + `requirements.txt` |
| Day3 PostgreSQL + 七库建表 | `sql/` + `make init`（幂等） |
| Day3 密钥管理（.env 不入库） | `.env.example` + `.gitignore` |
| Day3 Raw Data 存储规范 | `storage.raw_dir()` + `core.source_registry` |
| Day3 冒烟测试全绿 | `make smoke` |
| Day4 原始数据登记 | `storage.register()` 写来源、版本、时间、校验和 |
| Day7 入库代码 | `db.batch()` 批次上下文 + 各表 `batch_id` 外键 |
| Day12 跨库去重归并 | `core.merge_log` + `merged_into` 字段 |
| Day14 自动化 QC | `qc.finding` + `qc.pass_rate` |

## LLM 用量与成本

`llm.py` 默认 `claude-sonnet-5` —— 方案《六、成本预算》就是按 Claude Sonnet 5
的 ¥20.2/M 输入、¥101/M 输出测算的。每次调用自动写一条 `core.llm_usage`；
跟踪表「8.预算与用量追踪」的 token 与费用两列直接取自 `core.llm_usage_daily` 视图：

```sql
SELECT * FROM core.llm_usage_daily;
```

三个已经内置的省钱/防跑飞措施：

1. **提示词缓存** —— 抽取规则放 system 轮并打 `cache_control`，3,600 份文档共用同一段
   长提示词，命中缓存后这部分按输入价的 0.1× 计费。
2. **Batches API** —— `submit_batch()` / `fetch_batch()` 走批量接口，token 按标准价的
   **50%** 计费。Day10–11 的 400 篇文献 + 200 件专利不赶时间，走批量可把这部分预算减半。
3. **单日费用上限** —— `CART_LLM_DAILY_CAP_CNY`（默认 ¥800），超限抛
   `DailyCapExceeded` 中止，避免批量任务半夜跑飞。

跑批前先用 `llm.count_tokens()` 估算输入规模，核对方案里 ~180M 输入 token 的估算是否成立。
