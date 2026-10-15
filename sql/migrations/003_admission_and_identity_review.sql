-- Remove the rejected extraction-schema additions, preserving any stored values.
CREATE TABLE cart.retired_manufacturing_fields (
    manufacturing_id uuid PRIMARY KEY,
    process_step_status jsonb,
    harvest_steps jsonb,
    archived_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO cart.retired_manufacturing_fields(manufacturing_id,process_step_status,harvest_steps)
SELECT manufacturing_id,process_step_status,harvest_steps FROM cart.manufacturing
WHERE process_step_status IS NOT NULL OR harvest_steps IS NOT NULL;
ALTER TABLE cart.manufacturing DROP COLUMN process_step_status, DROP COLUMN harvest_steps;
ALTER TABLE cart.manufacturing DROP CONSTRAINT manufacturing_vector_type_check;
ALTER TABLE cart.manufacturing ADD CONSTRAINT manufacturing_vector_type_check
CHECK (vector_type IN ('慢病毒','逆转录病毒','转座子','电转','CRISPR/Cas9+AAV定点插入'));

ALTER TABLE cart.staged_record
ADD COLUMN identity_status text CHECK (identity_status IN ('resolved','unresolved','similar','conflict')),
ADD COLUMN identity_details jsonb;
UPDATE cart.staged_record SET identity_status='resolved'
WHERE status='published' AND table_name IN ('binder','car','manufacturing');
CREATE INDEX ON cart.staged_record(identity_status) WHERE identity_status<>'resolved';
UPDATE cart.import_contract SET schema_hash =
'205f6f856cde5e6e9396843e29f3359add4fa8882fa4e96d710229ad67deb25f' WHERE singleton;
