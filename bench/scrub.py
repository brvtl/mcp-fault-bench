"""Replace machine-specific absolute paths in stored artifacts with portable placeholders."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scrub_text(text: str, root: Path | str = ROOT, home: Path | str | None = None) -> str:
    """Repo root -> ".", temp dirs (/tmp/<name>) -> "<tmp>", home directory -> "~"."""
    boundary = r"(?=[/\"'\s,}\]]|$)"
    for base in sorted({str(Path(root).resolve()), str(root)}, key=len, reverse=True):
        if base not in ("", "/"):
            text = re.sub(re.escape(base) + boundary, ".", text)
    for tmp in sorted({"/tmp", tempfile.gettempdir()}, key=len, reverse=True):
        if tmp not in ("", "/"):
            text = re.sub(re.escape(tmp.rstrip("/")) + r"/[^\s\"'/\\]+", "<tmp>", text)
    home_text = str(home if home is not None else Path.home())
    if home_text not in ("", "/"):
        text = re.sub(re.escape(home_text) + boundary, "~", text)
    return text


def scrub_file(path: Path, root: Path | str = ROOT, home: Path | str | None = None) -> bool:
    """Rewrite one text file in place; True when it changed."""
    try:
        original = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    scrubbed = scrub_text(original, root, home)
    if scrubbed != original:
        path.write_text(scrubbed, encoding="utf-8")
        return True
    return False
