-- 1.3 制造工艺数据库：每条 = 一套工艺 / 方案
CREATE TABLE IF NOT EXISTS process.process (
  uid                text PRIMARY KEY,
  name_code          text,
  source_type        core.source_type   NOT NULL,
  source_id          text,                     -- BLA 编号 / EPAR 文档号 / DOI
  experiment_conditions text,
  evidence_level     core.evidence_level NOT NULL,
  source_weight      numeric(3,2) GENERATED ALWAYS AS (core.weight_of(evidence_level)) STORED,
  version            text,
  entry_date         date NOT NULL DEFAULT current_date,
  citation           text,
  applicable_scenario text,
  contrary_evidence  text,

  -- ===== 起始材料 =====
  t_cell_source      process.t_cell_source,
  cd4_cd8_ratio      text,
  starting_quality   text,

  -- ===== 激活 =====
  activation_method  text,                     -- CD3/CD28 磁珠等
  activation_reagents text,

  -- ===== 基因导入 =====
  vector             process.vector_type,
  moi                numeric,
  transduction_condition text,

  -- ===== 扩增 =====
  culture_system     text,
  cytokines          text,                     -- IL-2 / IL-7 / IL-15
  culture_days       numeric,

  -- ===== 冻存 / 配方 =====
  cryo_condition     text,
  formulation        text,

  -- ===== 放行指标 =====
  viability_pct      numeric,
  transduction_efficiency_pct numeric,
  vcn                numeric,                  -- 载体拷贝数
  cd3_positive_pct   numeric,
  phenotype          text,                     -- 记忆 / 耗竭 / Treg
  sterility          text,
  mycoplasma         text,
  endotoxin          text,
  cytotoxicity       text,
  cytokine_release   text,

  -- ===== 关联 =====
  car_construct_uid  text REFERENCES car.construct(uid),
  product_name       text,                     -- Kymriah / Yescarta ...

  batch_id           uuid REFERENCES core.batch_run(batch_id),
  registry_id        bigint REFERENCES core.source_registry(id),
  merged_into        text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
