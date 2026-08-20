#!/usr/bin/env python3
"""建表：执行 sql/ 下的全部脚本。加 --reset 先整库删除再建。"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cart_db.db import apply_ddl, drop_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true",
                    help="先 DROP SCHEMA 再重建（Schema 改动后用）")
    args = ap.parse_args()

    if args.reset:
        confirm = input("将删除全部 schema 与数据，输入 yes 确认：")
        if confirm.strip().lower() != "yes":
            print("已取消")
            return 1
        drop_all()
        print("已删除全部 schema")

    for name in apply_ddl():
        print(f"  已执行 {name}")
    print("建表完成（脚本幂等，可反复执行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
