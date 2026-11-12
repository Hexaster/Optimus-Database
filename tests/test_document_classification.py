"""Offline checks for shared credentials and additive patent routing."""
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from cart_db import document_classification as classifier
from cart_db.artifacts import checksum, verify_artifacts

spec = importlib.util.spec_from_file_location('patent_runner', Path(__file__).parents[1] / 'scripts/run_extraction_agent.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def receipt(path, route='literature'):
    response = {'model': 'typesafe/jev-1.14', 'answers': {'document_type': {
        'type': 'choice', 'choice': route, 'confidence': 1,
        'probabilities': {key: int(key == route) for key in classifier.QUESTION['criteria']}}},
        'usage': {'input_tokens': 10, 'output_tokens': 1, 'cost': 0.001}}
    return {'routing_version': 1, 'source_sha256': checksum(path), 'document_type': route,
            'request': {}, 'response': response, 'cost_usd': 0.001}


def test_openrouter_shared_key(tmp_path, monkeypatch):
    source = tmp_path / 'patent.md'
    source.write_text('A scientific paper discussing patents.')
    configured = replace(classifier.settings, openrouter_api_key='shared-test-key',
                         openai_api_key='other-test-key', openai_base_url='https://openrouter.ai/api/v1')
    monkeypatch.setattr(classifier, 'settings', configured)
    monkeypatch.setattr(runner, 'settings', configured)
    monkeypatch.setenv('OPENAI_API_KEY', 'inherited-test-key')
    def respond(request):
        assert str(request.url) == 'https://openrouter.ai/api/alpha/decisions'
        assert request.headers['Authorization'] == 'Bearer shared-test-key'
        assert json.loads(request.content)['questions']['document_type']['type'] == 'choice'
        return httpx.Response(200, json=receipt(source)['response'])
    client = httpx.Client
    monkeypatch.setattr(classifier.httpx, 'Client', lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    assert classifier.classify_document(source, timeout=10)['document_type'] == 'literature'
    assert runner.child_env('codex')['OPENAI_API_KEY'] == 'shared-test-key'
    monkeypatch.setattr(runner, 'settings', replace(configured, openai_base_url='https://api.openai.com/v1'))
    assert runner.child_env('codex')['OPENAI_API_KEY'] == 'other-test-key'


@pytest.mark.parametrize('route', ['literature', 'patent', 'unknown'])
def test_routing(tmp_path, monkeypatch, route):
    source = tmp_path / 'source.md'
    source.write_text('Synthetic document')
    calls = []
    monkeypatch.setattr(runner, 'classify_document', lambda path, **kw: receipt(path, route))
    def fake(path, *, out_dir, document_type, **kw):
        calls.append(document_type)
        rows = [{'table': 'binder', 'data': {'binder_id': 'b1'}}]
        if route == 'patent':
            rows.append({'table': 'patent', 'data': {'patent_id': 'p1'}})
        (out_dir / 'data.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        (out_dir / 'reasoning.md').write_text('Synthetic provenance')
        (out_dir / 'figures.jsonl').write_text('')
        (out_dir / 'img').mkdir(exist_ok=True)
        return dict(ok=True, reason='', usage=runner.empty_usage(), usage_known=True, cost=0.0)
    monkeypatch.setattr(runner, '_run_agent', fake)
    result = runner.run_one(source, out_dir=tmp_path / 'out', timeout=30, budget=None, validation_retries=0)
    if route == 'unknown':
        assert not result['ok']
        assert calls == []
        return
    assert result['ok'], result
    final = tmp_path / 'out/source'
    assert json.loads((final / 'data.jsonl').read_text())['table'] == 'binder'
    assert (final / 'patent.jsonl').exists() == (route == 'patent')
    verify_artifacts(final, source, require_classification=True)
    (final / 'document_classification.json').write_text('{}')
    with pytest.raises(ValueError):
        verify_artifacts(final, source, require_classification=True)


def test_invalid_cost_and_ties(tmp_path):
    path = tmp_path / 'a.txt'
    path.write_text('text')
    response = receipt(path)['response']
    response['usage']['cost'] = -1
    with pytest.raises(ValueError):
        classifier.decision(response)
    response['usage']['cost'] = None
    response['answers']['document_type']['probabilities'] = {'literature': .5, 'patent': .5, 'unknown': 0}
    assert classifier.decision(response) == 'unknown'


def test_missing_shared_key_does_not_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(classifier, 'settings', replace(classifier.settings, openrouter_api_key=None, openai_api_key='other'))
    with pytest.raises(ValueError, match='OPENROUTER_API_KEY'):
        classifier.classify_document(tmp_path / 'absent', timeout=10)


def test_codex_openrouter_requires_shared_key(monkeypatch):
    monkeypatch.setattr(runner, 'settings', replace(runner.settings,
        openrouter_api_key=None, openai_api_key='other', openai_base_url='https://openrouter.ai/api/v1'))
    with pytest.raises(ValueError, match='OPENROUTER_API_KEY'):
        runner.child_env('codex')


def test_patent_entity_links_and_route_guard(tmp_path):
    from cart_db.agent_output import prepare_output
    path = tmp_path / 'data.jsonl'
    rows = [{'table': 'binder', 'data': {'binder_id': 'b'}},
            {'table': 'patent', 'data': {'patent_id': 'p', 'entity_links': [{
                'relation_type': 'disclosed_in_description', 'entity_type': 'binder',
                'entity_id': 'b', 'basis_text': 'Synthetic source reference'}]}}]
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    result = [json.loads(line) for line in prepare_output(path, document_type='patent').splitlines()]
    assert result[1]['data']['entity_links'][0]['entity_id'] == result[0]['data']['binder_id']
    with pytest.raises(ValueError, match='require Jev patent'):
        prepare_output(path, document_type='literature')
