-- Schema_B.yaml：CAR backbone 核心实体与 1:N 证据。
-- Validate one legacy CAR module array; STRICT propagates SQL NULL and the column rejects NULL.
CREATE OR REPLACE FUNCTION car.valid_modules(value jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
  -- Require array-shaped JSON; malformed non-arrays may also raise during element expansion.
  SELECT jsonb_typeof(value) = 'array'
    -- Inspect all elements and pass only when no element violates the module contract.
    AND NOT EXISTS (
      SELECT 1
      FROM jsonb_array_elements(value) AS module(item)
      -- Each element must be an object with a reported string module_type from the controlled list.
      WHERE jsonb_typeof(item) <> 'object'
         OR NOT (item ? 'module_type')
         OR jsonb_typeof(item -> 'module_type') <> 'string'
         OR item ->> 'module_type' NOT IN (
              'linker', 'hinge', 'transmembrane_region',
              'costimulatory_domain', 'CD3zeta', 'tag', 'safety_switch'
            )
         -- An optional source molecule may be text or JSON null; absence is allowed.
         OR (item ? 'source_molecule'
             AND jsonb_typeof(item -> 'source_molecule') NOT IN ('string', 'null'))
         -- An optional amino-acid sequence may be text or JSON null; deeper sequence QC is separate.
         OR (item ? 'sequence'
             AND jsonb_typeof(item -> 'sequence') NOT IN ('string', 'null'))
         -- A supplied non-null length must be numeric and written as a nonnegative integer.
         OR (item ? 'length'
             AND jsonb_typeof(item -> 'length') <> 'null'
             AND (jsonb_typeof(item -> 'length') <> 'number'
                  OR item ->> 'length' !~ '^[0-9]+$'))
    )
$$;

CREATE TABLE IF NOT EXISTS car.car (
  car_id       uuid PRIMARY KEY,
  name         text,
  modules      jsonb NOT NULL CHECK (car.valid_modules(modules)),
  version      text NOT NULL DEFAULT '1.0',
  entry_date   date NOT NULL DEFAULT current_date
);

CREATE TABLE IF NOT EXISTS car.car_evidence (
  evidence_id                 uuid PRIMARY KEY,
  car_id                      uuid NOT NULL REFERENCES car.car (car_id),
  source_type                 text NOT NULL
    CHECK (source_type IN ('public_database', 'literature', 'patent', 'internal_data')),
  source_id                   text NOT NULL,
  citation                    text,
  evidence_level              text NOT NULL,
  experimental_conditions     jsonb,
  applicable_scenario         text,
  contrary_evidence           boolean NOT NULL DEFAULT false,
  activation_speed            text,
  metabolic_state             text CHECK (metabolic_state IN ('glycolytic', 'oxidative')),
  expansion_capacity          text,
  memory_phenotype            text,
  persistence                 text,
  exhaustion_risk             text,
  tonic_signaling_tendency    text,
  geometric_length            numeric CHECK (geometric_length >= 0),
  epitope_distance_effect     text,
  immune_synapse_effect       text,
  tonic_signaling_effect      text,
  compatible_modules          jsonb,
  incompatible_modules        jsonb,
  assembly_rules              jsonb
);

CREATE INDEX IF NOT EXISTS car_evidence_car_id_idx
  ON car.car_evidence (car_id);
CREATE INDEX IF NOT EXISTS car_evidence_source_type_idx
  ON car.car_evidence (source_type);
CREATE INDEX IF NOT EXISTS car_evidence_source_id_idx
  ON car.car_evidence (source_id);
