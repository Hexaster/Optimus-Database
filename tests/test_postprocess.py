import json
from copy import deepcopy

import pytest

from cart_db.agent_output import OutputError
from cart_db.measurements import convert
from cart_db.postprocess import canonical_sequence, normalize_record, process_batch


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    return path


def binder(row_id='b1', **kw):
    return dict(table='binder', data=dict(binder_id=row_id, **kw))


def test_sequences_no_ocr_repair_or_annotation_stripping():
    assert canonical_sequence(' evq\nL\tV ') == 'EVQLV'
    for value in ('EVQ1V', '>VH\nEVQLV', 'EVQ-V', 'SEQ ID NO: 1 EVQLV', ''):
        assert canonical_sequence(value) is None
    row = binder(scfv_sequence=' evq\nLV ', linker='(G4S)3')
    before = deepcopy(row)
    data, events = normalize_record(row['table'], row['data'])
    assert data['scfv_sequence'] == 'EVQLV'
    assert data['linker'] == '(G4S)3'
    assert row == before
    assert events[0]['before'] == ' evq\nLV '


def test_nested_aliases_and_conflicts():
    rules = {'field_aliases': {'binder': {'VH': 'heavy_chain'}},
             'value_aliases': {'binder.heavy_chain.scope': {'VH': 'variable_region'}}}
    data, _ = normalize_record('binder', {'binder_id': 'b', 'VH':
                              {'sequence': 'evqlv', 'scope': 'VH'}}, rules)
    assert data['heavy_chain'] == {'sequence': 'EVQLV', 'scope': 'variable_region'}
    with pytest.raises(OutputError, match='conflicting fields'):
        normalize_record('binder', {'binder_id': 'b', 'VH': {}, 'heavy_chain': None}, rules)
    with pytest.raises(OutputError, match='unknown fields'):
        normalize_record('binder', {'binder_id': 'b', 'made_up': 2})


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


def test_scope_ids_references_and_retain_independent_evidence(tmp_path):
    records = [binder(name='clone', scfv_sequence='EVQLV'),
               dict(table='evidence', data={'record_id': 'e1', 'source_type': 'patent',
                    'source_id': 'WO1', 'binder.binder_id': 'b1'})]
    a = write_rows(tmp_path / 'a.jsonl', records + [records[0]])
    b = write_rows(tmp_path / 'b.jsonl', records)
    rows, audit, provenance, candidates = process_batch([a, b])
    assert len(rows) == 4 and len(provenance) == 5
    assert rows[0].data['binder_id'] != rows[2].data['binder_id']
    assert rows[1].data['binder.binder_id'] == rows[0].data['binder_id']
    assert rows[3].data['binder.binder_id'] == rows[2].data['binder_id']
    assert sum(e['reason'] == 'duplicate_serialization' for e in audit) == 1
    assert any(c['basis'] == 'exact_scfv_sequence' for c in candidates)
    assert all(c['decision'] == 'review_required' for c in candidates)
    assert [r.model_dump() for r in process_batch([b, a])[0]] == [r.model_dump() for r in rows]


def test_same_name_mutations_and_ambiguous_residues_do_not_match_sequences(tmp_path):
    path = write_rows(tmp_path / 'a.jsonl', [binder('a', name='clone', scfv_sequence='EVQLV'),
          binder('b', name='clone', scfv_sequence='EVQAV'), binder('c', scfv_sequence='EVQXV'),
          binder('d', scfv_sequence='EVQXV')])
    rows, audit, _, groups = process_batch([path])
    assert len(rows) == 4
    assert not any(g['basis'] == 'exact_scfv_sequence' for g in groups)
    assert any(g['basis'] == 'name_or_alias_only' for g in groups)
    assert sum(e['reason'] == 'review_ambiguous_or_nonstandard_residue' for e in audit) == 2


def test_bad_references_and_conflicting_ids_fail(tmp_path):
    path = write_rows(tmp_path / 'a.jsonl', [binder(), binder(name='different')])
    with pytest.raises(OutputError, match='conflicting repeated ID'):
        process_batch([path])
    write_rows(path, [dict(table='evidence', data={'record_id': 'e', 'source_type': 'literature',
                                                'source_id': 'PMC1', 'binder.binder_id': 'missing'})])
    with pytest.raises(OutputError, match='unresolved'):
        process_batch([path])


def test_linker_names_preserved_and_partial_chains_not_sequence_candidates(tmp_path):
    paths = []
    for n in range(2):
        row = binder('b', linker='GS linker', heavy_chain={'sequence': 'EVQLV', 'scope': 'partial'},
                     light_chain={'sequence': 'DIQMT', 'scope': 'variable_region'})
        paths.append(write_rows(tmp_path / f'{n}.jsonl', [row]))
    rows, _, _, groups = process_batch(paths)
    assert all(r.data['linker'] == 'GS linker' for r in rows)
    assert not any(g['basis'] == 'exact_vh_vl_pair' for g in groups)


def test_module_order_and_individual_observations_preserved(tmp_path):
    modules = [{'module_type': 'hinge', 'sequence': 'ACDE'},
               {'module_type': 'signaling_domain', 'sequence': 'FGHI'}]
    observations = [dict(table='evidence', data={'record_id': f'e{i}', 'source_type': 'literature',
                       'source_id': 'PMC1', 'binder.binder_id': 'b1',
                       'applicable_scenario': f'donor {i}'}) for i in range(2)]
    path = write_rows(tmp_path / 'x.jsonl', [binder(),
                      dict(table='car', data={'car_id': 'c1', 'modules': modules}),
                      dict(table='car', data={'car_id': 'c2', 'modules': modules[::-1]}),
                      *observations])
    rows, _, _, groups = process_batch([path])
    assert len([r for r in rows if r.table == 'evidence']) == 2
    assert not any(g['basis'] == 'exact_ordered_backbone_modules' for g in groups)


def test_missing_and_incompatible_units_flagged_not_inferred():
    for unit in (None, 'ng/mL'):
        m = {'kind': 'single_value', 'value': 2, 'unit': unit, 'raw': 'source text'}
        data, events = normalize_record('evidence', {'record_id': 'e', 'source_type': 'patent',
                                                    'source_id': 'WO1', 'binder.kd': m})
        assert data['binder.kd']['unit'] == unit
        assert data['binder.kd']['value'] == 2
        assert any(e['reason'] == 'review_missing_or_unconvertible_unit' for e in events)
