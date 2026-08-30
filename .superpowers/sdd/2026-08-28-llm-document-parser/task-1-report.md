# Task 1 report: build extraction models from `docs/Schema/*.yaml`

## What was implemented

Followed the brief (`task-1-brief.md`) step by step, transcribing its code verbatim.

1. **Step 1 — dependencies**
   - Appended to `requirements.txt`:
     ```
     pymupdf>=1.24        # extraction.load_document 从 PDF 取文字
     pytest>=8.0          # tests/
     ```
   - Installed both into the `fosun` conda env:
     `/home/zzz010122/anaconda3/envs/fosun/bin/pip install pymupdf pytest`
     → `pymupdf-1.28.2`, `pytest-9.1.1` (plus `pluggy-1.6.0`, `iniconfig-2.3.0`) installed successfully.
   - Created `pytest.ini` at repo root:
     ```ini
     [pytest]
     pythonpath = src
     testpaths = tests
     ```

2. **Step 2 — failing test**
   - Created `tests/test_schema_models.py` (13 tests), transcribed verbatim from the brief. `tests/` did not exist before this task; it was created fresh.

3. **Step 3 — confirmed the test fails first**
   - Ran the test suite before any implementation existed; it failed exactly as the brief predicted (see "Test command and output" below, first run).

4. **Step 4 — implementation**
   - Created `src/cart_db/schema_models.py`, transcribed verbatim from the brief. It exposes:
     - `KV` — key/value model used for untyped `json` fields.
     - `EntitySpec(kind, id_column, fk_column, model, evidence_model)`
     - `ExtractionSchema(extraction, entities, shared_evidence_fields, evidence_table, combination_table)`
     - `load_schema(schema_dir: Path | None = None) -> ExtractionSchema`, `@lru_cache(maxsize=4)`-decorated, callable both as `load_schema()` (default `docs/Schema/`) and `load_schema(tmp_path)` (positional, for tests that build a modified copy of the schema dir).
   - The three structural conventions Python still hardcodes (per `global-constraints.md`, this is intentional — everything else comes from YAML): `ENTITY_TABLES = ("binder", "car", "manufacturing")`, `EVIDENCE_TABLE = "evidence"`, `COMBINATION_TABLE = "abc_combination_db1"`.
   - Did not touch `src/cart_db/llm.py`.

5. **Step 5 — confirmed the test suite passes**
   - All 13 tests passed on the first run after implementation — no transcription fixes were needed (see full output below).

6. **Step 6 — commit**
   - Staged exactly the four files named in the brief and committed with the exact message given:
     ```
     git add requirements.txt pytest.ini src/cart_db/schema_models.py tests/test_schema_models.py
     git commit -m "feat: build extraction models from docs/Schema YAML at runtime"
     ```
   - Commit: `aeaf7ddd1d02e1e21cd961e92a15f1b75c9fc845` on branch `feat/llm-document-parser`.
   - `git status` was checked before commit to confirm nothing else got swept in — only those four files were staged (`A pytest.ini`, `M requirements.txt`, `A src/cart_db/schema_models.py`, `A tests/test_schema_models.py`); all other pre-existing modified/untracked files in the working tree (docs/Schema *.dbml/*.yaml, sql/*.sql, etc. — unrelated to this task) were left untouched.

## Exact test command and full output

### Before implementation (Step 3 — confirming failure)

```
/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/test_schema_models.py -v
```

```
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0 -- /home/zzz010122/anaconda3/envs/fosun/bin/python
cachedir: .pytest_cache
rootdir: /home/zzz010122/Fosun-db
configfile: pytest.ini
plugins: anyio-4.14.2
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_schema_models.py _________________
ImportError while importing test module '/home/zzz010122/Fosun-db/tests/test_schema_models.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
../anaconda3/envs/fosun/lib/python3.11/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_schema_models.py:10: in <module>
    from cart_db.schema_models import KV, load_schema
E   ModuleNotFoundError: No module named 'cart_db.schema_models'
=========================== short test summary info ============================
ERROR tests/test_schema_models.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.34s ===============================
```

This matches the brief's expected failure exactly (`ModuleNotFoundError: No module named 'cart_db.schema_models'`).

### After implementation (Step 5 — confirming pass)

```
/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/test_schema_models.py -v
```

```
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0 -- /home/zzz010122/anaconda3/envs/fosun/bin/python
cachedir: .pytest_cache
rootdir: /home/zzz010122/Fosun-db
configfile: pytest.ini
plugins: anyio-4.14.2
collecting ... collected 13 items

tests/test_schema_models.py::test_shared_evidence_fields_come_from_yaml PASSED [  7%]
tests/test_schema_models.py::test_each_prefix_becomes_its_own_evidence_model PASSED [ 15%]
tests/test_schema_models.py::test_same_field_name_under_two_prefixes_does_not_collide PASSED [ 23%]
tests/test_schema_models.py::test_entity_models_match_yaml PASSED        [ 30%]
tests/test_schema_models.py::test_primary_and_foreign_keys_are_never_asked_of_the_model PASSED [ 38%]
tests/test_schema_models.py::test_allowed_values_become_a_closed_choice PASSED [ 46%]
tests/test_schema_models.py::test_json_fields_become_key_value_lists PASSED [ 53%]
tests/test_schema_models.py::test_item_schema_becomes_a_nested_model PASSED [ 61%]
tests/test_schema_models.py::test_combination_foreign_keys_become_indices PASSED [ 69%]
tests/test_schema_models.py::test_root_model_has_four_lists PASSED       [ 76%]
tests/test_schema_models.py::test_strict_schema_is_not_empty PASSED      [ 84%]
tests/test_schema_models.py::test_new_yaml_field_appears_without_touching_python PASSED [ 92%]
tests/test_schema_models.py::test_prefix_group_overlapping_a_shared_field_is_rejected PASSED [100%]

============================== 13 passed in 0.53s ==============================
```

13 passed, as the brief predicted.

## Decisions / judgment calls

- No design decisions were needed — the brief's code was transcribed as-is, and it worked against the real `docs/Schema/*.yaml` files on the first try (I read `Evidence.yaml`, `Schema_A.yaml`, `Schema_B.yaml`, `Schema_C.yaml`, `Schema_DB1.yaml` beforehand to sanity-check the brief's assumptions — e.g. that `Schema_DB1.yaml`'s table key is `abc_combination_db1`, matching `COMBINATION_TABLE`; that `car.modules` in `Schema_B.yaml` has an `item_schema`; that `car.memory_phenotype` / `manufacturing.memory_phenotype` genuinely collide by bare name in `Evidence.yaml`). Everything matched.
- Used the `Write`/`Edit`/`Read` tools rather than bash heredocs for creating/editing the Python and test files, to avoid any shell-escaping risk when transcribing multi-line source containing Chinese comments/docstrings and special characters (`|`, `[`, quotes) — precision mattered more here than tool-preference conventions, given the explicit warning that any test failure would likely be a transcription slip.
- `tests/` did not exist before this task; created it fresh (implied by the brief, not stated as a separate step).

## Concerns

None. All 13 tests passed without needing any fixes. `git status` confirms only the four intended files were committed; the branch's large set of pre-existing unrelated modifications/deletions (docs/Schema `.dbml` files, `sql/*.sql`, `parsers/thera_sabdab.py`, etc.) were left untouched, as instructed — they belong to other tasks/work already in progress on this branch and are out of scope for Task 1.

---

## Fix round 1

### Finding (Important)

`load_schema()` and `load_schema(None)` did not share an `lru_cache` entry, because `functools.lru_cache` keys on the literal argument passed to the wrapper, not on the resolved default. `load_schema()` and `load_schema(None)` therefore built two structurally identical but non-identical sets of model classes, breaking `is`/`isinstance` comparisons downstream (e.g. a Task 4 test asserting `captured["schema"] is SCHEMA.extraction`).

### Fix

Split `load_schema` into a thin, uncached public wrapper and a cached private function, so the argument is normalised to a single canonical value *before* it reaches the cache key:

```python
def load_schema(schema_dir: Path | None = None) -> ExtractionSchema:
    """读 docs/Schema/*.yaml，构建整套答题格式。

    薄封装：把参数归一化成同一个值后再进缓存，让 load_schema()、
    load_schema(None)、load_schema(SCHEMA_DIR) 命中同一条缓存、
    返回同一个对象 —— lru_cache 按字面参数取键，不按解析后的默认值取键，
    否则这几种写法会各自建一套结构相同但不是同一个类的模型，
    下游用 `is`/`isinstance` 比较模型类时会静默出错。
    """
    return _load_schema_cached(schema_dir or SCHEMA_DIR)


@lru_cache(maxsize=4)
def _load_schema_cached(schema_dir: Path) -> ExtractionSchema:
    tables = _load_tables(schema_dir)
    ...
```

`load_schema`'s public name and signature (`schema_dir: Path | None = None`) are unchanged, so no caller needs to change. `_load_schema_cached` always receives a resolved `Path` (`schema_dir or SCHEMA_DIR`), so `load_schema()`, `load_schema(None)`, and `load_schema(SCHEMA_DIR)` all now delegate to the same cache key and return the identical `ExtractionSchema` object.

Manual verification:

```
load_schema() is load_schema():          True
load_schema() is load_schema(None):      True
load_schema() is load_schema(SCHEMA_DIR): True
_load_schema_cached.cache_info() -> CacheInfo(hits=5, misses=1, maxsize=4, currsize=1)
```

`currsize=1` confirms a single cache entry now serves all three call spellings.

### Test added

Appended to `tests/test_schema_models.py`, exactly as specified by the coordinator:

```python
def test_load_schema_default_and_explicit_none_are_the_same_object():
    from cart_db.schema_models import SCHEMA_DIR, load_schema
    assert load_schema() is load_schema(None)
    assert load_schema() is load_schema(SCHEMA_DIR)
```

### Covering tests re-run

```
/home/zzz010122/anaconda3/envs/fosun/bin/python -m pytest tests/ -v
```

```
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0 -- /home/zzz010122/anaconda3/envs/fosun/bin/python
cachedir: .pytest_cache
rootdir: /home/zzz010122/Fosun-db
configfile: pytest.ini
plugins: anyio-4.14.2
collecting ... collected 39 items

tests/test_extraction.py::test_strip_removes_back_matter PASSED          [  2%]
tests/test_extraction.py::test_strip_keeps_body_intact PASSED            [  5%]
tests/test_extraction.py::test_strip_removes_standalone_ref_list PASSED  [  7%]
tests/test_extraction.py::test_load_xml_file PASSED                      [ 10%]
tests/test_extraction.py::test_load_nxml_extension PASSED                [ 12%]
tests/test_extraction.py::test_load_markdown_verbatim PASSED             [ 15%]
tests/test_extraction.py::test_load_markdown_alias_extension PASSED      [ 17%]
tests/test_extraction.py::test_unknown_extension_raises PASSED           [ 20%]
tests/test_extraction.py::test_evidence_points_at_its_own_binder PASSED  [ 23%]
tests/test_extraction.py::test_evidence_carries_all_three_fk_columns PASSED [ 25%]
tests/test_extraction.py::test_shared_fields_are_not_prefixed PASSED     [ 28%]
tests/test_extraction.py::test_car_and_manufacturing_memory_phenotype_stay_apart PASSED [ 30%]
tests/test_extraction.py::test_kv_lists_become_dicts PASSED              [ 33%]
tests/test_extraction.py::test_modules_stay_a_list PASSED                [ 35%]
tests/test_extraction.py::test_entities_come_before_evidence PASSED      [ 38%]
tests/test_extraction.py::test_combination_resolves_indices_and_emits_one_evidence_row PASSED [ 41%]
tests/test_extraction.py::test_out_of_range_combination_is_dropped PASSED [ 43%]
tests/test_extraction.py::test_negative_index_is_dropped PASSED          [ 46%]
tests/test_extraction.py::test_evidence_without_source_id_is_dropped PASSED [ 48%]
tests/test_extraction.py::test_evidence_with_blank_evidence_level_is_dropped PASSED [ 51%]
tests/test_extraction.py::test_system_prompt_contains_rules_schema_and_output_guide PASSED [ 53%]
tests/test_extraction.py::test_system_prompt_is_stable_across_calls PASSED [ 56%]
tests/test_extraction.py::test_extract_document_writes_jsonl PASSED      [ 58%]
tests/test_extraction.py::test_extract_document_writes_readable_utf8 PASSED [ 61%]
tests/test_extraction.py::test_dry_run_estimates_without_calling_extract PASSED [ 64%]
tests/test_schema_models.py::test_shared_evidence_fields_come_from_yaml PASSED [ 66%]
tests/test_schema_models.py::test_each_prefix_becomes_its_own_evidence_model PASSED [ 69%]
tests/test_schema_models.py::test_same_field_name_under_two_prefixes_does_not_collide PASSED [ 71%]
tests/test_schema_models.py::test_entity_models_match_yaml PASSED        [ 74%]
tests/test_schema_models.py::test_primary_and_foreign_keys_are_never_asked_of_the_model PASSED [ 76%]
tests/test_schema_models.py::test_allowed_values_become_a_closed_choice PASSED [ 79%]
tests/test_schema_models.py::test_json_fields_become_key_value_lists PASSED [ 82%]
tests/test_schema_models.py::test_item_schema_becomes_a_nested_model PASSED [ 84%]
tests/test_schema_models.py::test_combination_foreign_keys_become_indices PASSED [ 87%]
tests/test_schema_models.py::test_root_model_has_four_lists PASSED       [ 89%]
tests/test_schema_models.py::test_strict_schema_is_not_empty PASSED      [ 92%]
tests/test_schema_models.py::test_new_yaml_field_appears_without_touching_python PASSED [ 94%]
tests/test_schema_models.py::test_prefix_group_overlapping_a_shared_field_is_rejected PASSED [ 97%]
tests/test_schema_models.py::test_load_schema_default_and_explicit_none_are_the_same_object PASSED [100%]

============================== 39 passed in 0.62s ==============================
```

All 39 tests pass (38 pre-existing across `test_extraction.py` and `test_schema_models.py`, plus the 1 new identity-pinning test).

### Concerns

None. `_load_schema_cached` is prefixed with `_` (module-private), so it doesn't expand the public surface; `load_schema`'s name and signature are byte-for-byte unchanged, so no other task's code or tests needed to change.

### Commit

```
git add src/cart_db/schema_models.py tests/test_schema_models.py
git commit -m "fix: normalise load_schema's arg before the cache so all call spellings share one object"
```
