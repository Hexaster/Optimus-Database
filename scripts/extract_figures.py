#!/usr/bin/env python
"""Offline rendering/export helper used by the dedicated figure extraction agent."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

# Make repository checkout execution work without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cart_db.figures import export_figures, render_pages, validate_figures


def main() -> int:
    """Parse one explicit operation and report validation errors without a traceback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("render", "export", "validate"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, help="Agent-authored JSONL to copy into the output directory before export")
    parser.add_argument("--pages", help="Comma-separated 1-based page numbers for render")
    parser.add_argument("--dpi", type=int, help="Defaults: render 100, export 200")
    args = parser.parse_args()
    try:
        # Rendering and exporting need source content; validation can check hashes alone.
        if args.command != "validate" and args.source is None:
            parser.error("--source is required for render/export")
        if args.command == "render":
            pages = [int(value) for value in args.pages.split(",")] if args.pages else None
            records = render_pages(args.source, args.output_dir, pages, dpi=args.dpi or 100)
        elif args.command == "export":
            args.output_dir.mkdir(parents=True, exist_ok=True)
            target = args.output_dir / "figures.jsonl"
            # An external inventory is copied only when it is not already the target.
            if args.inventory is not None and args.inventory.resolve() != target.resolve():
                if target.is_symlink():
                    raise ValueError("Inventory output cannot be a symlink")
                shutil.copyfile(args.inventory, target)
            records = export_figures(args.source, args.output_dir, dpi=args.dpi or 200)
        else:
            records = validate_figures(args.output_dir, args.source)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Figure {args.command} failed: {exc}", file=sys.stderr)
        return 1
    print(f"{args.command}: {len(records)} records; output={args.output_dir}")
    return 0


# Importing the helper must not execute the command-line workflow.
if __name__ == "__main__":
    raise SystemExit(main())
