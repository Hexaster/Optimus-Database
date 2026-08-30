#!/usr/bin/env python
"""从一份 PDF / XML / Markdown 文档抽取结构化数据。

    python scripts/extract.py data/raw/europe_pmc/PMC123.xml
    python scripts/extract.py data/raw/ema_epar/carvykti.pdf --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cart_db.extraction import extract_document      # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="要抽取的 .pdf / .xml / .nxml / .md 文件")
    parser.add_argument("--out-dir", default=None, help="结果目录，默认 data/normalised/")
    parser.add_argument("--dry-run", action="store_true",
                        help="只估算 token 与费用，不调模型、不写文件")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    path = Path(args.file)
    if not path.exists():
        print(f"文件不存在：{path}", file=sys.stderr)
        return 1

    rows = extract_document(path, out_dir=args.out_dir, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"写出 {len(rows)} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
