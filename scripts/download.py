#!/usr/bin/env python3
"""按 source registry 下载原始数据。

    python scripts/download.py <registry> [--route ID] [--limit N] [--dry-run]

<registry> 可以是 `europe_pmc`、`europe_pmc.yaml` 或完整路径。
真正执行什么，全看该 registry 里的「下载配置」块——本脚本不含任何源专属逻辑。

例：
    python scripts/download.py ema_epar --route assessment_reports
    python scripts/download.py europe_pmc --route process_corpus --limit 50
    python scripts/download.py fda_cber_cgt --dry-run
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cart_db.downloaders.base import (  # noqa: E402
    DownloadError,
    Snapshot,
    load_registry,
    register_snapshot,
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("registry", help="registry 名或路径，如 europe_pmc")
    ap.add_argument("--route", help="registry 里有多条 route 时必填")
    ap.add_argument("--limit", type=int, help="只取前 N 条，用于试跑")
    ap.add_argument("--snapshot", help="快照目录名，默认今天 YYYYMMDD")
    ap.add_argument("--dry-run", action="store_true", help="只探查不落盘")
    ap.add_argument("--register", action="store_true",
                    help="把落盘文件登记进 core.source_registry（需要数据库）")
    ap.add_argument("--list", action="store_true", help="列出该 registry 的 route 后退出")
    args = ap.parse_args()

    try:
        reg = load_registry(args.registry)
    except DownloadError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    if args.list:
        print(f"{reg.source_name}（{reg.path.name}）")
        for rid in reg.route_ids():
            print(f"  - {rid}")
        return 0

    try:
        route = reg.route(args.route)
        module = importlib.import_module(f"cart_db.downloaders.{reg.downloader}")
    except DownloadError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    except ModuleNotFoundError as exc:
        print(f"✗ 找不到 downloader 模块 `{reg.downloader}`：{exc}", file=sys.stderr)
        return 2

    snap = Snapshot(reg.source_dir, args.snapshot)
    print(f"源 : {reg.source_name}（{reg.path.name}）")
    print(f"路 : {route.route_id} → {reg.downloader}")
    print(f"落 : {snap.dir}")

    try:
        module.run(reg, route, snap, limit=args.limit, dry_run=args.dry_run)
    except DownloadError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        # 即便失败也把已下到的部分记成清单，便于续跑与留证
        if snap.items or snap.skipped:
            path = snap.finish(source_name=reg.source_name, route_id=route.route_id,
                               extra={"failed": str(exc)})
            print(f"  已落盘部分写入清单：{path}")
        return 1

    if args.dry_run:
        print("\n[dry-run] 未落盘")
        return 0

    manifest = snap.finish(source_name=reg.source_name, route_id=route.route_id)
    total = sum(i.bytes for i in snap.items)
    print(f"\n✓ {len(snap.items)} 个文件，{total:,} bytes，跳过 {len(snap.skipped)}")
    print(f"  清单：{manifest}")

    if args.register:
        try:
            n = register_snapshot(reg, snap, route)
            print(f"  已登记 core.source_registry：{n} 条")
        except Exception as exc:
            print(f"  ⚠ 登记失败（不影响已落盘的数据）：{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
