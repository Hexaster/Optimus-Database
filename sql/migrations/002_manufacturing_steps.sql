-- Add source-reported step status and harvest details; do not infer old values.
ALTER TABLE cart.manufacturing
  ADD COLUMN process_step_status jsonb CHECK (jsonb_typeof(process_step_status) = 'object'),
  ADD COLUMN harvest_steps jsonb CHECK (jsonb_typeof(harvest_steps) = 'array');
UPDATE cart.import_contract SET schema_hash =
  'fb64398a5ef997932fcf2a6b795040a050054f717bc0479de176cdc799656d9a'
WHERE singleton;
