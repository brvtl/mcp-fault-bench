#!/usr/bin/env bash
# Scan a directory tree for things that must not be published. Exits 1 if any pattern matches.
#   scripts/release-scan.sh <dir>
# Each pattern is written so that its own source text does not match it (e.g. `pete[y]`, `/home/bo[x]`),
# so this file scans clean without being skipped. Binary files and .git/ are not scanned.
# One exception is allowed for the owner-name patterns only: the copyright line at the top level of
# <dir>/LICENSE ("Copyright <year> <owner>"), which scripts/release-export.sh writes. Nothing else is allowed.
set -euo pipefail

dir=${1:?usage: release-scan.sh <dir>}
[ -d "$dir" ] || { echo "not a directory: $dir" >&2; exit 2; }
dir=$(cd "$dir" && pwd)

# the single allowed owner-name line: <dir>/LICENSE:<n>:Copyright 20xx <owner>
allowed_rx="^$dir/LICENSE:[0-9]+:Copyright 20[0-9]{2} Pete[r] Garbe[r]s\$"

# name | grep flags | ERE | name-allowlist applies (1/0)
patterns=(
  "GitHub token (gho_/ghp_)|-E|(^|[^A-Za-z0-9])gh[op]_[A-Za-z0-9]{20,}|0"
  "GitHub PAT (github_pat_)|-E|github_pa[t]_[A-Za-z0-9_]{20,}|0"
  "Anthropic key (sk-ant-)|-E|(^|[^A-Za-z0-9])sk-an[t]-[A-Za-z0-9_-]{10,}|0"
  "sk- key|-E|(^|[^A-Za-z0-9_-])s[k]-[A-Za-z0-9_-]{20,}|0"
  "OpenAI project/service/admin key prefix|-E|s[k]-(pro[j]|svcacc[t]|admi[n])-[A-Za-z0-9_-]{4,}|0"
  "Slack token (xox)|-E|(^|[^A-Za-z0-9])xo[x][abprs]-[A-Za-z0-9-]{10,}|0"
  "AWS access key id|-E|AK[I]A[0-9A-Z]{16}|0"
  "PEM private key|-E|-----BEGI[N] [A-Z ]*PRIVATE KE[Y]-----|0"
  "home-dir path (/home/b..x)|-iE|/home/bo[x]|0"
  "workspace path (/w..kspace)|-iE|/workspac[e]|0"
  "rate-limit event records|-iE|rate_limit_even[t]|0"
  "plan wording (M.. subscription)|-iE|max[[:space:]]+subscriptio[n]|0"
  "personal name|-iE|pete[y]|0"
  "owner first name (whole word)|-iwE|pete[r]|1"
  "owner surname|-iE|garbe[r]s?|1"
  "owner domain|-iE|devth[e]\.net|0"
  "usage slash command as list entry|-E|(^|[[,])[[:space:]]*\"(usag[e]|usage-credit[s]|extra-usag[e])\"[[:space:]]*([],]|\$)|0"
  "usage-cr..its / extra-us..e names|-iE|usage-credit[s]|extra-usag[e]|0"
)

fail=0
allowed_total=0
printf '%-40s %8s %6s %8s\n' pattern matches files allowed
for p in "${patterns[@]}"; do
  allow=${p##*|}
  p=${p%|*}
  name=${p%%|*}; rest=${p#*|}
  flags=${rest%%|*}; rx=${rest#*|}
  hits=$(grep -rIHn --exclude-dir=.git $flags -- "$rx" "$dir" || true)
  nallowed=0
  if [ "$allow" = 1 ] && [ -n "$hits" ]; then
    kept=$(printf '%s\n' "$hits" | grep -vE -- "$allowed_rx" || true)
    if [ -n "$kept" ]; then nallowed=$(( $(printf '%s\n' "$hits" | wc -l) - $(printf '%s\n' "$kept" | wc -l) ))
    else nallowed=$(printf '%s\n' "$hits" | wc -l); fi
    hits=$kept
  fi
  allowed_total=$((allowed_total + nallowed))
  if [ -n "$hits" ]; then
    nm=$(printf '%s\n' "$hits" | wc -l)
    nf=$(printf '%s\n' "$hits" | cut -d: -f1 | sort -u | wc -l)
  else nf=0; nm=0; fi
  printf '%-40s %8d %6d %8d\n' "$name" "$nm" "$nf" "$nallowed"
  if [ "$nf" -gt 0 ]; then
    fail=1
    printf '%s\n' "$hits" | cut -d: -f1,2 | head -5 | sed "s|^$dir/*|    |"
  fi
done

if [ "$fail" -ne 0 ]; then echo "release-scan: FAIL ($dir)"; exit 1; fi
echo "release-scan: OK ($dir; $allowed_total allowed LICENSE copyright match(es))"
