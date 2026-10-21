import json
from copy import deepcopy

import pytest

from cart_db.agent_output import OutputError
from cart_db.measurements import convert
from cart_db.postprocess import canonical_sequence, normalize_record, process_batch


# Write synthetic table/data rows to a temporary JSONL fixture.
def write_rows(path, rows):
    # Build mapped values from rows.
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    return path


# Build a minimal synthetic binder fixture with optional field overrides.
def binder(row_id='b1', **kw):
    return dict(table='binder', data=dict(binder_id=row_id, **kw))


# Verify that sequences no ocr repair or annotation stripping.
def test_sequences_no_ocr_repair_or_annotation_stripping():
    assert canonical_sequence(' evq\nL\tV ') == 'EVQLV'
    # Process each value from ('EVQ1V', '>VH\nEVQLV', 'EVQ-V', 'SEQ ID NO: 1 EVQLV', '')
    # independently.
    for value in ('EVQ1V', '>VH\nEVQLV', 'EVQ-V', 'SEQ ID NO: 1 EVQLV', ''):
        assert canonical_sequence(value) is None
    row = binder(scfv_sequence=' evq\nLV ', linker='(G4S)3')
    before = deepcopy(row)
    data, events = normalize_record(row['table'], row['data'])
    assert data['scfv_sequence'] == 'EVQLV'
    assert data['linker'] == '(G4S)3'
    assert row == before
    assert events[0]['before'] == ' evq\nLV '


# Verify that nested aliases and conflicts.
def test_nested_aliases_and_conflicts():
    rules = {'field_aliases': {'binder': {'VH': 'heavy_chain'}},
             'value_aliases': {'binder.heavy_chain.scope': {'VH': 'variable_region'}}}
    data, _ = normalize_record('binder', {'binder_id': 'b', 'VH':
                              {'sequence': 'evqlv', 'scope': 'VH'}}, rules)
    assert data['heavy_chain'] == {'sequence': 'EVQLV', 'scope': 'variable_region'}
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(OutputError, match='conflicting fields'):
        normalize_record('binder', {'binder_id': 'b', 'VH': {}, 'heavy_chain': None}, rules)
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(OutputError, match='unknown fields'):
        normalize_record('binder', {'binder_id': 'b', 'made_up': 2})


# Verify that measurement bounds error and raw.
def test_measurement_bounds_error_and_raw():
    m = dict(kind='mean_with_standard_deviation', value=2, error=.3, unit='µM', raw='2 ± 0.3 µM')
    data, _ = normalize_record('evidence', {'record_id': 'e', 'source_type': 'literature',
                                          'source_id': 'PMC1', 'binder.kd': m})
    assert data['binder.kd']['value'] == pytest.approx(2000)
    assert data['binder.kd']['error'] == pytest.approx(300)
    assert data['binder.kd']['raw'] == m['raw']
    assert convert({'lower': 1, 'upper': 2, 'unit': 'day'}, 'h')['upper'] == 48
    temperature = convert({'value': 32, 'error': 9, 'unit': '°F'}, '°C')
    assert temperature['value'] == pytest.approx(0)
    assert temperature['error'] == pytest.approx(5)
    assert convert({'value': 100, 'unit': 'ng/mL'}, 'nM')['unit'] == 'ng/mL'
    assert convert({'value': 2, 'unit': 'mL'}, 'uL')['value'] == pytest.approx(2000)
    assert convert({'value': 2, 'unit': 'cells/uL'}, 'cells/mL')['value'] == pytest.approx(2000)


# Verify that scope ids references and retain independent evidence.
def test_scope_ids_references_and_retain_independent_evidence(tmp_path):
    records = [binder(name='clone', scfv_sequence='EVQLV'),
               dict(table='evidence', data={'record_id': 'e1', 'source_type': 'patent',
                    'source_id': 'WO1', 'binder.binder_id': 'b1'})]
    a = write_rows(tmp_path / 'a.jsonl', records + [records[0]])
    b = write_rows(tmp_path / 'b.jsonl', records)
    rows, audit, provenance, candidates = process_batch([a, b])
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert len(rows) == 4 and len(provenance) == 5
    assert rows[0].data['binder_id'] != rows[2].data['binder_id']
    assert rows[1].data['binder.binder_id'] == rows[0].data['binder_id']
    assert rows[3].data['binder.binder_id'] == rows[2].data['binder_id']
    # Build mapped values from audit.
    assert sum(e['reason'] == 'duplicate_serialization' for e in audit) == 1
    # Build mapped values from candidates.
    assert any(c['basis'] == 'exact_scfv_sequence' for c in candidates)
    # Build mapped values from candidates.
    assert all(c['decision'] == 'review_required' for c in candidates)
    # Build mapped values from process_batch([b, a])[0].
    assert [r.model_dump() for r in process_batch([b, a])[0]] == [r.model_dump() for r in rows]


# Verify that same name mutations and ambiguous residues do not match sequences.
def test_same_name_mutations_and_ambiguous_residues_do_not_match_sequences(tmp_path):
    path = write_rows(tmp_path / 'a.jsonl', [binder('a', name='clone', scfv_sequence='EVQLV'),
          binder('b', name='clone', scfv_sequence='EVQAV'), binder('c', scfv_sequence='EVQXV'),
          binder('d', scfv_sequence='EVQXV')])
    rows, audit, _, groups = process_batch([path])
    assert len(rows) == 4
    # Build mapped values from groups.
    assert not any(g['basis'] == 'exact_scfv_sequence' for g in groups)
    # Build mapped values from groups.
    assert any(g['basis'] == 'name_or_alias_only' for g in groups)
    # Build mapped values from audit.
    assert sum(e['reason'] == 'review_ambiguous_or_nonstandard_residue' for e in audit) == 2


# Verify that bad references and conflicting ids fail.
def test_bad_references_and_conflicting_ids_fail(tmp_path):
    path = write_rows(tmp_path / 'a.jsonl', [binder(), binder(name='different')])
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(OutputError, match='conflicting repeated ID'):
        process_batch([path])
    write_rows(path, [dict(table='evidence', data={'record_id': 'e', 'source_type': 'literature',
                                                'source_id': 'PMC1', 'binder.binder_id': 'missing'})])
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(OutputError, match='unresolved'):
        process_batch([path])


# Verify that linker names preserved and partial chains not sequence candidates.
def test_linker_names_preserved_and_partial_chains_not_sequence_candidates(tmp_path):
    paths = []
    # Process each n from range(2) independently.
    for n in range(2):
        row = binder('b', linker='GS linker', heavy_chain={'sequence': 'EVQLV', 'scope': 'partial'},
                     light_chain={'sequence': 'DIQMT', 'scope': 'variable_region'})
        paths.append(write_rows(tmp_path / f'{n}.jsonl', [row]))
    rows, _, _, groups = process_batch(paths)
    # Build mapped values from rows.
    assert all(r.data['linker'] == 'GS linker' for r in rows)
    # Build mapped values from groups.
    assert not any(g['basis'] == 'exact_vh_vl_pair' for g in groups)


# Verify that module order and individual observations preserved.
def test_module_order_and_individual_observations_preserved(tmp_path):
    modules = [{'module_type': 'hinge', 'sequence': 'ACDE'},
               {'module_type': 'signaling_domain', 'sequence': 'FGHI'}]
    # Build mapped values from range(2).
    observations = [dict(table='evidence', data={'record_id': f'e{i}', 'source_type': 'literature',
                       'source_id': 'PMC1', 'binder.binder_id': 'b1',
                       'applicable_scenario': f'donor {i}'}) for i in range(2)]
    path = write_rows(tmp_path / 'x.jsonl', [binder(),
                      dict(table='car', data={'car_id': 'c1', 'modules': modules}),
                      dict(table='car', data={'car_id': 'c2', 'modules': modules[::-1]}),
                      *observations])
    rows, _, _, groups = process_batch([path])
    # Collect items from rows only where r.table == 'evidence'.
    assert len([r for r in rows if r.table == 'evidence']) == 2
    # Build mapped values from groups.
    assert not any(g['basis'] == 'exact_ordered_backbone_modules' for g in groups)


# Verify that missing and incompatible units flagged not inferred.
def test_missing_and_incompatible_units_flagged_not_inferred():
    # Process each unit from (None, 'ng/mL') independently.
    for unit in (None, 'ng/mL'):
        m = {'kind': 'single_value', 'value': 2, 'unit': unit, 'raw': 'source text'}
        data, events = normalize_record('evidence', {'record_id': 'e', 'source_type': 'patent',
                                                    'source_id': 'WO1', 'binder.kd': m})
        assert data['binder.kd']['unit'] == unit
        assert data['binder.kd']['value'] == 2
        # Build mapped values from events.
        assert any(e['reason'] == 'review_missing_or_unconvertible_unit' for e in events)


# Verify that measurement types validated before conversion.
@pytest.mark.parametrize('unit', ['nM', 'uM'])
@pytest.mark.parametrize('invalid', [True, False, '2'])
@pytest.mark.parametrize('kind,field', [
    ('single_value', 'value'), ('greater_than', 'lower'),
    ('less_than', 'upper'), ('mean_with_standard_deviation', 'error'),
])
def test_measurement_types_validated_before_conversion(unit, invalid, kind, field):
    measurement = {'kind': kind, field: invalid, 'unit': unit, 'raw': 'invalid input'}
    # Supply a valid central value when testing an invalid error term so the assertion isolates that
    # term.
    if field == 'error':
        measurement['value'] = 2
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(OutputError, match=rf'binder.kd.{field}: expected number'):
        normalize_record('evidence', {'record_id': 'e', 'source_type': 'literature',
                                     'source_id': 'PMC1', 'binder.kd': measurement})


# Verify that measurement validation does not create spurious conversion events.
def test_measurement_validation_does_not_create_spurious_conversion_events():
    measurement = {'kind': 'single_value', 'value': 2, 'unit': 'nM', 'raw': '2 nM'}
    data, events = normalize_record('evidence', {'record_id': 'e', 'source_type': 'literature',
                                               'source_id': 'PMC1', 'binder.kd': measurement})
    assert data['binder.kd']['value'] == 2
    assert not events


# Verify that converted measurement is also validated.
def test_converted_measurement_is_also_validated():
    measurement = {'kind': 'single_value', 'value': 1e308, 'unit': 'uM', 'raw': '1e308 uM'}
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(OutputError, match='number must be finite'):
        normalize_record('evidence', {'record_id': 'e', 'source_type': 'literature',
                                     'source_id': 'PMC1', 'binder.kd': measurement})


# Verify that backbone candidates ignore optional metadata but preserve it.
@pytest.mark.parametrize('metadata', [
    {'source_molecule': 'CD8 alpha'}, {'length': 4},
    {'source_molecule': 'conflicting annotation', 'length': 5},
])
def test_backbone_candidates_ignore_optional_metadata_but_preserve_it(tmp_path, metadata):
    module = {'module_type': 'hinge', 'sequence': 'ACDE'}
    path = write_rows(tmp_path / 'cars.jsonl', [
        dict(table='car', data={'car_id': 'c1', 'modules': [module]}),
        dict(table='car', data={'car_id': 'c2', 'modules': [{**module, **metadata}]}),
    ])
    rows, _, provenance, groups = process_batch([path])
    # Collect items from groups only where g['basis'] == 'exact_ordered_backbone_modules'.
    matches = [g for g in groups if g['basis'] == 'exact_ordered_backbone_modules']
    assert len(matches) == 1
    # Build mapped values from rows.
    assert matches[0]['record_ids'] == [r.data['car_id'] for r in rows]
    assert matches[0]['decision'] == 'review_required'
    assert len(rows) == len(provenance) == 2
    # Process each (key, value) from metadata.items() independently.
    for key, value in metadata.items():
        assert rows[1].data['modules'][0][key] == value
        assert provenance[1]['original_row']['data']['modules'][0][key] == value


# Verify that backbone candidates require matching types and certain sequences.
@pytest.mark.parametrize('other', [
    {'module_type': 'hinge', 'sequence': 'ACDF'},
    {'module_type': 'tag', 'sequence': 'ACDE'},
    {'module_type': 'hinge', 'sequence': 'ACDX'},
    {'module_type': 'hinge', 'sequence': None},
])
def test_backbone_candidates_require_matching_types_and_certain_sequences(tmp_path, other):
    path = write_rows(tmp_path / 'cars.jsonl', [
        dict(table='car', data={'car_id': 'c1', 'modules': [
            {'module_type': 'hinge', 'sequence': 'ACDE'}]}),
        dict(table='car', data={'car_id': 'c2', 'modules': [other]}),
    ])
    # Build mapped values from process_batch([path])[3].
    assert not any(g['basis'] == 'exact_ordered_backbone_modules'
                   for g in process_batch([path])[3])


# Build linked A/B/C, combination, and evidence rows for reference-consistency checks.
def combination_rows():
    return [binder(), binder('b2'),
            dict(table='car', data={'car_id': 'c1', 'modules': []}),
            dict(table='car', data={'car_id': 'c2', 'modules': []}),
            dict(table='manufacturing', data={'manufacturing_id': 'm1'}),
            dict(table='manufacturing', data={'manufacturing_id': 'm2'}),
            dict(table='abc_combination_db1', data={'combination_id': 'abc',
                 'binder_id': 'b1', 'car_id': 'c1', 'manufacturing_id': 'm1'}),
            dict(table='evidence', data={'record_id': 'e', 'source_type': 'literature',
                 'source_id': 'PMC1', 'combination_id': 'abc', 'binder.binder_id': 'b1',
                 'car.car_id': 'c1', 'manufacturing.manufacturing_id': 'm1'})]


# Verify that evidence must agree with combination.
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('field,conflicting_id', [
    ('binder.binder_id', 'b2'), ('car.car_id', 'c2'),
    ('manufacturing.manufacturing_id', 'm2'),
])
def test_evidence_must_agree_with_combination(tmp_path, reverse, field, conflicting_id):
    records = combination_rows()
    records[-1]['data'][field] = conflicting_id
    # Use records[::-1] when reverse is truthy; otherwise use records.
    path = write_rows(tmp_path / 'combination.jsonl', records[::-1] if reverse else records)
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(OutputError, match=rf'{field} conflicts with combination'):
        process_batch([path])


# Verify that consistent combination references allow missing direct links.
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('partial', [False, True])
def test_consistent_combination_references_allow_missing_direct_links(tmp_path, reverse, partial):
    records = combination_rows()
    # When partial is truthy, leave records[-1]['data']['car.car_id'] unknown rather than guess a
    # replacement.
    if partial:
        records[-1]['data']['car.car_id'] = None
        records[-1]['data']['manufacturing.manufacturing_id'] = None
    # Use records[::-1] when reverse is truthy; otherwise use records.
    path = write_rows(tmp_path / 'combination.jsonl', records[::-1] if reverse else records)
    rows, _, _, _ = process_batch([path])
    # Collect items from rows only where r.table == 'evidence'.
    evidence = next(r.data for r in rows if r.table == 'evidence')
    # Collect items from rows only where r.table == 'abc_combination_db1'.
    combination = next(r.data for r in rows if r.table == 'abc_combination_db1')
    assert evidence['combination_id'] == combination['combination_id']
    assert evidence['binder.binder_id'] == combination['binder_id']
    # Process each entity from ('car', 'manufacturing') independently.
    for entity in ('car', 'manufacturing'):
        key = f'{entity}_id'
        # Use None when partial is truthy; otherwise use combination[key].
        assert evidence[f'{entity}.{key}'] == (None if partial else combination[key])
