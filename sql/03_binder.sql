-- Schema_A.yaml：Binder 核心实体与 1:N 证据。
CREATE TABLE IF NOT EXISTS binder.binder (
  binder_id            uuid PRIMARY KEY,
  name                 text,
  scfv_sequence        text,
  vh_sequence          text,
  vl_sequence          text,
  linker               text,
  numbering_scheme     text,
  fr_cdr_regions       jsonb,
  cdr_lengths          jsonb,
  vdj_genes            jsonb,
  germline_origin      text,
  somatic_mutations    jsonb,
  target_antigen       text,
  glycosylation_sites  jsonb,
  free_cysteines       jsonb,
  humanization_level   text,
  structure_template   text,
  complex_structure    text,
  version              text NOT NULL DEFAULT '1.0',
  entry_date           date NOT NULL DEFAULT current_date
);

CREATE INDEX IF NOT EXISTS binder_target_antigen_idx
  ON binder.binder (target_antigen);

CREATE TABLE IF NOT EXISTS binder.binder_evidence (
  evidence_id                uuid PRIMARY KEY,
  binder_id                  uuid NOT NULL REFERENCES binder.binder (binder_id),
  source_type                text NOT NULL
    CHECK (source_type IN ('public_database', 'literature', 'patent', 'internal_data')),
  source_id                  text NOT NULL,
  citation                   text,
  evidence_level             text NOT NULL,
  experimental_conditions    jsonb,
  applicable_scenario        text,
  contrary_evidence          boolean NOT NULL DEFAULT false,
  epitope                    text,
  binding_site               text,
  kd                         numeric CHECK (kd >= 0),
  kon                        numeric CHECK (kon >= 0),
  koff                       numeric CHECK (koff >= 0),
  measurement_method         text CHECK (measurement_method IN ('SPR', 'BLI')),
  measurement_conditions     jsonb,
  cross_reactivity_protein   jsonb,
  cross_reactivity_cell      jsonb,
  species_reactivity         jsonb,
  tm                         numeric,
  viscosity                  numeric CHECK (viscosity >= 0),
  aggregation_tendency       text,
  solubility                 text,
  hydrophobicity             numeric,
  charge                     numeric,
  immunogenicity_ada_risk    text
);

CREATE INDEX IF NOT EXISTS binder_evidence_binder_id_idx
  ON binder.binder_evidence (binder_id);
CREATE INDEX IF NOT EXISTS binder_evidence_source_type_idx
  ON binder.binder_evidence (source_type);
CREATE INDEX IF NOT EXISTS binder_evidence_source_id_idx
  ON binder.binder_evidence (source_id);
