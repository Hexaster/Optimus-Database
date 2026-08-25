-- 平台支撑表：来源登记、批次、归并留痕与用量计费。
-- Binder/CAR/Manufacturing 的业务字段以 docs/Schema 中的 YAML 为准。

-- 数据源登记：Day3 建立，Day4 下载时逐条写入，支撑 Day14 引用可追溯性检查
CREATE TABLE IF NOT EXISTS core.source_registry (
  id              bigserial PRIMARY KEY,
  source_name     text NOT NULL,              -- SAbDab / CARTiBASE / Google Patents ...
  used_for        text,                       -- Binder / CAR / 工艺 / 文献 / 专利
  owner           text,                       -- A / B / 共同
  api_endpoint    text,
  file_format     text,
  snapshot_version text,                      -- 上游版本号，无则记快照日期
  downloaded_at   timestamptz NOT NULL DEFAULT now(),
  local_path      text NOT NULL,
  sha256          text,                       -- 校验和：原始文件指纹
  record_count    integer,
  notes           text,
  UNIQUE (source_name, snapshot_version, local_path)
);

-- 批次：每次 Parser / 抽取 / 入库运行一条，失败可定位重跑
CREATE TABLE IF NOT EXISTS core.batch_run (
  batch_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stage        text NOT NULL,                 -- parse / extract / load / qc / merge
  target       text NOT NULL,                 -- binder / car / manufacturing / lit / patent / db1
  started_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz,
  ok_count     integer DEFAULT 0,
  fail_count   integer DEFAULT 0,
  status       text DEFAULT 'running',        -- running / done / failed
  notes        text
);

-- LLM 用量：Day3 埋点，喂给「8.预算与用量追踪」
CREATE TABLE IF NOT EXISTS core.llm_usage (
  id             bigserial PRIMARY KEY,
  batch_id       uuid REFERENCES core.batch_run(batch_id),
  called_at      timestamptz NOT NULL DEFAULT now(),
  model          text NOT NULL,
  purpose        text,                        -- lit_extract / patent_extract / qc ...
  input_tokens   integer NOT NULL DEFAULT 0,
  output_tokens  integer NOT NULL DEFAULT 0,
  cache_read_tokens     integer NOT NULL DEFAULT 0,
  cache_write_tokens    integer NOT NULL DEFAULT 0,
  cost_cny       numeric(12,4) NOT NULL DEFAULT 0,
  request_id     text
);
-- 按时间戳建索引：timestamptz::date 随时区变（STABLE 而非 IMMUTABLE），不能做索引表达式
CREATE INDEX IF NOT EXISTS llm_usage_called_idx ON core.llm_usage (called_at);

-- 每日用量视图：直接抄进跟踪表的 token 与费用两列
CREATE OR REPLACE VIEW core.llm_usage_daily AS
SELECT called_at::date              AS day,
       round(sum(input_tokens)  / 1e6, 3) AS input_mtok,
       round(sum(output_tokens) / 1e6, 3) AS output_mtok,
       round(sum(cost_cny), 2)            AS cost_cny
FROM core.llm_usage GROUP BY 1 ORDER BY 1;

-- 跨库去重归并留痕：同一 Binder/CAR 的不同来源记录归并后保留原始记录
CREATE TABLE IF NOT EXISTS core.merge_log (
  id            bigserial PRIMARY KEY,
  merged_at     timestamptz NOT NULL DEFAULT now(),
  entity_kind   text NOT NULL,                -- binder / car / manufacturing
  kept_uid      text NOT NULL,                -- 归并后保留的主记录
  merged_uid    text NOT NULL,                -- 被并入的记录（原记录不删除）
  rule          text NOT NULL,                -- 判定依据：序列相似度阈值 / ID 对齐 / 人工
  similarity    numeric(5,4),
  operator      text,
  UNIQUE (entity_kind, merged_uid)
);
