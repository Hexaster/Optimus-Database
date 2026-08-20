-- 1.6 DB1：ABC 组合（A 提供 Binder + 工艺，B 提供 CAR）
CREATE TABLE IF NOT EXISTS db1.combo (
  uid              text PRIMARY KEY,
  binder_uid       text NOT NULL REFERENCES binder.binder(uid),
  car_construct_uid text NOT NULL REFERENCES car.construct(uid),
  process_uid      text REFERENCES process.process(uid),

  -- 同一实验组合判定：三库记录是否出自同一实验
  same_experiment  boolean,
  link_rule        text,
  link_confidence  numeric(4,3),

  -- 标签（字段规范/方案：相似度、来源等级、实验阶段）
  similarity       numeric(5,4),
  evidence_level   core.evidence_level,
  source_weight    numeric(3,2) GENERATED ALWAYS AS (core.weight_of(evidence_level)) STORED,
  experiment_stage text,
  labels           jsonb,

  trainable        boolean NOT NULL DEFAULT false,  -- 是否可用于训练（目标 ≥100 条）
  batch_id         uuid REFERENCES core.batch_run(batch_id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (binder_uid, car_construct_uid, process_uid)
);
CREATE INDEX IF NOT EXISTS db1_trainable_idx ON db1.combo (trainable);

-- 1.7 DB2：在 DB1 基础上构建，预留预测结果字段
CREATE TABLE IF NOT EXISTS db2.record (
  uid              text PRIMARY KEY,
  combo_uid        text NOT NULL REFERENCES db1.combo(uid),

  -- 实测结果
  observed_metrics jsonb,

  -- ===== 预留：预测结果字段，阶段1.2 模型产出后写入，本期留空 =====
  predicted_affinity      numeric,
  predicted_cytotoxicity  numeric,
  predicted_persistence   numeric,
  predicted_metrics       jsonb,
  prediction_model        text,
  prediction_version      text,
  predicted_at            timestamptz,

  batch_id         uuid REFERENCES core.batch_run(batch_id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (combo_uid)
);
