"""Local, read-only database browser; no extraction or database mutation."""
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from psycopg import sql
from psycopg.rows import dict_row

from .ingest_schema import TABLES, column, primary_key
from .schema_models import load_schema

STATIC = Path(__file__).with_name('web')
ENTITIES = ('binder', 'car', 'manufacturing')


def rows(conn, query, params=()):
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def valid_table(value):
    if value not in TABLES:
        raise ValueError('未知数据类型')
    return value


def page_args(params):
    page = int(params.get('page', '1'))
    if not 1 <= page <= 100000:
        raise ValueError('页码超出范围')
    return 20, (page - 1) * 20


def summary(conn):
    counts = {r['table_name']: r['n'] for r in rows(conn,
        'SELECT table_name,count(*) n FROM cart.record GROUP BY table_name')}
    sources = rows(conn, 'SELECT count(DISTINCT (source_type,source_id)) n FROM cart.evidence')[0]['n']
    # Review counts refer to source records, not unique accepted entities.
    states = {r['identity_status']:r['n'] for r in rows(conn, '''SELECT identity_status,count(*) n
        FROM cart.staged_record WHERE status='published' AND identity_status IS NOT NULL
        GROUP BY identity_status''')}
    batches = rows(conn, '''SELECT b.batch_id,b.input_name,b.created_at,
        count(*) FILTER (WHERE s.status='published') published,
        count(*) FILTER (WHERE s.status='pending') pending,
        count(*) FILTER (WHERE s.status='invalid') invalid
        FROM cart.import_batch b LEFT JOIN cart.staged_record s USING(batch_id)
        GROUP BY b.batch_id ORDER BY b.created_at DESC LIMIT 8''')
    return dict(counts=counts, sources=sources, states=states, batches=batches)


def listing(conn, params):
    table = valid_table(params.get('table', 'binder'))
    limit, offset = page_args(params)
    query = params.get('q', '').strip()
    if len(query) > 300:
        raise ValueError('搜索内容过长')
    conditions, args = [], []
    if query:
        # Literal substring search, not user-controlled SQL or LIKE wildcards.
        if table in ENTITIES:
            conditions.append(sql.SQL("""(strpos(lower(to_jsonb(t)::text),lower(%s))>0 OR EXISTS
                (SELECT 1 FROM cart.entity_name n WHERE n.entity_id=t.{}
                 AND strpos(lower(n.name),lower(%s))>0))""").format(sql.Identifier(primary_key(table))))
            args.extend([query, query])
        else:
            conditions.append(sql.SQL("strpos(lower(to_jsonb(t)::text),lower(%s))>0"))
            args.append(query)
    if params.get('entity'):
        if table != 'evidence':
            raise ValueError('实体筛选仅用于证据列表')
        entity = UUID(params['entity'])
        conditions.append(sql.SQL('(t.binder_id=%s OR t.car_id=%s OR t.manufacturing_id=%s OR t.combination_id=%s)'))
        args.extend([entity] * 4)
    where = sql.SQL(' AND ').join(conditions) if conditions else sql.SQL('true')
    total = rows(conn, sql.SQL('SELECT count(*) n FROM cart.{} t WHERE {}').format(sql.Identifier(table), where), args)[0]['n']
    found = rows(conn, sql.SQL("SELECT to_jsonb(t)-'record_kind' data FROM cart.{} t WHERE {} ORDER BY {} LIMIT %s OFFSET %s").format(
        sql.Identifier(table), where, sql.Identifier(primary_key(table))), [*args, limit, offset])
    return dict(total=total, items=[r['data'] for r in found], page=offset//limit+1)


def get_record(conn, table, identifier):
    table, identifier = valid_table(table), UUID(str(identifier))
    result = rows(conn, sql.SQL("SELECT to_jsonb(t)-'record_kind' data FROM cart.{} t WHERE {}=%s").format(
        sql.Identifier(table), sql.Identifier(primary_key(table))), (identifier,))
    if not result:
        raise LookupError('记录不存在')
    return result[0]['data']


def detail(conn, params):
    table, identifier = valid_table(params['table']), UUID(params['id'])
    data = get_record(conn, table, identifier)
    limit, offset = page_args(params)
    sources = rows(conn, '''SELECT s.stage_id,s.batch_id,s.line_number,s.local_id,s.original,s.normalized,
        s.identity_status,s.identity_details,b.input_name,
        (SELECT jsonb_agg(jsonb_build_object('name',c.name,'checksum',c.checksum) ORDER BY c.name)
         FROM cart.import_context c WHERE c.batch_id=s.batch_id) contexts
        FROM cart.staged_record s JOIN cart.import_batch b USING(batch_id)
        WHERE s.target_id=%s ORDER BY b.created_at,s.line_number LIMIT %s OFFSET %s''', (identifier, limit, offset))
    total = rows(conn, 'SELECT count(*) n FROM cart.staged_record WHERE target_id=%s', (identifier,))[0]['n']
    names = rows(conn, 'SELECT DISTINCT name FROM cart.entity_name WHERE entity_id=%s ORDER BY name', (identifier,))
    return dict(data=data, names=[r['name'] for r in names], sources=sources, total=total, page=offset//limit+1)


def reviews(conn, params):
    status = params.get('status', 'unresolved')
    if status not in ('unresolved', 'conflict', 'similar'):
        raise ValueError('未知匹配状态')
    limit, offset = page_args(params)
    total = rows(conn, "SELECT count(*) n FROM cart.staged_record WHERE status='published' AND identity_status=%s", (status,))[0]['n']
    items = rows(conn, '''SELECT stage_id,table_name,target_id,normalized->>'name' name,line_number,
        identity_status,identity_details->>'reason' reason,b.input_name
        FROM cart.staged_record s JOIN cart.import_batch b USING(batch_id)
        WHERE s.status='published' AND s.identity_status=%s
        ORDER BY s.published_at DESC,s.stage_id LIMIT %s OFFSET %s''', (status, limit, offset))
    return dict(total=total, items=items, page=offset//limit+1)


def review(conn, params):
    found = rows(conn, '''SELECT stage_id,table_name,normalized,original,identity_details,identity_status,
        target_id,batch_id,line_number FROM cart.staged_record WHERE stage_id=%s''', (UUID(params['id']),))
    if not found:
        raise LookupError('来源记录不存在')
    item = found[0]
    candidates = (item['identity_details'] or {}).get('candidates', [])
    comparisons = []
    for candidate in candidates[:50]:
        candidate = dict(candidate)
        if candidate['location'] == 'accepted':
            candidate['data'] = get_record(conn, item['table_name'], candidate['id'])
        else:
            staged = rows(conn, 'SELECT normalized,target_id FROM cart.staged_record WHERE stage_id=%s', (UUID(candidate['id']),))
            candidate['data'] = staged[0]['normalized'] if staged else None
            candidate['target_id'] = staged[0]['target_id'] if staged else None
        comparisons.append(candidate)
    return dict(record=item, candidates=comparisons, total=len(candidates))


def context(conn, params):
    result = rows(conn, 'SELECT content FROM cart.import_context WHERE batch_id=%s AND name=%s AND checksum=%s',
                  (UUID(params['batch']), params['name'], params['checksum']))
    if not result:
        raise LookupError('来源附件不存在')
    return dict(content=result[0]['content'])


def metadata():
    return {table: {column(key):dict(description=spec.get('description', ''), key=key)
                   for key,spec in fields.items()} for table,fields in load_schema().tables.items()}


def serialize(value):
    if isinstance(value, (UUID, datetime, date)):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)  # Preserve numerical precision in the viewer.
    raise TypeError(type(value).__name__)


def empty_result(path, params):
    """An intentionally removed demo behaves like an empty database."""
    if path == '/api/summary':
        return dict(counts={}, sources=0, states={}, batches=[])
    if path in ('/api/list', '/api/reviews'):
        limit, offset = page_args(params)
        return dict(total=0, items=[], page=offset//limit+1)
    raise LookupError('记录不存在')


def database_state(connect, is_empty):
    if is_empty():
        return 'empty'
    try:
        with connect() as conn:
            with conn.transaction():
                conn.execute('SET TRANSACTION READ ONLY')
                conn.execute("SET LOCAL statement_timeout='2s'")
                ready = conn.execute("SELECT to_regclass('cart.staged_record')").fetchone()[0]
                return 'ready' if ready else 'initializing'
    except Exception:
        return 'empty' if is_empty() else 'unavailable'


def handler(connect, mode, is_empty=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Do not log source content, search strings or database credentials.
            pass

        def respond(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # Only local Host headers; no CORS or remote binding.
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                self.respond(403, '仅支持本机访问'.encode(), 'text/plain; charset=utf-8')
                return
            parsed = urlsplit(self.path)
            static = {'/': ('index.html', 'text/html'), '/app.js': ('app.js','text/javascript'), '/style.css': ('style.css','text/css')}
            if parsed.path in static:
                name, mime = static[parsed.path]
                self.respond(200, (STATIC/name).read_bytes(), mime+'; charset=utf-8')
                return
            try:
                params = {k:v[-1] for k,v in parse_qs(parsed.query).items()}
                routes = {'/api/list':listing, '/api/detail':detail, '/api/reviews':reviews,
                          '/api/review':review, '/api/context':context}
                if parsed.path == '/api/meta':
                    result = dict(fields=metadata(), mode=mode, demo=is_empty is not None)
                elif parsed.path == '/api/state':
                    result = dict(state=database_state(connect, is_empty) if is_empty else 'ready')
                elif parsed.path == '/api/summary' or parsed.path in routes:
                    if is_empty and is_empty():
                        result = empty_result(parsed.path, params)
                    else:
                        try:
                            with connect() as conn:
                                with conn.transaction():
                                    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                                    conn.execute("SET LOCAL statement_timeout='8s'")
                                    result = summary(conn) if parsed.path == '/api/summary' else routes[parsed.path](conn, params)
                        except Exception:
                            # Cleanup may finish while a query is in flight.
                            if not is_empty or not is_empty():
                                raise
                            result = empty_result(parsed.path, params)
                else:
                    raise LookupError('页面不存在')
                self.respond(200, json.dumps(result, ensure_ascii=False, default=serialize).encode(), 'application/json; charset=utf-8')
            except (ValueError, KeyError):
                self.respond(400, json.dumps({'error':'请求参数无效'},ensure_ascii=False).encode(), 'application/json; charset=utf-8')
            except LookupError as exc:
                self.respond(404, json.dumps({'error':str(exc)},ensure_ascii=False).encode(), 'application/json; charset=utf-8')
            except Exception:
                self.respond(503, json.dumps({'error':'读取失败，请确认数据库已启动且已完成迁移，然后刷新。'},ensure_ascii=False).encode(), 'application/json; charset=utf-8')
    return Handler


def serve(connect, *, port=8765, mode='配置数据库', is_empty=None):
    server = ThreadingHTTPServer(('127.0.0.1', port), handler(connect, mode, is_empty))
    print(f'数据浏览页面已启动：http://127.0.0.1:{server.server_port}', flush=True)
    print(f'当前连接：{mode}；只读浏览，点击“刷新数据”获取最新结果。按 Ctrl+C 停止网页服务。', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n网页服务已停止，数据库和数据保留。', flush=True)
    finally:
        server.server_close()
