#!/usr/bin/env bash
set -euo pipefail

# Pre-commit runs with GIT_DIR/GIT_INDEX_FILE and friends set for the parent repo. The
# disposable RepoFixture repos test_profile.py/test_fleet.py create under /tmp must use
# their own git metadata, not the parent's -- otherwise `git init` there silently
# re-initializes the parent repo instead (see worktree-verify.sh for the same guard).
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_ROOT="$(cd "$HERE/../../../.." && pwd)"
PYCACHE="$(mktemp -d)"
trap 'rm -rf "$PYCACHE"' EXIT
export PYTHONPYCACHEPREFIX="$PYCACHE"

python3 -m py_compile "$HERE/profile.py" "$HERE/fleet.py" "$HERE/test_profile.py" "$HERE/test_fleet.py"
python3 -m unittest -v "$HERE/test_profile.py" "$HERE/test_fleet.py"

python3 - "$HERE" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
schema = json.loads((root / "config.schema.json").read_text())
config = json.loads((root / "config.json").read_text())
assert schema["additionalProperties"] is False
assert set(config) == set(schema["required"])
assert config["schema"] == "pr-automation/v1"
assert config["required_check"] == {"context": "required / ci", "integration_id": 15368}
assert all(config["settings"].values())

phase_b_schema = json.loads((root / "phase-b.config.schema.json").read_text())
phase_b = json.loads((root / "phase-b.config.json").read_text())
fleet_schema = json.loads((root / "fleet.schema.json").read_text())
fleet = json.loads((root / "fleet.json").read_text())
evidence_schema = json.loads((root / "phase-b.evidence.schema.json").read_text())
state_schema = json.loads((root / "phase-b.state.schema.json").read_text())
assert all(value["additionalProperties"] is False for value in (
    phase_b_schema, fleet_schema, evidence_schema, state_schema
))
assert phase_b["schema"] == "pr-automation/v2"
assert phase_b["hard_exclusions"] == ["KleinPerkins/chaos-scheduler"]
assert len(fleet["targets"]) == 12
assert "KleinPerkins/chaos-scheduler" not in {item["repo"] for item in fleet["targets"]}
assert "KleinPerkins/chaos-scheduler" in {item["repo"] for item in fleet["excluded"]}

try:
    import yaml
except ImportError:
    print("YAML parser unavailable; structural YAML assertions remain covered by unit tests")
else:
    value = yaml.load((root / "required.yml").read_text(), Loader=yaml.BaseLoader)
    assert isinstance(value, dict) and "jobs" in value
    assert "ci" in value["jobs"]
    print("YAML parse: OK")
PY

bash -n "$DEV_ROOT/_ops/bin/repo-baseline.sh"
bash -n "$DEV_ROOT/_ops/bin/dev-new-repo.sh"

if command -v actionlint >/dev/null 2>&1; then
  actionlint "$HERE/required.yml"
  rendered="$(mktemp)"
  python3 - "$HERE" "$rendered" <<'PY'
import importlib.util
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("fleet", root / "fleet.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
pathlib.Path(sys.argv[2]).write_text(
    module.render_controller(module.render_policy("KleinPerkins/demo", "main"))
)
PY
  actionlint "$rendered"
  rm -f "$rendered"
  echo "actionlint: OK"
else
  echo "actionlint unavailable; strict-subset and legal-flow fixtures remain covered by unit tests"
fi

if rg -n 'uses:\s*[^ @]+@(?![0-9a-f]{40}(?:\s|#|$))' "$HERE/required.yml" \
  --pcre2 >/dev/null; then
  echo "non-full-SHA action pin found" >&2
  exit 1
fi

# Preserve settings-GET failure propagation at the historical helper boundary.
# The top-level settings mutator now refuses unconditionally; this helper is
# exercised with a shell function fake, without network, HOME overrides or state.
(
  . "$DEV_ROOT/_ops/bin/baseline-lib.sh"
  bl_gh_timeout() { return 1; }
  rc=0
  bl_ensure_repo_settings KleinPerkins/fixture >/dev/null || rc=$?
  [ "$rc" -eq 1 ] || { echo "settings lookup failure did not propagate" >&2; exit 1; }
)
echo "historical profile parser/settings failure tests: OK"
