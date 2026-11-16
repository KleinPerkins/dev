#!/usr/bin/env bash
# install-awa-dashboard.sh — build/refresh the AWA worktree status canvas.
#
# The Cursor IDE only renders `.canvas.tsx` files under
# ~/.cursor/projects/<workspace-slug>/canvases/. This script takes the
# source-tracked, data-free seed (_ops/dashboards/awa-dashboard.canvas.tsx), runs
# the READ-ONLY `dev-worktree.sh dashboard-data` emitter, injects that live JSON
# between the seed's AWA_DATA markers, and writes the rendered canvas into the
# workspace canvases directory. Nothing in any repo/worktree is mutated.
#
# Verbs / flags:
#   (default)        refresh: emit live data + publish the rendered canvas
#   --check          assert the tracked seed is data-free (CI gate); no writes
#   --seed           normalize the tracked seed's data block back to empty (maintainer)
#   --print-path     print the resolved workspace canvas path and exit
#   --schedule [--interval MIN]   register a local-jobs refresh (hands-free; opt-in)
#   --unschedule     remove the local-jobs refresh registration
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SEED="$ROOT/_ops/dashboards/awa-dashboard.canvas.tsx"
EMITTER="$SCRIPT_DIR/awa-dashboard-data.py"
CANVAS_NAME="awa-worktree-dashboard.canvas.tsx"
REFRESH_JOB_ID="awa-dashboard-refresh"

die() { printf 'install-awa-dashboard: %s\n' "$*" >&2; exit 1; }
note() { printf 'install-awa-dashboard: %s\n' "$*"; }

[ -f "$SEED" ] || die "missing seed canvas: $SEED"
[ -f "$EMITTER" ] || die "missing emitter: $EMITTER"

# Resolve the Cursor workspace canvases dir for a root (mirrors local-jobs' slug rule:
# Cursor hyphenates both slashes and dots, e.g. /Users/laurence.duggan/dev ->
# Users-laurence-duggan-dev). Honors AWA_DASHBOARD_CANVAS_DIR for tests/overrides.
workspace_canvas_dir() {
  if [ -n "${AWA_DASHBOARD_CANVAS_DIR:-}" ]; then
    printf '%s\n' "$AWA_DASHBOARD_CANVAS_DIR"
    return 0
  fi
  local projects="${AWA_DASHBOARD_CURSOR_PROJECTS_DIR:-$HOME/.cursor/projects}"
  local path_slug hyphen_slug slug
  path_slug="${ROOT#/}"
  path_slug="${path_slug//\//-}"
  hyphen_slug="${path_slug//./-}"
  if [ -d "$projects/$hyphen_slug" ]; then
    slug="$hyphen_slug"
  elif [ -d "$projects/$path_slug" ]; then
    slug="$path_slug"
  else
    slug="$hyphen_slug"
  fi
  printf '%s/%s/canvases\n' "$projects" "$slug"
}

# --- data-block injection / check (python does the parsing robustly) ------------
py_inject() {
  # py_inject <seed> <out> <mode: live|seed> [json-file]
  python3 - "$@" <<'PY'
import json, re, sys
from pathlib import Path

seed, out, mode = sys.argv[1:4]
json_file = sys.argv[4] if len(sys.argv) > 4 else None

EMPTY = {
    "schema": "awa-worktree/v1",
    "generated_at": None,
    "root": "",
    "default_base": "main",
    "summary": {
        "repos": 0, "included": 0, "excluded": 0, "advisory": 0, "worktrees": 0,
        "linked": 0, "dirty": 0, "ahead_of_main": 0, "behind_main": 0,
        "diverged": 0, "no_base": 0, "orphan_branches": 0,
    },
    "repos": [],
}

text = Path(seed).read_text()
start_pat = re.compile(r"^.*AWA_DATA_START.*$", re.M)
end_pat = re.compile(r"^.*AWA_DATA_END.*$", re.M)
ms, me = start_pat.search(text), end_pat.search(text)
if not ms or not me or ms.end() >= me.start():
    raise SystemExit("seed canvas missing AWA_DATA_START/END markers")

if mode == "seed":
    payload = EMPTY
else:
    payload = json.loads(Path(json_file).read_text())
    if payload.get("schema") != "awa-worktree/v1":
        raise SystemExit(f"unexpected emitter schema: {payload.get('schema')!r}")

block = "\nconst INITIAL_RAW = " + json.dumps(payload, indent=2) + " as unknown as DashboardData;\n"
rendered = text[: ms.end()] + block + text[me.start():]
Path(out).write_text(rendered)
print(out)
PY
}

py_check() {
  python3 - "$SEED" <<'PY'
import json, re, sys
from pathlib import Path

EMPTY = {
    "schema": "awa-worktree/v1",
    "generated_at": None,
    "root": "",
    "default_base": "main",
    "summary": {
        "repos": 0, "included": 0, "excluded": 0, "advisory": 0, "worktrees": 0,
        "linked": 0, "dirty": 0, "ahead_of_main": 0, "behind_main": 0,
        "diverged": 0, "no_base": 0, "orphan_branches": 0,
    },
    "repos": [],
}
text = Path(sys.argv[1]).read_text()
m = re.search(r"AWA_DATA_START[^\n]*\n(.*)\n[^\n]*AWA_DATA_END", text, re.S)
if not m:
    raise SystemExit("seed canvas missing AWA_DATA markers")
region = m.group(1)
if "/Users/" in region:
    raise SystemExit("seed canvas carries a machine path — it must stay data-free")
lit = re.search(r"const INITIAL_RAW\s*=\s*(\{.*\})\s*as unknown as DashboardData;", region, re.S)
if not lit:
    raise SystemExit("seed canvas INITIAL_RAW block is malformed")
try:
    data = json.loads(lit.group(1))
except json.JSONDecodeError as exc:
    raise SystemExit(f"seed INITIAL_RAW is not valid JSON: {exc}")
if data != EMPTY:
    raise SystemExit("seed canvas is not data-free — run: install-awa-dashboard.sh --seed")
print("ok")
PY
}

do_check() {
  if py_check >/dev/null; then
    note "seed canvas is data-free and well-formed"
  else
    py_check >/dev/null # surface the error text
    exit 1
  fi
}

do_seed() {
  local tmp; tmp="$(mktemp)"
  py_inject "$SEED" "$tmp" seed >/dev/null
  if cmp -s "$tmp" "$SEED"; then
    rm -f "$tmp"; note "seed already normalized (data-free)"
  else
    mv "$tmp" "$SEED"; note "normalized seed data block to empty: $SEED"
  fi
}

do_refresh() {
  local dir; dir="$(workspace_canvas_dir)"
  mkdir -p "$dir"
  local target="$dir/$CANVAS_NAME"
  local json_tmp; json_tmp="$(mktemp)"
  local out_tmp; out_tmp="$(mktemp)"
  trap 'rm -f "$json_tmp" "$out_tmp"' RETURN

  if ! python3 "$EMITTER" --root "$ROOT" > "$json_tmp"; then
    die "emitter failed"
  fi
  py_inject "$SEED" "$out_tmp" live "$json_tmp" >/dev/null
  mv "$out_tmp" "$target"
  local repos; repos="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["summary"]["repos"])' "$json_tmp")"
  note "wrote live canvas ($repos governed repos): $target"
  printf '%s\n' "$target"
}

do_schedule() {
  local interval_min=10
  while [ $# -gt 0 ]; do
    case "$1" in
      --interval) shift; interval_min="${1:?--interval needs minutes}" ;;
      *) die "unknown --schedule option: $1" ;;
    esac
    shift
  done
  local lj; lj="$(command -v local-jobs.sh || true)"
  [ -n "$lj" ] || lj="$ROOT/capabilities/skills/global/skills/local-jobs/bin/local-jobs.sh"
  if [ ! -x "$lj" ]; then
    note "local-jobs not found; hands-free refresh is optional."
    note "run this manually to schedule it once local-jobs is installed:"
    note "  local-jobs.sh add-job --type command --id $REFRESH_JOB_ID \\"
    note "    --interval-seconds $((interval_min*60)) --program /bin/bash \\"
    note "    --arg $SCRIPT_DIR/install-awa-dashboard.sh"
    return 0
  fi
  note "registering local-jobs refresh '$REFRESH_JOB_ID' every ${interval_min}m via $lj"
  "$lj" add-job --type command --id "$REFRESH_JOB_ID" \
    --interval-seconds "$((interval_min*60))" \
    --program /bin/bash --arg "$SCRIPT_DIR/install-awa-dashboard.sh" || \
    note "local-jobs add-job returned non-zero; run the command above manually"
}

do_unschedule() {
  local lj; lj="$(command -v local-jobs.sh || true)"
  [ -n "$lj" ] || lj="$ROOT/capabilities/skills/global/skills/local-jobs/bin/local-jobs.sh"
  [ -x "$lj" ] || { note "local-jobs not found; nothing to unschedule"; return 0; }
  "$lj" delete-job --id "$REFRESH_JOB_ID" --confirm || note "local-jobs delete-job returned non-zero"
}

verb="${1:-refresh}"
case "$verb" in
  refresh|"") do_refresh ;;
  --check|check) do_check ;;
  --seed|seed) do_seed ;;
  --print-path) workspace_canvas_dir | sed "s#\$#/$CANVAS_NAME#" ;;
  --schedule) shift; do_schedule "$@" ;;
  --unschedule) do_unschedule ;;
  -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown verb: $verb (see --help)" ;;
esac
