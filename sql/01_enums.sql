-- 枚举：字段规范中「来源类型 / 证据等级」等受控词表。可重复执行
DO $$ BEGIN
  CREATE TYPE core.source_type AS ENUM ('公开库','文献','专利','内部');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 证据等级：内部实验 ＞ 同行评议 ＞ 专利/预印本 ＞ 模型预测
DO $$ BEGIN
  CREATE TYPE core.evidence_level AS ENUM ('内部实验','同行评议','专利预印本','模型预测');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE binder.numbering_scheme AS ENUM ('IMGT','Kabat','Chothia');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE binder.binder_format AS ENUM ('scFv','VHH','Fab','IgG','其他');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE binder.epitope_type AS ENUM ('线性','构象','未知');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE car.module_type AS ENUM
    ('识别域','linker','铰链','跨膜区','共刺激域','CD3ζ','标签','安全开关');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE car.logic_gate AS ENUM ('无','AND','OR','NOT');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE process.t_cell_source AS ENUM ('自体','异体','未知');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE process.vector_type AS ENUM ('慢病毒','逆转录病毒','转座子','电转','其他','未知');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE qc.severity AS ENUM ('P0','P1','P2');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 证据等级 → 来源可信度权重（字段规范：1.0 / 0.7 / 0.4 / 0.2）
CREATE OR REPLACE FUNCTION core.weight_of(lvl core.evidence_level)
RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE lvl
    WHEN '内部实验'     THEN 1.0
    WHEN '同行评议'     THEN 0.7
    WHEN '专利预印本'   THEN 0.4
    WHEN '模型预测'     THEN 0.2
  END::numeric
$$;
