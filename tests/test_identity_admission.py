"""Admission is independent of deduplication; conflicts never auto-merge."""
from copy import deepcopy
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from cart_db import ingest, ingest_schema
from cart_db.identity import compare
from cart_db.postprocess import normalize_record
from cart_db.schema_models import load_schema
from test_ingest import db, test_dsn, write, stage, count, binder, evidence
from test_pipeline import process, measurement


# Verify that names and source aliases link without sequences.
def test_names_and_source_aliases_link_without_sequences(db, tmp_path):
    bid, _ = stage(db, write(tmp_path, [binder(sequence=None, name='FMC63', aliases=['clone-FMC63']), evidence()]))
    assert ingest.publish(db, bid)['counts']['published'] == 2
    second = write(tmp_path, [binder(sequence=None, name='clone-FMC63'), evidence(source_id='paper-2')], 'second.jsonl')
    bid, _ = stage(db, second)
    report = ingest.publish(db, bid)
    assert report['counts']['published'] == 2
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert count(db, 'binder') == 1 and count(db, 'evidence') == 2


# Verify that generic binder name does not prove identity.
def test_generic_binder_name_does_not_prove_identity(db, tmp_path):
    # Process each i from range(2) independently.
    for i in range(2):
        bid, _ = stage(db, write(tmp_path, [binder(sequence=None, name='anti-CD19 scFv'), evidence(source_id=str(i))], f'{i}.jsonl'))
        assert ingest.publish(db, bid)['counts']['published'] == 2
    assert count(db, 'binder') == 2


# Verify that same binder name different sequence raises red flag and keeps evidence.
def test_same_binder_name_different_sequence_raises_red_flag_and_keeps_evidence(db, tmp_path):
    first, _ = stage(db, write(tmp_path, [binder(name='FMC63'), evidence()]))
    ingest.publish(db, first)
    second, _ = stage(db, write(tmp_path, [binder(sequence='DIVMT', name='FMC63'), evidence(source_id='other')], 'second.jsonl'))
    result = ingest.publish(db, second)
    assert result['counts'] == dict(published=2, pending=0, invalid=0)
    assert result['identity_counts']['conflict'] == 1
    assert count(db, 'binder') == count(db, 'evidence') == 2
    assert result['records'][0]['identity_details']['candidates'][0]['comparison']['conflicts'] == ['scfv_sequence']


# Build a synthetic CAR fixture for identity/reference checks.
def car(sequence=None):
    return dict(table='car', data=dict(car_id='c', modules=[
        dict(module_type='hinge', source_molecule='CD8', sequence=sequence),
        dict(module_type='costimulatory_domain', source_molecule='CD28'),
        dict(module_type='signaling_domain', source_molecule='CD3zeta')]))


# Build a synthetic observation referring to a CAR fixture.
def car_evidence(source_id):
    return dict(table='evidence', data={'record_id': 'e', 'source_type': 'literature', 'source_id': source_id, 'car.car_id': 'c'})


# Verify that module names order and conflict.
def test_module_names_order_and_conflict(db, tmp_path):
    first, _ = stage(db, write(tmp_path, [car('AEPK'), car_evidence('a')]))
    ingest.publish(db, first)
    second, _ = stage(db, write(tmp_path, [car(), car_evidence('b')], 'second.jsonl'))
    assert ingest.publish(db, second)['counts']['published'] == 2
    assert count(db, 'car') == 1
    third, _ = stage(db, write(tmp_path, [car('AVLT'), car_evidence('c')], 'third.jsonl'))
    report = ingest.publish(db, third)
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert report['identity_counts']['conflict'] == 1 and count(db, 'car') == 2
    assert count(db, 'evidence') == 3
    reordered = car()
    reordered['data']['modules'].reverse()
    assert compare('car', car()['data'], reordered['data'])['verdict'] != 'same'


# Verify that two named matches remain independent.
def test_two_named_matches_remain_independent(db, tmp_path):
    first, records = stage(db, write(tmp_path, [binder('a', name='Shared'), binder('b', 'DIVMT', name='Shared')]))
    ingest.publish(db, first)
    second, _ = stage(db, write(tmp_path, [binder(sequence=None, name='Shared'), evidence()], 'second.jsonl'))
    report = ingest.publish(db, second)
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert report['identity_counts']['unresolved'] == 1 and count(db, 'binder') == 3
    assert report['counts']['published'] == 2


# Verify that process similarity is not merge.
def test_process_similarity_is_not_merge(db, tmp_path):
    a, b = process(), process('相似工艺')
    b['activation_method'] = 'CD3/CD28游离抗体'
    bid, _ = stage(db, write(tmp_path, [dict(table='manufacturing', data=a)]))
    ingest.publish(db, bid)
    bid, _ = stage(db, write(tmp_path, [dict(table='manufacturing', data=b)], 'second.jsonl'))
    report = ingest.publish(db, bid)
    assert report['identity_counts']['similar'] == 1
    assert count(db, 'manufacturing') == 2


# Verify that duration units and unknown selection.
def test_duration_units_and_unknown_selection():
    a, b = process(), process()
    a['culture_duration'] = dict(kind='single_value', value=1, unit='weeks', raw='one week')
    b['culture_duration'] = dict(kind='single_value', value=7, unit='day', raw='seven days')
    na, _ = normalize_record('manufacturing', a)
    nb, _ = normalize_record('manufacturing', b)
    assert na['culture_duration']['value'] == 7
    assert compare('manufacturing', na, nb)['verdict'] == 'similar'
    b['selection_steps'] = None
    a['selection_steps'] = [dict(input='PBMC', output='PBMC', method='不进行T细胞分选')]
    assert compare('manufacturing', a, b)['verdict'] != 'same'


# Verify that retired fields are absent but source values audited.
def test_retired_fields_are_absent_but_source_values_audited(db, tmp_path):
    data = process()
    data.update(harvest_steps=[dict(method='old harvest', conditions='old conditions')], process_step_status={'harvest':'reported'})
    normalized, audit = normalize_record('manufacturing', data)
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert 'harvest_steps' not in normalized and 'process_step_status' not in normalized
    # Collect items from audit only where a['reason'] == 'retired_field_preserved_in_source'.
    assert len([a for a in audit if a['reason'] == 'retired_field_preserved_in_source']) == 2
    bid, _ = stage(db, write(tmp_path, [dict(table='manufacturing', data=data)]))
    ingest.publish(db, bid)
    saved = db.execute('SELECT original FROM cart.staged_record WHERE batch_id=%s', (bid,)).fetchone()[0]
    assert saved['data']['harvest_steps'] == data['harvest_steps']
    assert 'process_step_status' not in load_schema().tables['manufacturing']


# Verify that migration archives previously accepted fields.
def test_migration_archives_previously_accepted_fields(db, tmp_path, monkeypatch):
    db.execute('DROP SCHEMA cart CASCADE')
    originals = ingest_schema.MIGRATIONS
    # Process each name from ('001_scientific_ingestion.sql', '002_manufacturing_steps.sql')
    # independently.
    for name in ('001_scientific_ingestion.sql', '002_manufacturing_steps.sql'):
        (tmp_path / name).write_bytes((originals / name).read_bytes())
    # Release this managed resource when the enclosed operation completes or fails.
    with monkeypatch.context() as m:
        m.setattr(ingest_schema, 'MIGRATIONS', tmp_path)
        # The callback returns 'fb64398a5ef997932fcf2a6b795040a050054f717bc0479de176cdc799656d9a'.
        m.setattr(ingest_schema, 'contract_hash', lambda: 'fb64398a5ef997932fcf2a6b795040a050054f717bc0479de176cdc799656d9a')
        ingest_schema.migrate(db)
    identifier = uuid4()
    db.execute("INSERT INTO cart.record(record_id,table_name) VALUES (%s,'manufacturing')", (identifier,))
    db.execute('''INSERT INTO cart.manufacturing(manufacturing_id,harvest_steps,process_step_status)
                VALUES (%s,'[{"method":"old"}]','{"harvest":"reported"}')''', (identifier,))
    ingest_schema.migrate(db)
    assert db.execute('SELECT harvest_steps FROM cart.retired_manufacturing_fields WHERE manufacturing_id=%s', (identifier,)).fetchone()[0] == [{'method':'old'}]
    assert db.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='cart' AND table_name='manufacturing' AND column_name IN ('harvest_steps','process_step_status')").fetchone()[0] == 0


# Verify that crispr aav method is supported.
def test_crispr_aav_method_is_supported(db, tmp_path):
    data = process()
    data['vector_type'] = 'CRISPR/Cas9+AAV定点插入'
    bid, _ = stage(db, write(tmp_path, [dict(table='manufacturing', data=data)]))
    assert ingest.publish(db, bid)['counts'] == dict(published=1, pending=0, invalid=0)


# Verify that pending old batch revalidated without changing source ids.
def test_pending_old_batch_revalidated_without_changing_source_ids(db, tmp_path):
    from psycopg.types.json import Jsonb
    data = process()
    data['culture_duration'] = dict(kind='single_value', value=1, unit='weeks', raw='one week')
    data['harvest_steps'] = [{'method':'historical', 'conditions':None}]
    path = write(tmp_path, [dict(table='manufacturing', data=data)])
    bid, records = stage(db, path)
    old = deepcopy(data)
    db.execute('UPDATE cart.staged_record SET normalized=%s,audit=%s WHERE batch_id=%s',
               (Jsonb(old), Jsonb([dict(reason='review_missing_or_unconvertible_unit')]), bid))
    db.execute("UPDATE cart.import_batch SET schema_hash='old-schema' WHERE batch_id=%s", (bid,))
    assert ingest.stage_file(db, path) == bid
    updated = ingest.get_stage(db, records[0]['stage_id'])
    assert updated['normalized']['culture_duration']['unit'] == 'day'
    assert updated['normalized']['culture_duration']['value'] == 7
    assert 'harvest_steps' not in updated['normalized']
    assert updated['audit'][0]['before']['normalized']['harvest_steps'] == old['harvest_steps']
    assert ingest.publish(db, bid)['counts']['published'] == 1
    assert ingest.stage_file(db, path) == bid
    assert count(db, 'manufacturing') == 1


# Verify that incomplete entity without candidates completes matching.
@pytest.mark.parametrize('record', [
    binder(sequence=None, name='FMC63'),
    car(),
    dict(table='manufacturing', data={'manufacturing_id':'m', 'name':'未完整报告的工艺'}),
])
def test_incomplete_entity_without_candidates_completes_matching(db, tmp_path, record):
    bid, _ = stage(db, write(tmp_path, [record]))
    report = ingest.publish(db, bid)
    assert report['counts'] == dict(published=1, pending=0, invalid=0)
    assert report['identity_counts']['resolved'] == 1
    assert report['identity_counts']['unresolved'] == 0
    assert ingest.publish(db, bid)['identity_counts'] == report['identity_counts']


# Verify that migration corrects only empty candidate warnings.
def test_migration_corrects_only_empty_candidate_warnings(db, tmp_path):
    from psycopg.types.json import Jsonb
    bid, records = stage(db, write(tmp_path, [binder(sequence=None, name='FMC63')]))
    ingest.publish(db, bid)
    previous = dict(identity_status='unresolved', candidates=[], normalization_flags=[])
    migration = (ingest_schema.MIGRATIONS / '004_resolve_unmatched_entities.sql').read_text()
    # Process each declared item independently, preserving the order established by this collection.
    for details in (dict(previous, candidates=[{'comparison': {'verdict':'possible'}}]),
                    dict(previous, normalization_flags=[{'reason':'review_sequence'}])):
        db.execute("UPDATE cart.staged_record SET identity_status='unresolved', identity_details=%s WHERE batch_id=%s", (Jsonb(details), bid))
        db.execute(migration)
        assert ingest.batch_status(db, bid)['identity_counts']['unresolved'] == 1
    db.execute("UPDATE cart.staged_record SET identity_status='unresolved', identity_details=%s WHERE batch_id=%s", (Jsonb(previous), bid))
    db.execute(migration)
    result = ingest.batch_status(db, bid)
    assert result['identity_counts']['resolved'] == 1
    assert result['records'][0]['identity_details']['previous_identity_details'] == previous
    assert count(db, 'binder') == 1


# Verify that console uses plain matching labels.
def test_console_uses_plain_matching_labels():
    from cart_db.console import report_text
    text = report_text(dict(batch_id='demo', counts=dict(published=1, pending=0, invalid=0),
                            identity_counts=dict(unresolved=0, similar=0, conflict=1), records=[]))
    assert '匹配结果待确认 0 条' in text
    assert '匹配信息冲突 1 条' in text
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert '红旗' not in text and '待去重' not in text
