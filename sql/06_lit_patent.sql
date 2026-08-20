-- 1.4 文献库 / 1.5 专利库：下载与筛选留痕，抽取结果回填三库
CREATE TABLE IF NOT EXISTS lit.article (
  uid            text PRIMARY KEY,
  doi            text,
  pmid           text,
  pmcid          text,
  title          text,
  journal        text,
  pub_year       integer,
  authors        text,
  abstract       text,

  -- 高质量筛选规则的两个维度（3,000 → 400）
  source_rank    text,                 -- 来源等级
  experiment_stage text,               -- 已完成实验阶段
  selected       boolean NOT NULL DEFAULT false,
  select_reason  text,

  fulltext_available boolean DEFAULT false,
  fulltext_format text,                -- JATS XML / PDF / 仅摘要
  fulltext_path  text,
  retrieved_from text,                 -- OpenAlex / Europe PMC / PubMed
  registry_id    bigint REFERENCES core.source_registry(id),
  batch_id       uuid REFERENCES core.batch_run(batch_id),
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (doi)
);
CREATE INDEX IF NOT EXISTS lit_selected_idx ON lit.article (selected);

CREATE TABLE IF NOT EXISTS patent.patent (
  uid            text PRIMARY KEY,
  pub_number     text NOT NULL,        -- 公开号
  family_id      text,
  title          text,
  assignee       text,
  inventors      text,
  priority_date  date,
  pub_date       date,
  abstract       text,

  source_rank    text,
  experiment_stage text,
  selected       boolean NOT NULL DEFAULT false,   -- 600 → 200
  select_reason  text,

  claims_path    text,                 -- 权利要求分段结果
  examples_path  text,                 -- 实施例分段结果
  seq_listing_path text,               -- 序列表 ST.26 / ST.25
  seq_id_count   integer,              -- 该专利含多少 SEQ ID NO
  retrieved_from text DEFAULT 'Google Patents',
  registry_id    bigint REFERENCES core.source_registry(id),
  batch_id       uuid REFERENCES core.batch_run(batch_id),
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pub_number)
);
CREATE INDEX IF NOT EXISTS patent_selected_idx ON patent.patent (selected);

-- 抽取证据：每条结构化数据回溯到源文档的具体位置（Day14 可追溯性检查依赖这张表）
CREATE TABLE IF NOT EXISTS core.evidence (
  id             bigserial PRIMARY KEY,
  entity_kind    text NOT NULL,        -- binder / car_module / car_construct / process
  entity_uid     text NOT NULL,
  field_name     text NOT NULL,        -- 该证据支撑的字段
  doc_kind       text NOT NULL,        -- lit / patent
  doc_uid        text NOT NULL,
  locator        text NOT NULL,        -- 章节 / 段落 / 权利要求号 / SEQ ID NO
  quoted_text    text,
  confidence     numeric(4,3),
  extracted_at   timestamptz NOT NULL DEFAULT now(),
  batch_id       uuid REFERENCES core.batch_run(batch_id)
);
CREATE INDEX IF NOT EXISTS evidence_entity_idx ON core.evidence (entity_kind, entity_uid);
