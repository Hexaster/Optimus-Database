#!/usr/bin/env python3
"""完整文档提取演示：独立 PostgreSQL、独立输出，展示结束后显式清理。"""
from pathlib import Path
import fcntl
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cart_db.console import ChineseArgumentParser

DEMO = ROOT / '.pipeline-demo'
MARKER = 'fosun-pipeline-demo-v1'
PORT = '55440'


# Locate installed PostgreSQL server tools without installing software or starting a server.
def pg_bin():
    executable = shutil.which('initdb')
    # When executable is truthy, return Path(executable).parent.
    if executable:
        return Path(executable).parent
    config = shutil.which('pg_config')
    # Use pg_config to locate PostgreSQL binaries when initdb is not directly on PATH.
    if config:
        path = Path(subprocess.check_output([config, '--bindir'], text=True).strip())
        # When (path / 'initdb').is_file(), return path.
        if (path / 'initdb').is_file():
            return path
    # Visit the discovered files in the explicitly chosen order.
    for executable in sorted(Path('/usr/lib/postgresql').glob('*/bin/initdb'), reverse=True):
        # When (executable.parent / 'pg_ctl').is_file(), return executable.parent.
        if (executable.parent / 'pg_ctl').is_file():
            return executable.parent
    raise ValueError('找不到 PostgreSQL 服务端工具 initdb / pg_ctl，请先安装 PostgreSQL')


# Require the demo ownership marker and ordinary directories before starting or deleting local
# state.
def owned():
    # Stop with a diagnostic: 演示目录不存在或不是普通目录.
    if DEMO.is_symlink() or not DEMO.is_dir():
        raise ValueError('演示目录不存在或不是普通目录')
    marker = DEMO / 'owner.json'
    # Stop with a diagnostic: 演示目录缺少本工具的所有权标记，拒绝启动或清理.
    if marker.is_symlink() or json.loads(marker.read_text()).get('owner') != MARKER:
        raise ValueError('演示目录缺少本工具的所有权标记，拒绝启动或清理')
    # Stop with a diagnostic: 演示目录包含外部目录链接，拒绝操作.
    if any((DEMO / name).is_symlink() for name in ('pgdata', 'socket', 'output')):
        raise ValueError('演示目录包含外部目录链接，拒绝操作')


# Force child processes to use the private demo socket rather than the configured business database.
def environment():
    env = os.environ.copy()
    # Override even a business-database .env; dotenv does not override these values.
    env.update(PGHOST=str(DEMO / 'socket'), PGPORT=PORT, PGUSER='demo',
               PGDATABASE='postgres', PGPASSWORD='', PGSSLMODE='disable')
    # Process each key from ('PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS') independently.
    for key in ('PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS'):
        env.pop(key, None)
    return env


# Run pg_ctl against this demo cluster and return captured output for the caller to inspect.
def control(binaries, *args):
    return subprocess.run([str(binaries / 'pg_ctl'), '-D', str(DEMO / 'pgdata'), *args],
                          capture_output=True, text=True)


# Initialize the owned demo cluster if needed and start it on a private Unix socket.
def start(binaries):
    # Create the demo directory and ownership marker before initializing local database state.
    if not DEMO.exists():
        DEMO.mkdir(mode=0o700)
        (DEMO / 'owner.json').write_text(json.dumps({'owner': MARKER}), encoding='utf-8')
    owned()
    (DEMO / 'socket').mkdir(mode=0o700, exist_ok=True)
    # When DEMO / 'pgdata' / 'PG_VERSION' is missing, report this outcome to the command-line
    # operator.
    if not (DEMO / 'pgdata' / 'PG_VERSION').exists():
        print('正在初始化独立演示数据库……', flush=True)
        result = subprocess.run([str(binaries / 'initdb'), '-D', str(DEMO / 'pgdata'),
                                 '-U', 'demo', '-A', 'trust', '--encoding=UTF8', '--no-locale'],
                                capture_output=True, text=True)
        (DEMO / 'setup.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        # Stop with a diagnostic: 演示数据库初始化失败，详情见 {DEMO / 'setup.log'}.
        if result.returncode:
            raise ValueError(f'演示数据库初始化失败，详情见 {DEMO / "setup.log"}')
    if control(binaries, 'status').returncode:
        # Unix socket in a private directory only; never bind localhost:5432 or TCP.
        result = control(binaries, '-l', str(DEMO / 'postgres.log'), '-o',
                         f'-k "{DEMO / "socket"}" -p {PORT} -h ""', 'start')
        # Stop with a diagnostic: 演示数据库启动失败，详情见 {DEMO / 'postgres.log'}.
        if result.returncode:
            raise ValueError(f'演示数据库启动失败，详情见 {DEMO / "postgres.log"}')


# Stop and verify the owned demo cluster before deleting its database, results, and logs.
def cleanup(binaries):
    # When DEMO is missing, report this outcome to the command-line operator.
    if not DEMO.exists():
        print('没有需要清理的演示环境。')
        return
    owned()
    # When (DEMO / 'pgdata' / 'PG_VERSION').exists() and control(binaries, 'status').returncode ==
    # 0, run the selected operation and retain its result.
    if (DEMO / 'pgdata' / 'PG_VERSION').exists() and control(binaries, 'status').returncode == 0:
        result = control(binaries, '-m', 'fast', 'stop')
        # Stop with a diagnostic: 演示数据库未能停止，未删除任何文件.
        if result.returncode:
            raise ValueError('演示数据库未能停止，未删除任何文件')
    # A stale PID file can also mean an unverified server: never remove its data.
    if (DEMO / 'pgdata' / 'postmaster.pid').exists():
        raise ValueError('仍有数据库进程标记，无法确认已停止，未删除演示目录')
    shutil.rmtree(DEMO)
    print('已停止并删除演示数据库，清理本次演示的提取结果和日志；输入 PDF/XML 保留。')


# Validate demo inputs, lock against concurrent cleanup, and dispatch run/query/cleanup operations.
def main(argv=None):
    parser = ChineseArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'psql', 'cleanup'),
                        help='run 运行完整演示；psql 查看数据库；cleanup 结束展示并删除演示数据')
    args, forwarded = parser.parse_known_args(argv)
    # Remove the CLI separator before forwarding extraction arguments.
    if forwarded[:1] == ['--']:
        forwarded = forwarded[1:]
    # Reject the input: 只有 run 接受原提取命令参数.
    if args.action != 'run' and forwarded:
        parser.error('只有 run 接受原提取命令参数')
    # Reject the input: 请通过 --file 或 --dir 明确指定演示输入文档.
    if args.action == 'run' and not any(a == '--file' or a.startswith('--file=') or a == '--dir' or a.startswith('--dir=') for a in forwarded):
        parser.error('请通过 --file 或 --dir 明确指定演示输入文档')
    # Reject the input: 演示输出固定保存在 .pipeline-demo/output，不接受 --out-dir.
    if any(a == '--out-dir' or a.startswith('--out-dir=') for a in forwarded):
        parser.error('演示输出固定保存在 .pipeline-demo/output，不接受 --out-dir')
    # Before a demo run, reject input documents located inside the directory that cleanup owns.
    if args.action == 'run':
        # Process each (index, argument) from enumerate(forwarded) independently.
        for index, argument in enumerate(forwarded):
            # Read the separate value after --file or --dir before checking the source path.
            if argument in ('--file', '--dir') and index + 1 < len(forwarded):
                source = forwarded[index + 1]
            # Also recognize --file=PATH and --dir=PATH spellings.
            elif argument.startswith(('--file=', '--dir=')):
                source = argument.split('=', 1)[1]
            # Otherwise, skip this item and continue checking the remaining inputs.
            else:
                continue
            # Reject the input: 原始文档必须放在演示目录之外，避免清理时删除输入.
            if (ROOT / source).resolve().is_relative_to(DEMO.resolve()):
                parser.error('原始文档必须放在演示目录之外，避免清理时删除输入')
    try:
        # Keep the lock outside the directory being removed; another command cannot
        # clean up an active extraction or a psql session opened with this tool.
        with (ROOT / '.pipeline-demo.lock').open('a') as lock:
            # Attempt this operation while preserving the explicit recovery/cleanup paths below.
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # On BlockingIOError, stop with a diagnostic: 已有演示任务或查询终端在运行，请结束后再执行此命令.
            except BlockingIOError:
                raise ValueError('已有演示任务或查询终端在运行，请结束后再执行此命令')
            # Use None when args.action == 'run' and '--dry-run' in forwarded; otherwise use
            # pg_bin().
            binaries = None if args.action == 'run' and '--dry-run' in forwarded else pg_bin()
            # Cleanup stops the owned cluster and removes its demo assets, then exits.
            if args.action == 'cleanup':
                cleanup(binaries)
                return 0
            # The psql action verifies ownership, starts the demo if needed, and opens its
            # interactive SQL client.
            if args.action == 'psql':
                owned()
                start(binaries)
                print('查看表：SELECT * FROM cart.binder;  退出：\\q', flush=True)
                return subprocess.call([str(binaries / 'psql'), '-X'], env=environment())
            # A dry run previews extraction without starting or initializing PostgreSQL.
            if '--dry-run' not in forwarded:
                start(binaries)
            command = [sys.executable, str(ROOT / 'scripts/run_extraction_agent.py'),
                       *forwarded, '--import-db', '--out-dir', str(DEMO / 'output')]
            code = subprocess.call(command, cwd=ROOT, env=environment())
            # When '--dry-run' is not in forwarded, report this outcome to the command-line
            # operator.
            if '--dry-run' not in forwarded:
                print('\n演示结果已保留，可继续展示和查询。', flush=True)
                print('查看数据库：python scripts/demo_pipeline.py psql', flush=True)
                print('展示结束后清理：python scripts/demo_pipeline.py cleanup', flush=True)
            return code
    # On (OSError, ValueError, subprocess.SubprocessError), report this outcome to the command-line
    # operator.
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'演示操作未完成：{exc}', file=sys.stderr)
        return 1
    # On KeyboardInterrupt, report this outcome to the command-line operator.
    except KeyboardInterrupt:
        print('\n演示已中断；结果保留。展示结束后执行 cleanup 清理。', file=sys.stderr)
        return 130


# Run the command only when invoked as a script, not when imported by tests or other modules.
if __name__ == '__main__':
    raise SystemExit(main())
