-- QC 框架：Day14 自动化验证与 Day16 人工验证共用一张问题清单
CREATE TABLE IF NOT EXISTS qc.finding (
  id           bigserial PRIMARY KEY,
  found_at     timestamptz NOT NULL DEFAULT now(),
  check_kind   text NOT NULL,      -- field_format / unit / completeness / traceability / duplicate / manual
  severity     qc.severity NOT NULL,
  entity_kind  text NOT NULL,
  entity_uid   text,
  field_name   text,
  message      text NOT NULL,
  auto         boolean NOT NULL DEFAULT true,   -- true=自动化发现, false=人工/专家评审
  status       text NOT NULL DEFAULT 'open',    -- open / fixed / accepted / wontfix
  fixed_at     timestamptz,
  operator     text,
  batch_id     uuid REFERENCES core.batch_run(batch_id)
);
CREATE INDEX IF NOT EXISTS qc_open_idx ON qc.finding (status, severity);

-- QC 通过率：Day15 复核门槛 ≥95%
CREATE OR REPLACE VIEW qc.pass_rate AS
SELECT count(*) FILTER (WHERE status IN ('fixed','accepted'))::numeric
       / NULLIF(count(*),0) AS pass_rate,
       count(*) FILTER (WHERE status='open' AND severity='P0') AS open_p0,
       count(*) FILTER (WHERE status='open' AND severity='P1') AS open_p1
FROM qc.finding;

-- 数量指标：与「5.数量指标KPI」对齐，一条 SQL 拿到全部当前值
CREATE OR REPLACE VIEW qc.kpi AS
SELECT
  (SELECT count(*) FROM binder.binder WHERE merged_into IS NULL
     AND target_antigen ~* '(GCC|GUCY2C|CDH17)')                       AS binder_gcc_cdh17,
  (SELECT count(*) FROM binder.binder WHERE merged_into IS NULL
     AND source_type='公开库')                                          AS binder_public,
  (SELECT count(*) FROM binder.binder WHERE merged_into IS NULL
     AND source_type IN ('文献','专利'))                                AS binder_extracted,
  (SELECT count(*) FROM car.construct WHERE merged_into IS NULL)        AS car_construct,
  (SELECT count(*) FROM car.module   WHERE merged_into IS NULL)         AS car_module,
  (SELECT count(*) FROM process.process WHERE merged_into IS NULL)      AS process_total,
  (SELECT count(*) FROM lit.article)                                    AS lit_downloaded,
  (SELECT count(*) FROM lit.article WHERE selected)                     AS lit_selected,
  (SELECT count(*) FROM patent.patent)                                  AS patent_downloaded,
  (SELECT count(*) FROM patent.patent WHERE selected)                   AS patent_selected,
  (SELECT count(*) FROM db1.combo WHERE trainable)                      AS db1_trainable,
  (SELECT count(*) FROM db2.record)                                     AS db2_records;
