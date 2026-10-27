#!/usr/bin/env bash
# Export the committed tree (HEAD) into <target-dir> as a fresh repo with exactly one commit and no remote.
#   RELEASE_AUTHOR="Name <email>" scripts/release-export.sh [target-dir]   # default /tmp/mcp-fault-bench-export
# Only committed files are exported (git archive HEAD): untracked files (posts/), gitignored ones (.venv, caches,
# egg-info, dist) and uncommitted changes are left out. The export's LICENSE gets a "Copyright <year> <holder>" line
# (RELEASE_COPYRIGHT_HOLDER, default: the name in RELEASE_AUTHOR); the license itself stays Apache 2.0.
# The export is checked with scripts/audit_public.py --root and scripts/release-scan.sh before committing; a failure
# aborts with no commit made. The author's name is not stored in this repo: it comes from RELEASE_AUTHOR.
set -euo pipefail

target=${1:-/tmp/mcp-fault-bench-export}
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
author=${RELEASE_AUTHOR:?set RELEASE_AUTHOR=\"Name <email>\"}
[[ $author =~ ^([^<>]*[^<> ])\ +\<([^<> ]+@[^<> ]+)\>$ ]] || { echo "RELEASE_AUTHOR must look like: Name <email>" >&2; exit 2; }
author_name=${BASH_REMATCH[1]}; author_email=${BASH_REMATCH[2]}
holder=${RELEASE_COPYRIGHT_HOLDER:-$author_name}
year=${RELEASE_YEAR:-$(date +%Y)}
python=${PYTHON:-$repo/.venv/bin/python}; [ -x "$python" ] || python=python3

if [ -e "$target" ] && [ -n "$(ls -A "$target")" ]; then echo "target exists and is not empty: $target" >&2; exit 2; fi
if [ -n "$(git -C "$repo" status --porcelain --untracked-files=no)" ]; then echo "note: working tree has uncommitted changes; they are not exported" >&2; fi

mkdir -p "$target"
target=$(cd "$target" && pwd)
git -C "$repo" archive --format=tar HEAD | tar -x -C "$target"
echo "exported $(git -C "$repo" rev-parse --short HEAD) -> $target ($(find "$target" -type f | wc -l) files)"

# nothing that is not meant to ship
leftovers=$(find "$target" \( -name posts -o -name .venv -o -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \
  -o -name .mypy_cache -o -name '*.egg-info' -o -name '*.pyc' \) -print)
if [ -n "$leftovers" ]; then echo "export contains files that must not ship:" >&2; echo "$leftovers" >&2; exit 1; fi

# copyright line (only place the holder's name appears in files)
grep -q '^Apache License' "$target/LICENSE" || { echo "LICENSE is not the Apache 2.0 header" >&2; exit 1; }
{ printf 'Copyright %s %s\n\n' "$year" "$holder"; cat "$target/LICENSE"; } > "$target/LICENSE.new"
mv "$target/LICENSE.new" "$target/LICENSE"

(cd "$repo" && "$python" scripts/audit_public.py --root "$target")
"$repo/scripts/release-scan.sh" "$target"

git -C "$target" init -q -b main
git -C "$target" add -A
GIT_AUTHOR_NAME="$author_name" GIT_AUTHOR_EMAIL="$author_email" \
GIT_COMMITTER_NAME="$author_name" GIT_COMMITTER_EMAIL="$author_email" \
  git -C "$target" -c commit.gpgsign=false commit -q -m "${RELEASE_MESSAGE:-mcp-fault-bench: initial public release}"
echo "committed $(git -C "$target" rev-parse --short HEAD) in $target ($(git -C "$target" rev-list --count HEAD) commit," \
  "remotes: $(git -C "$target" remote | wc -l), author: $(git -C "$target" log -1 --format='%an <%ae>'))"
