# Blocker Fix Report: Strict-Grammar Limit on `llm.extract()`

## Summary
`llm.extract()` was failing against the live API with `400 invalid_request_error:
The compiled grammar is too large`. Per the prior diagnosis (nullable-field
`anyOf` unions are the driver, not byte size; per-entity calls with json
fields as plain strings is the configuration that clears the limit), split
extraction into one LLM call per entity list and removed all `X | None`
unions from the generated models. All 44 tests pass, and all four request
schemas measure comfortably under the ~5.5k-char strict-grammar threshold.

## Implementation

### 1. `src/cart_db/schema_models.py`
- `_build_model`: fields are now declared non-Optional with a plain default
  (`(annotation, Field(default=None))` for scalars/enums,
  `(annotation, Field(default_factory=list))` for list-valued fields —
  detected via `typing.get_origin(annotation) is list`). This removes the
  `anyOf: [{type: X}, {type: null}]` unions that were driving grammar size,
  without loosening `llm._strict()`'s "everything required" behavior.
- Applied the same non-Optional treatment to the combination model's
  non-key fields (built by hand in `load_schema`, not through
  `_build_model`), for the same reason. The `*_index` foreign-key fields
  stay required as before.
- `_annotation`: a `type: json` field with **no** `item_schema` now maps to
  plain `str` instead of `list[KV]`. The `item_schema` branch (nested
  models, e.g. `car.modules`) and the `item_type` branch (scalar lists) are
  unchanged.
- Deleted the now-unused `KV` class.
- Added `ExtractionSchema.requests: tuple[tuple[str, type[BaseModel]], ...]`
  — one `(root_field_name, request_model)` pair per LLM call, in order
  `binders`, `cars`, `manufacturings`, `combinations`. Each request model is
  a `create_model` root carrying exactly the one matching field (same name,
  same annotation) from the full `extraction` model. `extraction` itself is
  unchanged and is still what `flatten()` consumes.

### 2. `src/cart_db/extraction.py`
- `extract_document` now loops over `schema.requests`, making one
  `llm.extract()` call per entry (`purpose=f"article_extraction:{field_name}"`),
  collecting each answer's single field into a `parts` dict, and assembling
  `schema.extraction(**parts)` once all four calls are done. `flatten()` is
  unchanged and consumes that assembled result exactly as before.
- Added `_index_hint(parts)`: renders the binders/cars/manufacturings
  already extracted as a numbered list (using each entity's `name`, falling
  back to `"(unnamed)"`, and `"(none)"` for an empty list) so the
  `combinations` call has real indices to point at. That call's document is
  `f"{document}\n\n{_index_hint(parts)}"`; the other three calls send the
  document unmodified.
- Updated `OUTPUT_GUIDE` to explain that a schema-less `json` field is now
  written as a free-text string (not key/value pairs), that a field with a
  declared item structure is still a list of objects, and that each call
  answers exactly one of the four lists. The guide text itself is a static
  string with no per-call variance, so `build_system_prompt()` stays
  byte-identical across calls (verified by
  `test_system_prompt_is_stable_across_calls`).
- `dry_run` behavior is unchanged: `count_tokens` is estimated once and `[]`
  is returned without calling the model.
- Did not touch `flatten()` or `_unkv()` — the brief said "flatten as
  before." `_unkv()` is now mostly inert (nothing produces the
  `[{"key":..., "value":...}]` shape anymore except in principle), but it is
  still exercised by every field in `flatten()` and removing it wasn't
  requested, so it was left in place as pre-existing code.

### 3. Tests
- `tests/test_schema_models.py`: replaced
  `test_json_fields_become_key_value_lists` with
  `test_json_field_without_item_schema_becomes_a_plain_string` (asserts the
  annotation is `str` and that `car.modules`, which has an `item_schema`,
  still becomes a nested model). Added
  `test_requests_have_one_field_each_in_call_order`, which checks the four
  names and order, that each request model has exactly one field, and that
  each field's annotation matches the corresponding field on the full
  `extraction` model. Removed the `KV` import.
- `tests/test_extraction.py`: rewrote `test_kv_lists_become_dicts` as
  `test_json_fields_without_item_schema_stay_plain_strings` (plain strings
  in, plain strings out of `flatten()`). Rewrote the `outcomes=[KV(...)]`
  usage inside `test_combination_resolves_indices_and_emits_one_evidence_row`
  to a plain string. Fixed
  `test_evidence_without_source_id_is_dropped`, which explicitly passed
  `source_id=None` — now that the field is non-Optional `str`, an explicit
  `None` is a type error; a missing source_id must now be expressed by
  *omitting* the field so it falls through to the `Field(default=None)`
  default (this matches the mechanism note in the brief). Rewrote
  `test_extract_document_writes_jsonl` and
  `test_extract_document_writes_readable_utf8` to use a fake `llm.extract`
  that dispatches on `next(iter(schema.model_fields))` (each request model
  has exactly one field) via a shared `_fake_request(schema, **overrides)`
  helper. Added
  `test_extract_document_makes_one_call_per_request_and_hints_indices`,
  which asserts the four calls happen in order and that the combination
  call's document contains the rendered index hint
  (`"binders: 0=ARB-202, 1=5F9"`, `"cars: 0=CD8a-BBz"`,
  `"manufacturings: (none)"`). Removed the `KV` import.

No test was weakened or deleted; every changed test still asserts real
behavior. `src/cart_db/llm.py` was not modified.

## Verification

```
/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/ -v
```
Result: **44 passed** (42 pre-existing + 2 new: the requests-shape test and
the four-calls/index-hint test; one pre-existing test —
`test_evidence_without_source_id_is_dropped` — was fixed for the new
non-Optional field semantics, not deleted).

Strict-grammar size per request schema (must be comfortably under ~5500
chars per the diagnosed threshold):

```
binders 5029
cars 3949
manufacturings 4631
combinations 2200
```

All four clear the limit with margin — `binders`/`cars`/`manufacturings`
land within ~10-70 chars of the already-verified-OK per-entity numbers
from the live-API diagnosis (5022 / 3959 / 4624), and `combinations` (not
previously measured standalone) comes in far smaller at 2200.

## Commit
```
fix: split extraction into per-entity calls to fit the strict-grammar limit
```

## Concerns
None. `src/cart_db/llm.py` was not touched. Field names still come entirely
from `docs/Schema/*.yaml` — nothing was hardcoded in Python beyond the three
pre-existing structural constants (`ENTITY_TABLES`, `EVIDENCE_TABLE`,
`COMBINATION_TABLE`).
