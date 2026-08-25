-- Schema_C.yaml：制造工艺核心实体与 1:N 证据。
CREATE TABLE IF NOT EXISTS manufacturing.manufacturing (
  manufacturing_id                   uuid PRIMARY KEY,
  name                               text,
  t_cell_source                      text,
  cd4_cd8_ratio                      text,
  starting_cell_quality              jsonb,
  activation_method                  text,
  reagents                           jsonb,
  vector_type                        text,
  moi                                numeric CHECK (moi >= 0),
  transduction_transfection_conditions jsonb,
  culture_system                     text,
  cytokine_combination               jsonb,
  culture_duration                   text,
  cryopreservation_conditions        jsonb,
  formulation                        jsonb,
  corresponding_car_product          text,
  version                            text NOT NULL DEFAULT '1.0',
  entry_date                         date NOT NULL DEFAULT current_date
);

CREATE TABLE IF NOT EXISTS manufacturing.manufacturing_evidence (
  evidence_id              uuid PRIMARY KEY,
  manufacturing_id         uuid NOT NULL
    REFERENCES manufacturing.manufacturing (manufacturing_id),
  source_type              text NOT NULL
    CHECK (source_type IN ('public_database', 'literature', 'patent', 'internal_data')),
  source_id                text NOT NULL,
  citation                 text,
  evidence_level           text NOT NULL,
  experimental_conditions  jsonb,
  applicable_scenario      text,
  contrary_evidence        boolean NOT NULL DEFAULT false,
  cell_viability           numeric CHECK (cell_viability BETWEEN 0 AND 100),
  transduction_efficiency  numeric CHECK (transduction_efficiency BETWEEN 0 AND 100),
  vcn                      numeric CHECK (vcn >= 0),
  cd3_positive_ratio       numeric CHECK (cd3_positive_ratio BETWEEN 0 AND 100),
  memory_phenotype         text,
  exhaustion_phenotype     text,
  treg_phenotype           text,
  sterility                text,
  mycoplasma               text,
  endotoxin                text,
  killing_activity         text,
  cytokine_release         jsonb
);

CREATE INDEX IF NOT EXISTS manufacturing_evidence_manufacturing_id_idx
  ON manufacturing.manufacturing_evidence (manufacturing_id);
CREATE INDEX IF NOT EXISTS manufacturing_evidence_source_type_idx
  ON manufacturing.manufacturing_evidence (source_type);
CREATE INDEX IF NOT EXISTS manufacturing_evidence_source_id_idx
  ON manufacturing.manufacturing_evidence (source_id);
