-- 1.2 CAR 结构库：模块级 + 整装级两层（字段规范：推荐引擎按 A×B×C 拼模块）
CREATE TABLE IF NOT EXISTS car.module (
  uid                text PRIMARY KEY,
  name_code          text,
  source_type        core.source_type   NOT NULL,
  source_id          text,
  experiment_conditions text,
  evidence_level     core.evidence_level NOT NULL,
  source_weight      numeric(3,2) GENERATED ALWAYS AS (core.weight_of(evidence_level)) STORED,
  version            text,
  entry_date         date NOT NULL DEFAULT current_date,
  citation           text,
  applicable_scenario text,
  contrary_evidence  text,

  -- ===== 标识 =====
  module_type        car.module_type NOT NULL,
  source_molecule    text,                    -- CD28 / 4-1BB ...
  sequence           text,
  length_aa          integer,

  -- ===== 功能属性（尤其共刺激域）=====
  activation_speed   text,
  metabolic_state    text,                    -- 糖酵解 / 氧化
  expansion_capacity text,
  memory_phenotype   text,                    -- Tscm / Tcm / Tem
  persistence        text,
  exhaustion_risk    text,
  tonic_signaling    text,

  -- ===== 铰链 / 跨膜属性 =====
  epitope_distance_effect text,
  synapse_effect     text,
  tonic_effect       text,

  -- ===== 组合约束 =====
  compatible_modules   jsonb,                 -- ["uid1","uid2"]
  incompatible_modules jsonb,
  assembly_rules       text,

  batch_id           uuid REFERENCES core.batch_run(batch_id),
  registry_id        bigint REFERENCES core.source_registry(id),
  merged_into        text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS car_module_type_idx ON car.module (module_type);
CREATE INDEX IF NOT EXISTS car_module_src_idx  ON car.module (source_molecule);

-- 整装构型：识别域-linker-铰链-跨膜-共刺激域-CD3ζ
CREATE TABLE IF NOT EXISTS car.construct (
  uid                text PRIMARY KEY,
  name_code          text,
  source_type        core.source_type   NOT NULL,
  source_id          text,
  experiment_conditions text,
  evidence_level     core.evidence_level NOT NULL,
  source_weight      numeric(3,2) GENERATED ALWAYS AS (core.weight_of(evidence_level)) STORED,
  version            text,
  entry_date         date NOT NULL DEFAULT current_date,
  citation           text,
  applicable_scenario text,
  contrary_evidence  text,

  binder_uid         text REFERENCES binder.binder(uid),
  scfv_module_uid    text REFERENCES car.module(uid),
  linker_module_uid  text REFERENCES car.module(uid),
  hinge_module_uid   text REFERENCES car.module(uid),
  tm_module_uid      text REFERENCES car.module(uid),
  costim_module_uid  text REFERENCES car.module(uid),
  cd3z_module_uid    text REFERENCES car.module(uid),
  full_sequence      text,
  vector_backbone    text,
  logic              car.logic_gate DEFAULT '无',
  validated_function text,
  risk_tags          jsonb,

  batch_id           uuid REFERENCES core.batch_run(batch_id),
  merged_into        text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
