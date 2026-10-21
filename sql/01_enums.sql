-- 只保留非业务表所需的 QC 枚举。Schema_A/B/C 中的受控字符串
-- 在各表上以 CHECK 约束实现，使列本身仍与 YAML 的 string 类型一致。

-- Create the historical QC severity vocabulary once; reruns reuse the existing enum.
DO $$ BEGIN
  CREATE TYPE qc.severity AS ENUM ('P0','P1','P2');
-- Ignore only an already-existing type; other errors propagate and stop this SQL file.
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
