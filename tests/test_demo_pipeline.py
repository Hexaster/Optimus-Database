"""Disposable demo lifecycle; never invokes a model or a configured business DB."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile

import psycopg
import pytest

spec = importlib.util.spec_from_file_location('demo_pipeline', Path(__file__).resolve().parents[1] / 'scripts/demo_pipeline.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


@pytest.fixture
def isolated(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='cart-demo-') as directory:
        root = Path(directory)
        monkeypatch.setattr(demo, 'ROOT', root)
        monkeypatch.setattr(demo, 'DEMO', root / '.pipeline-demo')
        yield root


def test_connection_ignores_business_environment(isolated, monkeypatch):
    monkeypatch.setenv('PGHOST', 'business.example')
    monkeypatch.setenv('PGUSER', 'business')
    monkeypatch.setenv('PGPASSWORD', 'not-for-demo')
    env = demo.environment()
    assert env['PGHOST'] == str(demo.DEMO / 'socket')
    assert env['PGUSER'] == 'demo' and env['PGPASSWORD'] == ''


def test_cleanup_refuses_unowned_directory(isolated):
    demo.DEMO.mkdir()
    original = demo.DEMO / 'important.txt'
    original.write_text('keep')
    with pytest.raises((ValueError, OSError)):
        demo.cleanup(Path('/unused'))
    assert original.read_text() == 'keep'


def test_dry_run_forwards_model_and_does_not_start_db(isolated, monkeypatch):
    monkeypatch.setattr(demo, 'pg_bin', lambda: Path('/unused'))
    monkeypatch.setattr(demo, 'start', lambda *a: pytest.fail('dry run started DB'))
    calls = []
    monkeypatch.setattr(demo.subprocess, 'call', lambda args, **kwargs: calls.append((args, kwargs)) or 0)
    assert demo.main(['run', '--file', 'source.pdf', '--agent', 'codex', '--model', 'example', '--dry-run']) == 0
    command, options = calls[0]
    assert '--import-db' in command and command[-1] == str(demo.DEMO / 'output')
    assert command[command.index('--model') + 1] == 'example'
    assert options['env']['PGHOST'] == str(demo.DEMO / 'socket')
    assert not demo.DEMO.exists()


def test_input_cannot_be_inside_cleanup_directory(isolated):
    with pytest.raises(SystemExit):
        demo.main(['run', '--file', str(demo.DEMO / 'source.pdf')])


def test_real_private_postgres_start_query_stop_cleanup(isolated):
    binaries = os.environ.get('CART_TEST_POSTGRES_BIN')
    if not binaries:
        pytest.skip('Set CART_TEST_POSTGRES_BIN for the disposable server lifecycle test')
    binaries = Path(binaries)
    source = isolated / 'source.xml'
    source.write_text('<article/>')
    try:
        demo.start(binaries)
        env = demo.environment()
        with psycopg.connect(host=env['PGHOST'], port=env['PGPORT'], user=env['PGUSER'],
                             dbname=env['PGDATABASE'], password='') as conn:
            assert conn.execute('SHOW listen_addresses').fetchone()[0] == ''
            conn.execute('CREATE TABLE demo_probe(id integer)')
        demo.start(binaries)  # Reuse the same instance for continued display.
        (demo.DEMO / 'output').mkdir()
        (demo.DEMO / 'output' / 'data.jsonl').write_text('{}\n')
        demo.cleanup(binaries)
        assert not demo.DEMO.exists()
        assert source.read_text() == '<article/>'
    finally:
        if demo.DEMO.exists():
            demo.cleanup(binaries)
