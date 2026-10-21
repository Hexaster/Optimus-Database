"""Read-only HTTP browser integration, including provenance and untrusted content."""
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg
import pytest
from http.server import ThreadingHTTPServer
from cart_db import browser, ingest
from test_ingest import db, test_dsn, binder, evidence, write, stage


# Start an ephemeral local browser server for HTTP tests and stop it afterward.
@pytest.fixture
def web(db, test_dsn):
    # Open the isolated test database used by the browser handler.
    def connect():
        return psycopg.connect(**test_dsn, autocommit=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), browser.handler(connect, '测试数据库'))
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    worker.join()


# Request the local test server and decode its JSON response.
def get(web, path):
    # Release this managed resource when the enclosed operation completes or fails.
    with urlopen(web+path) as response:
        return json.load(response)


# Verify that live data search detail and source context.
def test_live_data_search_detail_and_source_context(web, db, tmp_path):
    assert get(web, '/api/summary')['sources'] == 0
    path = write(tmp_path, [binder(name='<script>alert(1)</script>'), evidence(citation='来源原文')])
    context = tmp_path/'reasoning.md'
    context.write_text('图 2：原始依据', encoding='utf-8')
    batch = ingest.stage_file(db, path, [context])
    ingest.publish(db, batch)
    report = get(web, '/api/summary')
    assert report['counts']['binder'] == report['sources'] == 1
    result = get(web, '/api/list?table=binder&q=script')
    assert result['total'] == 1
    identifier = result['items'][0]['binder_id']
    detail = get(web, '/api/detail?table=binder&id='+identifier)
    assert detail['sources'][0]['original']['data']['name'] == '<script>alert(1)</script>'
    assert detail['names'] == ['<script>alert(1)</script>']
    assert get(web, '/api/list?table=evidence&entity='+identifier)['total'] == 1
    from urllib.parse import urlencode
    saved = detail['sources'][0]['contexts'][0]
    params = urlencode(dict(batch=str(batch), name=saved['name'], checksum=saved['checksum']))
    assert get(web, '/api/context?'+params)['content'] == '图 2：原始依据'
    assert get(web, '/api/list?table=binder&page=2')['items'] == []
    # Same running server observes a later transaction, without a generated snapshot.
    bid, _ = stage(db, write(tmp_path, [binder(name='other', sequence='DIVMT')], 'second.jsonl'))
    ingest.publish(db, bid)
    assert get(web, '/api/summary')['counts']['binder'] == 2


# Verify that conflicts show both records and reason.
def test_conflicts_show_both_records_and_reason(web, db, tmp_path):
    first, _ = stage(db, write(tmp_path, [binder(name='FMC63')]))
    ingest.publish(db, first)
    second, _ = stage(db, write(tmp_path, [binder(name='FMC63',sequence='DIVMT')], 'second.jsonl'))
    ingest.publish(db, second)
    result = get(web, '/api/reviews?status=conflict')
    assert result['total'] == 1
    detail = get(web, '/api/review?id='+result['items'][0]['stage_id'])
    assert detail['record']['normalized']['scfv_sequence'] == 'DIVMT'
    assert detail['candidates'][0]['data']['scfv_sequence'] == 'EVQLVGGGGSAVLTQ'
    assert detail['candidates'][0]['comparison']['conflicts'] == ['scfv_sequence']


# Verify that rejects invalid requests.
@pytest.mark.parametrize('path,code', [
    ('/api/list?table=pg_authid',400),('/api/list?page=-1',400),
    ('/api/detail?table=binder&id=bad',400),('/api/reviews?status=wrong',400),
    ('/api/detail?table=binder&id=00000000-0000-0000-0000-000000000000',404),
    ('/../../.env',404),
])
def test_rejects_invalid_requests(web,path,code):
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(HTTPError) as exc:
        get(web,path)
    assert exc.value.code == code


# Verify that http read only boundary and static security.
def test_http_read_only_boundary_and_static_security(web):
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(HTTPError) as exc:
        urlopen(Request(web+'/api/list',data=b'{}',method='POST'))
    assert exc.value.code == 501
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(HTTPError) as exc:
        urlopen(Request(web+'/api/summary',headers={'Host':'evil.example'}))
    assert exc.value.code == 403
    # Release this managed resource when the enclosed operation completes or fails.
    with urlopen(web+'/') as response:
        assert 'frame-ancestors' in response.headers['Content-Security-Policy']
        assert '数据总览' in response.read().decode()
    # Release this managed resource when the enclosed operation completes or fails.
    with urlopen(web+'/app.js') as response:
        assert 'innerHTML' not in response.read().decode()


# Verify that requests use read only database transactions.
def test_requests_use_read_only_database_transactions(web, db, monkeypatch):
    # Read PostgreSQL transaction_read_only through the browser's query connection.
    def transaction_state(conn):
        return {'read_only': conn.execute('SHOW transaction_read_only').fetchone()[0]}
    monkeypatch.setattr(browser, 'summary', transaction_state)
    assert get(web, '/api/summary')['read_only'] == 'on'
    # Attempt a write inside the browser query boundary to verify read-only enforcement.
    def attempt_write(conn):
        conn.execute('DELETE FROM cart.record')
        return {}
    monkeypatch.setattr(browser, 'summary', attempt_write)
    # Require the operation to raise the expected error instead of accepting invalid input.
    with pytest.raises(HTTPError) as exc:
        get(web, '/api/summary')
    assert exc.value.code == 503


# Verify that demo empty state does not hide connection failures.
def test_demo_empty_state_does_not_hide_connection_failures():
    # Simulate a transport or connection failure rather than a successful empty result.
    def broken():
        raise psycopg.OperationalError('not running')
    # The callback returns True.
    assert browser.database_state(broken, lambda: True) == 'empty'
    # The callback returns False.
    assert browser.database_state(broken, lambda: False) == 'unavailable'


from test_demo_pipeline import demo, isolated


# Verify that real cleanup keeps web empty and recovers after new import.
def test_real_cleanup_keeps_web_empty_and_recovers_after_new_import(isolated, tmp_path):
    import os
    from pathlib import Path
    binaries = os.environ.get('CART_TEST_POSTGRES_BIN')
    # When binaries is empty or false, record the skipped download and its cause in the snapshot.
    if not binaries:
        pytest.skip('Set CART_TEST_POSTGRES_BIN for private demo lifecycle verification')
    binaries = Path(binaries)
    # Open the isolated test database used by the browser handler.
    def connect():
        return psycopg.connect(host=str(demo.DEMO/'socket'), port=demo.PORT,
                               user='demo', dbname='postgres', autocommit=True, connect_timeout=2)
    # The callback returns not demo.DEMO.exists().
    server = ThreadingHTTPServer(('127.0.0.1', 0), browser.handler(connect, '演示库', lambda: not demo.DEMO.exists()))
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    web = f'http://127.0.0.1:{server.server_port}'
    try:
        # The page also works before the first demo, without creating a database.
        assert get(web, '/api/state')['state'] == 'empty'
        assert get(web, '/api/summary')['sources'] == 0
        assert not demo.DEMO.exists()
        # Process each name from ('first', 'after-cleanup') independently.
        for name in ('first', 'after-cleanup'):
            demo.start(binaries)
            assert get(web, '/api/state')['state'] == 'initializing'
            # Close the database connection when this operation finishes or raises.
            with connect() as conn:
                ingest.migrate(conn)
                bid = ingest.stage_file(conn, write(tmp_path, [binder(name=name), evidence()], name+'.jsonl'))
                ingest.publish(conn, bid)
            assert get(web, '/api/state')['state'] == 'ready'
            assert get(web, '/api/summary')['counts']['binder'] == 1
            assert get(web, '/api/summary')['counts']['evidence'] == 1
            identifier = get(web, '/api/list?table=binder')['items'][0]['binder_id']
            demo.cleanup(binaries)
            assert get(web, '/api/state')['state'] == 'empty'
            assert get(web, '/api/summary') == dict(counts={}, sources=0, states={}, batches=[])
            assert get(web, '/api/list?table=binder')['items'] == []
            assert get(web, '/api/reviews')['total'] == 0
            # Require the operation to raise the expected error instead of accepting invalid input.
            with pytest.raises(HTTPError) as exc:
                get(web, '/api/detail?table=binder&id='+identifier)
            assert exc.value.code == 404
            # Release this managed resource when the enclosed operation completes or fails.
            with urlopen(web+'/') as response:
                assert response.status == 200
    # Stop the test HTTP server and join its worker before cleaning the isolated demo.
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
        # Remove any demo state still present after the test.
        if demo.DEMO.exists():
            demo.cleanup(binaries)
