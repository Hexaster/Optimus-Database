-- Version 1: new scientific storage. Existing schemas and data are untouched.
-- Scalar fields follow active YAML; measurements and nested fields retain JSON structure.
CREATE TABLE cart.import_contract (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton), schema_hash text NOT NULL
);
INSERT INTO cart.import_contract(schema_hash) VALUES ('c46191a74ce60f1ce5c663e91895a96432c725fdfe744e6b13614a9f53545d88');
CREATE TABLE cart.record (
  record_id uuid PRIMARY KEY,
  table_name text NOT NULL CHECK (table_name IN ('binder','car','manufacturing','abc_combination_db1','evidence')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(record_id, table_name)
);
CREATE TABLE cart."binder" (
  "binder_id" uuid NOT NULL PRIMARY KEY,
  "name" text,
  "aliases" jsonb CHECK (jsonb_typeof("aliases") = 'array'),
  "scfv_sequence" text,
  "heavy_chain" jsonb CHECK (jsonb_typeof("heavy_chain") = 'object'),
  "light_chain" jsonb CHECK (jsonb_typeof("light_chain") = 'object'),
  "linker" text,
  "fr_cdr_regions" jsonb CHECK (jsonb_typeof("fr_cdr_regions") = 'array'),
  "cdr_length" text,
  "vdj_genes" text,
  "germline_origin" text,
  "germline_origin_identity" numeric,
  "somatic_mutations" jsonb CHECK (jsonb_typeof("somatic_mutations") = 'array'),
  "target_antigen" text,
  "glycosylation_sites" jsonb CHECK (jsonb_typeof("glycosylation_sites") = 'array'),
  "free_cysteines" jsonb CHECK (jsonb_typeof("free_cysteines") = 'array'),
  "humanization_level" text CHECK ("humanization_level" IN ('non_human','chimeric','humanized','fully_human')),
  "structure_template" jsonb CHECK (jsonb_typeof("structure_template") = 'array'),
  "complex_structure" text,
  record_kind text GENERATED ALWAYS AS ('binder'::text) STORED,
  FOREIGN KEY ("binder_id", record_kind) REFERENCES cart.record(record_id, table_name)
);
CREATE INDEX ON cart."binder" ("target_antigen");
CREATE TABLE cart."car" (
  "car_id" uuid NOT NULL PRIMARY KEY,
  "name" text,
  "modules" jsonb NOT NULL CHECK (jsonb_typeof("modules") = 'array'),
  record_kind text GENERATED ALWAYS AS ('car'::text) STORED,
  FOREIGN KEY ("car_id", record_kind) REFERENCES cart.record(record_id, table_name)
);
CREATE TABLE cart."manufacturing" (
  "manufacturing_id" uuid NOT NULL PRIMARY KEY,
  "name" text,
  "t_cell_source" text CHECK ("t_cell_source" IN ('自体','异体')),
  "cd4_cd8_ratio" jsonb CHECK (jsonb_typeof("cd4_cd8_ratio") = 'object'),
  "selection_steps" jsonb CHECK (jsonb_typeof("selection_steps") = 'array'),
  "starting_cell_quality" jsonb CHECK (jsonb_typeof("starting_cell_quality") = 'object'),
  "activation_method" text,
  "reagents" jsonb CHECK (jsonb_typeof("reagents") = 'array'),
  "vector_type" text CHECK ("vector_type" IN ('慢病毒','逆转录病毒','转座子','电转')),
  "moi" jsonb CHECK (jsonb_typeof("moi") = 'object'),
  "transduction_transfection_conditions" jsonb CHECK (jsonb_typeof("transduction_transfection_conditions") = 'object'),
  "culture_system" jsonb CHECK (jsonb_typeof("culture_system") = 'object'),
  "cytokine_combination" jsonb CHECK (jsonb_typeof("cytokine_combination") = 'array'),
  "culture_duration" jsonb CHECK (jsonb_typeof("culture_duration") = 'object'),
  "cryopreservation_conditions" jsonb CHECK (jsonb_typeof("cryopreservation_conditions") = 'object'),
  "formulation" jsonb CHECK (jsonb_typeof("formulation") = 'object'),
  record_kind text GENERATED ALWAYS AS ('manufacturing'::text) STORED,
  FOREIGN KEY ("manufacturing_id", record_kind) REFERENCES cart.record(record_id, table_name)
);
CREATE TABLE cart."abc_combination_db1" (
  "combination_id" uuid NOT NULL PRIMARY KEY,
  "binder_id" uuid NOT NULL REFERENCES cart."binder" ("binder_id"),
  "car_id" uuid NOT NULL REFERENCES cart."car" ("car_id"),
  "manufacturing_id" uuid NOT NULL REFERENCES cart."manufacturing" ("manufacturing_id"),
  "similarity" text,
  "completed_experiment_phase" text CHECK ("completed_experiment_phase" IN ('design_only','in_vitro','in_vivo','preclinical','clinical_unspecified','clinical_phase_1','clinical_phase_2','clinical_phase_3','unspecified')),
  record_kind text GENERATED ALWAYS AS ('abc_combination_db1'::text) STORED,
  FOREIGN KEY ("combination_id", record_kind) REFERENCES cart.record(record_id, table_name),
  UNIQUE(binder_id,car_id,manufacturing_id)
);
CREATE INDEX ON cart."abc_combination_db1" ("binder_id");
CREATE INDEX ON cart."abc_combination_db1" ("car_id");
CREATE INDEX ON cart."abc_combination_db1" ("manufacturing_id");
CREATE TABLE cart."evidence" (
  "record_id" uuid NOT NULL PRIMARY KEY,
  "source_type" text NOT NULL CHECK ("source_type" IN ('public_database','literature','patent','internal_data')),
  "source_id" text NOT NULL,
  "citation" text,
  "applicable_scenario" text,
  "contrary_evidence" boolean,
  "time_of_upload" date,
  "time_of_download" date,
  "combination_id" uuid REFERENCES cart."abc_combination_db1" ("combination_id"),
  "binder_id" uuid REFERENCES cart."binder" ("binder_id"),
  "binder_epitope" jsonb CHECK (jsonb_typeof("binder_epitope") = 'object'),
  "binder_binding_site" jsonb CHECK (jsonb_typeof("binder_binding_site") = 'object'),
  "binder_kd" jsonb CHECK (jsonb_typeof("binder_kd") = 'object'),
  "binder_kon" jsonb CHECK (jsonb_typeof("binder_kon") = 'object'),
  "binder_koff" jsonb CHECK (jsonb_typeof("binder_koff") = 'object'),
  "binder_measurement_method" text CHECK ("binder_measurement_method" IN ('SPR','BLI','other')),
  "binder_measurement_conditions" jsonb CHECK (jsonb_typeof("binder_measurement_conditions") = 'object'),
  "binder_ec50" jsonb CHECK (jsonb_typeof("binder_ec50") = 'object'),
  "binder_ec50_conditions" jsonb CHECK (jsonb_typeof("binder_ec50_conditions") = 'object'),
  "binder_cross_reactivity_protein" jsonb CHECK (jsonb_typeof("binder_cross_reactivity_protein") = 'array'),
  "binder_cross_reactivity_cell" jsonb CHECK (jsonb_typeof("binder_cross_reactivity_cell") = 'array'),
  "binder_species_reactivity" jsonb CHECK (jsonb_typeof("binder_species_reactivity") = 'array'),
  "binder_tm" jsonb CHECK (jsonb_typeof("binder_tm") = 'object'),
  "binder_viscosity" jsonb CHECK (jsonb_typeof("binder_viscosity") = 'object'),
  "binder_aggregation_tendency" jsonb CHECK (jsonb_typeof("binder_aggregation_tendency") = 'array'),
  "binder_solubility" jsonb CHECK (jsonb_typeof("binder_solubility") = 'object'),
  "binder_hic_retention_time" jsonb CHECK (jsonb_typeof("binder_hic_retention_time") = 'object'),
  "binder_hydrophobic_patch_area" numeric,
  "binder_hydrophobic_patch_location" text,
  "binder_sap_score" numeric,
  "binder_isoelectric_point" jsonb CHECK (jsonb_typeof("binder_isoelectric_point") = 'object'),
  "binder_net_charge" numeric,
  "binder_net_charge_ph" numeric,
  "binder_immunogenicity_ada_risk" text,
  "car_id" uuid REFERENCES cart."car" ("car_id"),
  "car_coexpressed_proteins" jsonb CHECK (jsonb_typeof("car_coexpressed_proteins") = 'array'),
  "car_activation_peak_time_min" numeric,
  "car_activation_peak_time_max" numeric,
  "car_activation_readout" text,
  "car_metabolic_state" text CHECK ("car_metabolic_state" IN ('glycolytic','oxidative','both')),
  "car_expansion_capacity" text,
  "car_tscm_ratio" jsonb CHECK (jsonb_typeof("car_tscm_ratio") = 'object'),
  "car_tcm_ratio" jsonb CHECK (jsonb_typeof("car_tcm_ratio") = 'object'),
  "car_tem_ratio" jsonb CHECK (jsonb_typeof("car_tem_ratio") = 'object'),
  "car_teff_ratio" jsonb CHECK (jsonb_typeof("car_teff_ratio") = 'object'),
  "car_exhaustion_phenotype" text,
  "car_treg_phenotype" text,
  "car_persistence" jsonb CHECK (jsonb_typeof("car_persistence") = 'object'),
  "car_tonic_signaling_tendency" text,
  "car_binder_length" numeric,
  "car_epitope_distance_effect" text,
  "car_immune_synapse_effect" text,
  "car_tonic_signaling_effect" text,
  "car_compatible_modules" jsonb CHECK (jsonb_typeof("car_compatible_modules") = 'array'),
  "car_incompatible_modules" jsonb CHECK (jsonb_typeof("car_incompatible_modules") = 'array'),
  "manufacturing_id" uuid REFERENCES cart."manufacturing" ("manufacturing_id"),
  "manufacturing_cell_viability" jsonb CHECK (jsonb_typeof("manufacturing_cell_viability") = 'object'),
  "manufacturing_transduction_efficiency" jsonb CHECK (jsonb_typeof("manufacturing_transduction_efficiency") = 'object'),
  "manufacturing_car_positive_ratio" jsonb CHECK (jsonb_typeof("manufacturing_car_positive_ratio") = 'object'),
  "manufacturing_turbidity" jsonb CHECK (jsonb_typeof("manufacturing_turbidity") = 'object'),
  "manufacturing_ifn_gamma_release" jsonb CHECK (jsonb_typeof("manufacturing_ifn_gamma_release") = 'object'),
  "manufacturing_vcn" jsonb CHECK (jsonb_typeof("manufacturing_vcn") = 'object'),
  "manufacturing_cd3_positive_ratio" jsonb CHECK (jsonb_typeof("manufacturing_cd3_positive_ratio") = 'object'),
  "manufacturing_tscm_ratio" jsonb CHECK (jsonb_typeof("manufacturing_tscm_ratio") = 'object'),
  "manufacturing_tcm_ratio" jsonb CHECK (jsonb_typeof("manufacturing_tcm_ratio") = 'object'),
  "manufacturing_tem_ratio" jsonb CHECK (jsonb_typeof("manufacturing_tem_ratio") = 'object'),
  "manufacturing_teff_ratio" jsonb CHECK (jsonb_typeof("manufacturing_teff_ratio") = 'object'),
  "manufacturing_exhaustion_phenotype" text,
  "manufacturing_treg_phenotype" text,
  "manufacturing_sterility" boolean,
  "manufacturing_mycoplasma" boolean,
  "manufacturing_endotoxin" jsonb CHECK (jsonb_typeof("manufacturing_endotoxin") = 'object'),
  "manufacturing_killing_activity" jsonb CHECK (jsonb_typeof("manufacturing_killing_activity") = 'object'),
  "manufacturing_cytokine_release" jsonb CHECK (jsonb_typeof("manufacturing_cytokine_release") = 'array'),
  record_kind text GENERATED ALWAYS AS ('evidence'::text) STORED,
  FOREIGN KEY ("record_id", record_kind) REFERENCES cart.record(record_id, table_name),
  CHECK (num_nonnulls(binder_id, car_id, manufacturing_id) >= 1)
);
CREATE INDEX ON cart."evidence" ("source_type");
CREATE INDEX ON cart."evidence" ("source_id");
CREATE INDEX ON cart."evidence" ("combination_id");
CREATE INDEX ON cart."evidence" ("binder_id");
CREATE INDEX ON cart."evidence" ("car_id");
CREATE INDEX ON cart."evidence" ("manufacturing_id");

CREATE INDEX ON cart.car USING gin(modules jsonb_path_ops);
CREATE INDEX ON cart.binder USING gin(heavy_chain jsonb_path_ops);
CREATE INDEX ON cart.binder USING gin(light_chain jsonb_path_ops);

CREATE TABLE cart.import_batch (
  batch_id uuid PRIMARY KEY, checksum text NOT NULL UNIQUE,
  input_name text NOT NULL, input_text text NOT NULL,
  schema_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE cart.import_context (
  batch_id uuid NOT NULL REFERENCES cart.import_batch,
  name text NOT NULL, checksum text NOT NULL, content text NOT NULL,
  PRIMARY KEY(batch_id, name, checksum)
);
CREATE TABLE cart.staged_record (
  stage_id uuid PRIMARY KEY, batch_id uuid NOT NULL REFERENCES cart.import_batch,
  line_number integer NOT NULL CHECK (line_number > 0), table_name text,
  local_id text, original jsonb, normalized jsonb,
  audit jsonb NOT NULL DEFAULT '[]', errors jsonb NOT NULL DEFAULT '[]',
  status text NOT NULL CHECK (status IN ('invalid','pending','published')),
  target_id uuid, published_at timestamptz,
  UNIQUE(batch_id,line_number),
  FOREIGN KEY(target_id,table_name) REFERENCES cart.record(record_id,table_name),
  CHECK ((status = 'published') = (target_id IS NOT NULL))
);
CREATE INDEX ON cart.staged_record(batch_id,status);
CREATE INDEX ON cart.staged_record(target_id);
CREATE TABLE cart.identity_feature (
  stage_id uuid NOT NULL REFERENCES cart.staged_record,
  basis text NOT NULL, fingerprint text NOT NULL, value jsonb NOT NULL,
  PRIMARY KEY(stage_id,basis,fingerprint)
);
CREATE INDEX ON cart.identity_feature(basis,fingerprint);
CREATE TABLE cart.identity_decision (
  decision_id bigserial PRIMARY KEY, stage_id uuid NOT NULL REFERENCES cart.staged_record,
  action text NOT NULL CHECK (action IN ('new','link')),
  target_id uuid REFERENCES cart.record,
  target_stage_id uuid REFERENCES cart.staged_record,
  reviewer text NOT NULL CHECK (length(trim(reviewer)) > 0),
  reason text NOT NULL CHECK (length(trim(reason)) > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((action='new' AND num_nonnulls(target_id,target_stage_id)=0)
      OR (action='link' AND num_nonnulls(target_id,target_stage_id)=1)),
  CHECK (stage_id IS DISTINCT FROM target_stage_id)
);
CREATE INDEX ON cart.identity_decision(stage_id,decision_id DESC);
CREATE TABLE cart.publication_log (
  stage_id uuid PRIMARY KEY REFERENCES cart.staged_record,
  target_id uuid NOT NULL REFERENCES cart.record,
  method text NOT NULL, details jsonb NOT NULL,
  published_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE cart.entity_name (
  entity_id uuid NOT NULL REFERENCES cart.record,
  name text NOT NULL CHECK (length(trim(name)) > 0),
  stage_id uuid NOT NULL REFERENCES cart.staged_record,
  PRIMARY KEY(entity_id,name,stage_id)
);
CREATE INDEX ON cart.entity_name(name);
CREATE TABLE cart.name_selection (
  selection_id bigserial PRIMARY KEY, entity_id uuid NOT NULL REFERENCES cart.record,
  name text NOT NULL, selector text NOT NULL, reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Both directions are checked: evidence insertion and later combination changes.
CREATE FUNCTION cart.check_combination_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'evidence' THEN
    IF NEW.combination_id IS NOT NULL AND EXISTS (
      SELECT 1 FROM cart.abc_combination_db1 c WHERE c.combination_id=NEW.combination_id
      AND ((NEW.binder_id IS NOT NULL AND NEW.binder_id<>c.binder_id)
        OR (NEW.car_id IS NOT NULL AND NEW.car_id<>c.car_id)
        OR (NEW.manufacturing_id IS NOT NULL AND NEW.manufacturing_id<>c.manufacturing_id))
    ) THEN RAISE EXCEPTION 'Evidence entity references disagree with combination'; END IF;
  ELSE
    IF EXISTS (SELECT 1 FROM cart.evidence e WHERE e.combination_id=NEW.combination_id
      AND ((e.binder_id IS NOT NULL AND e.binder_id<>NEW.binder_id)
        OR (e.car_id IS NOT NULL AND e.car_id<>NEW.car_id)
        OR (e.manufacturing_id IS NOT NULL AND e.manufacturing_id<>NEW.manufacturing_id))
    ) THEN RAISE EXCEPTION 'Combination change disagrees with existing evidence'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER evidence_combination_consistency BEFORE INSERT OR UPDATE ON cart.evidence
FOR EACH ROW EXECUTE FUNCTION cart.check_combination_evidence();
CREATE TRIGGER combination_evidence_consistency BEFORE UPDATE ON cart.abc_combination_db1
FOR EACH ROW EXECUTE FUNCTION cart.check_combination_evidence();
