#!/usr/bin/env python3
"""按 mapping doc 把 raw data 解析成待入库记录。

    python scripts/parse.py <mapping> [--limit N] [--parse-date YYYYMMDD] [--dry-run]

<mapping> 可以是 `thera_sabdab_to_binder`、`….yaml` 或完整路径。
真正执行什么，全看该 mapping 的 Part 3「可执行映射」——本脚本不含任何源专属逻辑。

输出落 data/interim/<db>/<source>/<解析日期>/，含 records.jsonl、rejects.jsonl
与 _manifest.json。不写数据库——入库是后续 loader 的事。

例：
    python scripts/parse.py thera_sabdab_to_binder --limit 50
    python scripts/parse.py sabdab_to_binder --dry-run
    python scripts/parse.py --list
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parsers import KNOWN_PARSERS  # noqa: E402
from parsers.base import (  # noqa: E402
    Interim,
    ParseError,
    SourceParser,
    Undecided,
    load_mapping,
)


# Run the legacy mapping parser, distinguishing missing configuration, rejected data, and unresolved
# policy.
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("mapping", nargs="?", help="mapping 名或路径，如 thera_sabdab_to_binder")
    ap.add_argument("--limit", type=int, help="只读前 N 行源记录，用于试跑")
    ap.add_argument("--parse-date", help="interim 目录名，默认今天 YYYYMMDD")
    ap.add_argument("--dry-run", action="store_true",
                    help="只加载 mapping 与 schema 并报告契约是否对得上，不落盘")
    ap.add_argument("--list", action="store_true", help="列出已实现的 parser 后退出")
    args = ap.parse_args()

    # List the available legacy parsers and return before loading source data.
    if args.list:
        # Process each (mid, mod) from KNOWN_PARSERS.items() independently.
        for mid, mod in KNOWN_PARSERS.items():
            print(f"  {mid:28s} → parsers/{mod}.py")
        return 0

    # Reject the input: 需要指定 mapping，或用 --list 查看有哪些.
    if not args.mapping:
        ap.error("需要指定 mapping，或用 --list 查看有哪些")

    # Attempt this operation while preserving the explicit recovery/cleanup paths below.
    try:
        mapping = load_mapping(args.mapping)
    # On ParseError, report this outcome to the command-line operator.
    except ParseError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    # 先按档名查，再拿档内的 mapping_id 兜底。
    # 2026-08-24 实测三份 mapping 里有两份两者不一致：
    #   dotad_to_binder.yaml  → mapping_id: dotad2_to_binder
    #   sabdab_to_binder.yaml → mapping_id: sabdab2_to_binder
    # load_mapping() 本来就是按档名找档的，档名才是稳定的那个键。
    mod_name = KNOWN_PARSERS.get(mapping.path.stem) or KNOWN_PARSERS.get(mapping.mapping_id)
    # When mod name is empty or false, report this outcome to the command-line operator.
    if not mod_name:
        # Prefer ', '.join(KNOWN_PARSERS); if empty or absent, fall back to '（无）'.
        print(
            f"✗ mapping `{mapping.path.stem}`（档内 mapping_id={mapping.mapping_id}）"
            f"还没有对应的 parser。\n  已实现：{', '.join(KNOWN_PARSERS) or '（无）'}",
            file=sys.stderr,
        )
        return 2

    # Attempt this operation while preserving the explicit recovery/cleanup paths below.
    try:
        module = importlib.import_module(f"parsers.{mod_name}")
    # On ModuleNotFoundError, report this outcome to the command-line operator.
    except ModuleNotFoundError as exc:
        print(f"✗ 找不到 parser 模块 `parsers.{mod_name}`：{exc}", file=sys.stderr)
        return 2

    # Collect items from vars(module).values() only where isinstance(v, type) and issubclass(v,
    # SourceParser) and (v is not SourceParser).
    parser_cls = next(
        (v for v in vars(module).values()
         if isinstance(v, type) and issubclass(v, SourceParser) and v is not SourceParser),
        None,
    )
    # When parser cls is absent, report this outcome to the command-line operator.
    if parser_cls is None:
        print(f"✗ parsers/{mod_name}.py 里没有 SourceParser 的子类", file=sys.stderr)
        return 2

    # Attempt this operation while preserving the explicit recovery/cleanup paths below.
    try:
        parser = parser_cls(mapping)
    # On ParseError, report this outcome to the command-line operator.
    except ParseError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    db = parser.targets[0].db_name
    print(f"源  : {mapping.source_name}（{mapping.path.name}，status={mapping.status}）")
    print(f"映射: {mapping.mapping_id} → {mapping.target_schema}")
    # Prefer mapping.record_grain; if empty or absent, fall back to '（mapping 未声明）'.
    print(f"粒度: {mapping.record_grain or '（mapping 未声明）'}")

    # 契约自检：mapping 写了、schema 里却没有的列，是两层脱节最早的信号。
    # 这类问题该在 dry-run 阶段就看见，而不是跑完几万行才发现。
    for t in parser.targets:
        # Build mapped values from t.fields.
        unknown = parser.schemas[t.table].unknown(f.target for f in t.fields)
        # Use f" ⚠ schema 无此列：{', '.join(unknown)}" when unknown is truthy; otherwise use ''.
        flag = f"  ⚠ schema 无此列：{', '.join(unknown)}" if unknown else ""
        print(f"  - {t.table}  记录数/源行={t.record_per_source}  字段={len(t.fields)}{flag}")

    # Preview the planned operation and return before the subsequent execution stage.
    if args.dry_run:
        print("\n[dry-run] 未落盘")
        return 0

    out = Interim(db, parser.source_dir, args.parse_date)
    print(f"落  : {out.dir}")
    # Attempt this operation while preserving the explicit recovery/cleanup paths below.
    try:
        # Release this managed resource when the enclosed operation completes or fails.
        with out:
            parser.run(out, limit=args.limit)
    except Undecided as exc:
        # 未决问题不是崩溃，是骨架按设计停在了该由人决定的地方。
        # 已产出的部分照样写清单，便于看清停之前走到了哪。
        print(f"\n⏸ {exc}", file=sys.stderr)
        path = out.finish(mapping=mapping, extra={"halted_at": exc.qid})
        print(f"  已产出部分写入清单：{path}", file=sys.stderr)
        return 3
    # On ParseError, report this outcome to the command-line operator.
    except ParseError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        path = out.finish(mapping=mapping, extra={"failed": str(exc)})
        print(f"  已产出部分写入清单：{path}", file=sys.stderr)
        return 1

    manifest = out.finish(mapping=mapping)
    print(f"\n✓ 记录 {out.n_records:,}，拒收 {out.n_rejects:,}")
    print(f"  清单：{manifest}")
    return 0


# Run the command only when invoked as a script, not when imported by tests or other modules.
if __name__ == "__main__":
    raise SystemExit(main())
