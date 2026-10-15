-- Correct the old completeness-only warning without changing identities or links.
-- Keep the previous decision details for audit; do not reinterpret ambiguous matches.
UPDATE cart.staged_record
SET identity_status = 'resolved',
    identity_details = identity_details || jsonb_build_object(
        'identity_status', 'resolved',
        'reason', '本次匹配未发现疑似重复，已新增实体；缺失字段不单独触发待确认。',
        'previous_identity_details', identity_details)
WHERE status = 'published' AND identity_status = 'unresolved'
  AND table_name IN ('binder', 'car', 'manufacturing')
  AND identity_details->'candidates' = '[]'::jsonb
  AND identity_details->'normalization_flags' = '[]'::jsonb;
