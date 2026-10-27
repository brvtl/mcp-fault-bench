"""Fail when tracked files contain absolute box paths, likely secrets, non-noreply email addresses, the owner's
personal name, or plan/usage-limit wording.

    python scripts/audit_public.py [paths ...]     # default: every file tracked by git (results included)
    python scripts/audit_public.py --root DIR      # every file under DIR (except .git/), e.g. a release export

The owner's name is allowed in exactly one place: the copyright line at the top of LICENSE in a release export
(written by scripts/release-export.sh). Anywhere else, including LICENSE in this repo's other lines, it is a finding.

Prints offending file:line: reason and exits 1 when anything is found. Binary files are skipped.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Literal fragments are split so this file does not flag itself.
CHECKS = [
    ("absolute box path", re.compile("/" + "workspace/" + "|" + "/home" + "/box")),
    ("Anthropic key", re.compile(r"\bsk-" + r"ant-[A-Za-z0-9_-]{8,}")),
    ("API key (sk-)", re.compile(r"(?<![A-Za-z0-9_-])sk-" + r"(?:proj-)?[A-Za-z0-9_]{20,}")),
    ("GitHub token", re.compile(r"\bgh" + r"p_[A-Za-z0-9]{20,}|\bgithub" + r"_pat_[A-Za-z0-9_]{20,}")),
    ("AWS access key", re.compile(r"\bAK" + r"IA[0-9A-Z]{16}\b")),
    ("private key block", re.compile("-----" + "BEGIN")),
    ("Slack token", re.compile(r"\bxo" + r"x[bp]-[A-Za-z0-9-]+")),
    ("personal name", re.compile(r"pete" + r"y|\bpete" + r"r\b|garbe" + r"rs?\b|devth" + r"e\.net", re.IGNORECASE)),
    ("rate-limit event record", re.compile(r"rate_limit" + r"_event", re.IGNORECASE)),
    ("plan wording", re.compile(r"max\s+subscri" + r"ption|usage-cred" + r"its|extra-us" + r"age", re.IGNORECASE)),
]
# (relative path, full-line pattern): the only places a "personal name" finding is allowed.
NAME_ALLOWED = [("LICENSE", re.compile(r"Copyright 20\d\d Pete" + r"r Garb" + r"ers"))]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAIL = re.compile(r"@users\.noreply\.github\.com$", re.IGNORECASE)


def tracked_files(root: Path = ROOT) -> list[Path]:
    output = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True).stdout
    return [root / name for name in output.decode("utf-8").split("\0") if name]


def _name_allowed(relpath: str | None, line: str) -> bool:
    return relpath is not None and any(relpath == path and pattern.fullmatch(line.strip())
                                       for path, pattern in NAME_ALLOWED)


def audit_text(text: str, relpath: str | None = None) -> list[tuple[int, str]]:
    """(line number, reason) for every finding in one text; relpath (posix, relative) enables NAME_ALLOWED."""
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for reason, pattern in CHECKS:
            if reason == "personal name" and _name_allowed(relpath, line):
                continue
            if pattern.search(line):
                findings.append((number, reason))
        for match in EMAIL.finditer(line):
            if not ALLOWED_EMAIL.search(match.group()):
                findings.append((number, f"email address {match.group()}"))
    return findings


def all_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts)


def audit_file(path: Path, relpath: str | None = None) -> list[tuple[int, str]]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b"\0" in data[:8192]:
        return []
    return audit_text(data.decode("utf-8", errors="replace"), relpath)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--root", type=Path, help="audit every file under this directory instead of git-tracked files")
    args = parser.parse_args(argv)
    base = args.root.resolve() if args.root else ROOT
    paths = all_files(base) if args.root else [Path(path) for path in args.paths] if args.paths else tracked_files()
    count = 0
    for path in paths:
        absolute = path.resolve()
        relpath = absolute.relative_to(base).as_posix() if absolute.is_relative_to(base) else None
        for number, reason in audit_file(path, relpath):
            shown = relpath or path
            print(f"{shown}:{number}: {reason}")
            count += 1
    print(f"{count} finding(s) in {len(paths)} file(s)", file=sys.stderr)
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main())
