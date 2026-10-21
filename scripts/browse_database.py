#!/usr/bin/env python3
"""中文只读数据浏览页面；--demo 使用现有独立演示库。"""
from pathlib import Path
import fcntl
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from cart_db.browser import serve
from cart_db.console import ChineseArgumentParser


# Select the configured or demo database and start the local read-only browser.
def main():
    parser = ChineseArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='启动并读取现有演示数据库，不执行抽取或入库')
    parser.add_argument('--port', type=int, default=8765, help='网页端口，默认 8765')
    args = parser.parse_args()
    # Reject the input: 端口必须在 1–65535 之间.
    if not 1 <= args.port <= 65535:
        parser.error('端口必须在 1–65535 之间')
    # Attempt this operation while preserving the explicit recovery/cleanup paths below.
    try:
        is_empty = None
        # Demo mode uses the owned local cluster and a lifecycle probe rather than the configured
        # business database.
        if args.demo:
            import demo_pipeline as demo
            import psycopg
            # Close the file reliably, including when reading or writing raises an error.
            with (ROOT/'.pipeline-demo.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Start the demo cluster only when its owned directory exists; absence is the
                # intentional empty-demo state.
                if demo.DEMO.exists():
                    demo.owned()
                    demo.start(demo.pg_bin())
            # The callback returns not demo.DEMO.exists().
            is_empty = lambda: not demo.DEMO.exists()
            # Connect explicitly to the private demo socket, bypassing business-database settings.
            def connect():
                return psycopg.connect(host=str(demo.DEMO/'socket'), port=int(demo.PORT),
                    user='demo', dbname='postgres', autocommit=True, connect_timeout=5)
            mode = '独立演示数据库'
        # Normal mode uses the environment-configured database connection.
        else:
            from cart_db.ingest import connect
            mode = '环境配置数据库'
        # Read-only readiness check. The browser never runs migrations.
        if not args.demo:
            # Close the database connection when this operation finishes or raises.
            with connect() as conn:
                # Keep these operations in one transaction so errors roll back the whole unit of
                # work.
                with conn.transaction():
                    conn.execute('SET TRANSACTION READ ONLY')
                    conn.execute('SELECT identity_status FROM cart.staged_record LIMIT 1')
        serve(connect, port=args.port, mode=mode, is_empty=is_empty)
    # On BlockingIOError, report this outcome to the command-line operator.
    except BlockingIOError:
        print('演示任务正在运行，请待其完成后启动浏览页面。', file=sys.stderr)
        return 1
    # On Exception, report this outcome to the command-line operator.
    except Exception:
        print('启动失败：请确认数据库存在、连接配置正确、已完成迁移，且网页端口未被占用。', file=sys.stderr)
        return 1
    return 0


# Run the command only when invoked as a script, not when imported by tests or other modules.
if __name__ == '__main__':
    raise SystemExit(main())
