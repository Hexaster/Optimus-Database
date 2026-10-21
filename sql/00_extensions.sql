-- 扩展与 schema：可重复执行
CREATE EXTENSION IF NOT EXISTS "pgcrypto";      -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";       -- 名称模糊匹配，用于实体归并
-- pgvector 为阶段1.2 的智能体检索预留；本地若未装 pgvector，跳过而不中断建库
-- Attempt the optional vector extension without making it a prerequisite for legacy setup.
DO $$ BEGIN
  CREATE EXTENSION IF NOT EXISTS "vector";
-- This catches all ordinary SQL errors, including permission failures, not just a missing extension.
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'pgvector 未安装，已跳过（阶段1.1 用不到，阶段1.2 前补上即可）';
END $$;

CREATE SCHEMA IF NOT EXISTS core;     -- 来源登记、批次、归并留痕、LLM 用量
CREATE SCHEMA IF NOT EXISTS binder;        -- 1.1 Binder 实体与证据
CREATE SCHEMA IF NOT EXISTS car;           -- 1.2 CAR 实体与证据
CREATE SCHEMA IF NOT EXISTS manufacturing; -- 1.3 制造工艺实体与证据
CREATE SCHEMA IF NOT EXISTS lit;      -- 1.4 文献库
CREATE SCHEMA IF NOT EXISTS patent;   -- 1.5 专利库
CREATE SCHEMA IF NOT EXISTS db1;      -- 1.6 ABC 组合库
CREATE SCHEMA IF NOT EXISTS db2;      -- 1.7 在 DB1 基础上构建，预留预测字段
CREATE SCHEMA IF NOT EXISTS qc;       -- QC 框架
