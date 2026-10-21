-- 仅开发期使用：整库重建。Schema 在 Day5-13 还会调整，DDL 必须可反复执行
-- CASCADE removes dependent legacy objects and data; cart is not among the schemas reset here.
DROP SCHEMA IF EXISTS qc, db2, db1, patent, lit, manufacturing, process, car, binder, core CASCADE;
