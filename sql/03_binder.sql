-- 1.1 结合域数据库：每条 = 一个抗体 / binder
CREATE TABLE IF NOT EXISTS binder.binder (
  -- ===== 公共元数据（字段规范：每条都要）=====
  uid                text PRIMARY KEY,
  name_code          text,
  source_type        core.source_type   NOT NULL,
  source_id          text,                       -- DOI / 专利号 / 登录号 / 内部批次
  experiment_conditions text,
  evidence_level     core.evidence_level NOT NULL,
  source_weight      numeric(3,2) GENERATED ALWAYS AS (core.weight_of(evidence_level)) STORED,
  version            text,
  entry_date         date NOT NULL DEFAULT current_date,
  citation           text,                       -- 可回溯到源文档具体位置
  applicable_scenario text,
  contrary_evidence  text,

  -- ===== 序列 =====
  vh_seq             text,
  vl_seq             text,
  scfv_seq           text,
  linker             text,
  format             binder.binder_format,

  -- ===== 编号 / 注释 =====
  numbering          binder.numbering_scheme,
  cdr_h1 text, cdr_h2 text, cdr_h3 text,
  cdr_l1 text, cdr_l2 text, cdr_l3 text,
  cdr_lengths        jsonb,                      -- {"H1":5,"H2":17,...}
  vdj_genes          text,
  germline           text,
  somatic_mutations  text,

  -- ===== 靶点 / 表位 =====
  target_antigen     text,                       -- GCC / CDH17 ...
  epitope_position   text,
  epitope_kind       binder.epitope_type,
  binding_site       text,

  -- ===== 亲和力（单位统一在 Day12 执行）=====
  kd_nm              numeric,                    -- 统一存 nM
  kon_m1s1           numeric,
  koff_s1            numeric,
  measure_method     text,                       -- SPR / BLI
  measure_condition  text,

  -- ===== 特异性 =====
  cross_reactivity   text,
  species_reactivity text,                       -- 人 / 鼠 / 猴

  -- ===== 成药性标签 =====
  tm_celsius         numeric,
  viscosity          numeric,
  aggregation        text,
  solubility         text,
  hydrophobicity     numeric,
  net_charge         numeric,
  glycosylation_sites text,
  free_cysteine      text,
  humanization       text,
  immunogenicity_risk text,

  -- ===== 结构 =====
  structure_template text,
  complex_structure  text,                       -- PDB ID 或预测标识
  prediction_confidence numeric,

  -- ===== 状态 / 功能 =====
  development_stage  text,                       -- 已完成实验阶段，用于筛选与打标
  patent_status      text,
  in_vitro_readout   text,

  -- ===== 溯源 =====
  batch_id           uuid REFERENCES core.batch_run(batch_id),
  registry_id        bigint REFERENCES core.source_registry(id),
  merged_into        text,                       -- 非空表示已并入该 uid
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS binder_target_idx  ON binder.binder (target_antigen);
CREATE INDEX IF NOT EXISTS binder_source_idx  ON binder.binder (source_type, source_id);
CREATE INDEX IF NOT EXISTS binder_scfv_idx    ON binder.binder USING gin (scfv_seq gin_trgm_ops);
