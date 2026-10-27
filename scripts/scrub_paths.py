"""Rewrite tracked result files so they carry no machine-specific absolute paths.

    python scripts/scrub_paths.py [--root <repo root the runs were recorded in>] [--dry-run] [paths ...]

Default paths: every git-tracked file under results/. The repo root becomes ".", /tmp/<name> becomes "<tmp>"
and the home directory becomes "~" (bench/scrub.py, the same rules the arena now applies to new runs).
Run results/summary.* and scripts/audit_public.py afterwards.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.scrub import scrub_file, scrub_text  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT), help="absolute repo root to replace (default: this checkout)")
    parser.add_argument("--home", help="home directory to replace with ~ (default: the current user's)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if args.paths:
        paths = [Path(path) for path in args.paths]
    else:
        listed = subprocess.run(["git", "ls-files", "-z", "results"], cwd=ROOT, check=True, capture_output=True).stdout
        paths = [ROOT / name for name in listed.decode("utf-8").split("\0") if name]
    changed = 0
    for path in paths:
        if args.dry_run:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            hit = scrub_text(text, args.root, args.home) != text
        else:
            hit = scrub_file(path, args.root, args.home)
        if hit:
            changed += 1
            print(("would rewrite " if args.dry_run else "rewrote ") + str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path))
    print(f"{changed} of {len(paths)} file(s) {'would change' if args.dry_run else 'changed'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
